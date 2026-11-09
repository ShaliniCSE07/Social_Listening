"""Collection run execution engine."""
from dataclasses import asdict
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

from src.collection.agent import Decision, plan_decisions, sanitize_secrets
from src.collection.base import BaseConnector, CollectionRequest
from src.collection.budget import BudgetTracker
from src.collection.executor import ExecutionResult, TaskOutcome, execute, write_outputs
from src.collection.planner import InvalidCompany, Plan, Planner
from src.contracts.enums import AttemptStatus, Method, Platform
from src.contracts.schemas import CollectionAttempt, RawMention
from src.service.models import CreateRunRequest
from src.service.run_store import run_store

logger = logging.getLogger(__name__)


def sanitize_secret(text: str) -> str:
    """Ensure no secrets or tokens leak in error messages."""
    if not text:
        return ""
    res = str(text)
    for var in (
        "REDDIT_CLIENT_SECRET",
        "REDDIT_CLIENT_ID",
        "GOOGLE_PLACES_API_KEY",
        "GOOGLE_MAPS_API_KEY",
        "KAGGLE_KEY",
        "KAGGLE_USERNAME",
        "HUGGINGFACE_TOKEN",
        "SECRET_KEY",
    ):
        val = os.environ.get(var, "").strip()
        if val and val in res:
            res = res.replace(val, "[REDACTED]")
    return sanitize_secrets(res)


def sanitize_obj(obj: Any) -> Any:
    """Recursively sanitize any strings within dicts, lists, or primitives."""
    if isinstance(obj, str):
        return sanitize_secret(obj)
    elif isinstance(obj, dict):
        return {k: sanitize_obj(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_obj(item) for item in obj]
    elif isinstance(obj, tuple):
        return tuple(sanitize_obj(item) for item in obj)
    return obj


class ConnectorRegistryHelper:
    """Registry adapter that resolves mock or registered connectors for agent and executor."""

    def __init__(self, connector_classes: List[Type[BaseConnector]]):
        self.classes = list(connector_classes)
        self._by_name: Dict[str, Type[BaseConnector]] = {
            getattr(c, "name", c.__name__): c for c in connector_classes
        }

    def get(self, name: str, default: Any = None) -> Any:
        # 1. Exact name match
        if name in self._by_name:
            return self._by_name[name]

        # 2. Match by platform/method if candidate name relates to it
        name_lower = name.lower()
        for c in self.classes:
            plats = [
                p.value.lower() if isinstance(p, Platform) else str(p).lower()
                for p in getattr(c, "platforms", [])
            ]
            if any(p in name_lower for p in plats):
                return c

            method = getattr(c, "method", None)
            method_str = method.value.lower() if hasattr(method, "value") else str(method).lower()
            if method_str in name_lower:
                return c

        return default

    def get_connector(self, name: str) -> Optional[Any]:
        return self.get(name)

    def __getitem__(self, name: str) -> Any:
        res = self.get(name)
        if res is None:
            raise KeyError(name)
        return res

    def __contains__(self, name: str) -> bool:
        return self.get(name) is not None


class RunRunner:
    """Orchestrates collection across companies and connectors for a run."""

    def __init__(
        self,
        connector_classes: Optional[List[Type[BaseConnector]]] = None,
        policy: Optional[Any] = None,
    ):
        self.connector_classes = connector_classes
        self.policy = policy

    def run(self, run_id: str, request: CreateRunRequest) -> Dict[str, Any]:
        """Execute full collection pipeline: planner -> agent -> executor."""
        started_at = datetime.now(timezone.utc)
        current_summary = run_store.get_run(run_id) or {}

        try:
            tracker = BudgetTracker(limit_usd=request.budget_usd)
            current_summary["status"] = "running"
            current_summary["started_at"] = started_at.isoformat()
            current_summary["budget_snapshot"] = tracker.snapshot()
            run_store.save_run_summary(run_id, current_summary)

            # 1. Build planner input
            planner_input = {
                "companies": [
                    {
                        "name": c.name,
                        "alt_spellings": c.alt_spellings or [],
                        "handles": c.handles or [],
                        "branches": c.branches or [],
                        "industry": c.industry,
                        "platforms": getattr(c, "platforms", None),
                        "dataset_keys": getattr(c, "dataset_keys", None),
                        "date_from": getattr(c, "date_from", None),
                        "date_to": getattr(c, "date_to", None),
                        "budget_usd": getattr(c, "budget_usd", None),
                        "scraping_allowed": getattr(c, "scraping_allowed", None),
                    }
                    for c in request.companies
                ],
                "date_from": request.date_from,
                "date_to": request.date_to,
                "budget_usd": tracker.limit_usd,
                "run_id": run_id,
                "max_age_days": (
                    float(request.max_age_days)
                    if request.max_age_days is not None
                    else None
                ),
                "require_fresh": bool(request.require_fresh),
                "refresh": bool(getattr(request, "refresh", False)),
                "scraping_allowed": bool(getattr(request, "scraping_allowed", False)),
            }
            if request.sources:
                if request.sources.api is not None:
                    planner_input["platforms"] = list(request.sources.api)
                if request.sources.dataset_keys is not None:
                    planner_input["dataset_keys"] = list(request.sources.dataset_keys)

            # 2. Planner execution
            supported_plats: List[Platform] = []
            if self.connector_classes:
                for cls in self.connector_classes:
                    for p in getattr(cls, "platforms", []):
                        if p not in supported_plats:
                            supported_plats.append(p)
            planner = Planner(supported_platforms=supported_plats if supported_plats else None)
            plan_obj = planner.plan(planner_input)

            invalid_data = [
                {"name": inv.name, "reasons": inv.reasons}
                if hasattr(inv, "name") else dict(inv)
                for inv in plan_obj.invalid
            ]

            # If no valid companies, fail immediately
            if not plan_obj.requests:
                finished_at = datetime.now(timezone.utc)
                inv_msgs = [
                    f"{inv.get('name', 'Unknown')}: {', '.join(inv.get('reasons', []))}"
                    for inv in invalid_data
                ]
                err_msg = f"No valid companies to process. Invalid companies: {'; '.join(inv_msgs)}" if inv_msgs else "No valid companies specified"
                empty_res = ExecutionResult(budget_snapshot=tracker.snapshot())
                run_dir = run_store._get_run_dir(run_id)
                write_outputs(empty_res, run_dir)

                summary = {
                    "run_id": run_id,
                    "status": "failed",
                    "error": err_msg,
                    "created_at": current_summary.get("created_at", started_at.isoformat()),
                    "started_at": started_at.isoformat(),
                    "finished_at": finished_at.isoformat(),
                    "companies": [c.name for c in request.companies],
                    "counts": {
                        "mentions_count": 0,
                        "attempts_count": 0,
                        "cost_usd": 0.0,
                    },
                    "budget_snapshot": tracker.snapshot(),
                    "progress": {},
                    "per_source_results": {},
                    "task_outcomes": [],
                    "decisions": [],
                    "invalid_companies": invalid_data,
                }
                run_store.save_run_summary(run_id, summary)
                return summary

            # 3. Agent planning decisions
            registry = (
                ConnectorRegistryHelper(self.connector_classes)
                if self.connector_classes
                else None
            )
            decisions = plan_decisions(
                plan_obj,
                registry=registry,
                budget=tracker,
                policy=self.policy,
            )

            # 4. Executor execution
            exec_result = execute(
                plan_obj,
                decisions,
                registry=registry,
                budget=tracker,
                policy=self.policy,
            )

            # 5. Write artifacts under data/runs/<run_id>/ using write_outputs
            run_dir = run_store._get_run_dir(run_id)
            write_outputs(exec_result, run_dir)

            # 6. Evaluate status per task and overall run status
            has_invalid = bool(plan_obj.invalid)
            if not exec_result.task_outcomes:
                overall_status = "failed"
            else:
                task_statuses: List[str] = []
                for t in exec_result.task_outcomes:
                    # Collect attempts for this specific task
                    t_atts = [
                        a for a in exec_result.attempts
                        if a.company.lower() == t.company.lower()
                        and (
                            (hasattr(a.platform, "value") and a.platform.value.lower() == t.platform.lower())
                            or str(a.platform).lower() == t.platform.lower()
                        )
                    ]
                    has_failed_att = any(a.status == AttemptStatus.failed for a in t_atts)

                    if t.status == "ok":
                        task_statuses.append("ok")
                    elif t.total_items > 0 and not has_failed_att:
                        task_statuses.append("ok")
                    elif t.total_items > 0:
                        task_statuses.append("partial")
                    else:
                        task_statuses.append("failed")

                if all(s == "ok" for s in task_statuses) and not has_invalid:
                    overall_status = "completed"
                elif any(s == "ok" for s in task_statuses) or any(s == "partial" for s in task_statuses):
                    overall_status = "partial"
                else:
                    overall_status = "failed"

            finished_at = datetime.now(timezone.utc)
            total_cost = sum(a.cost_usd for a in exec_result.attempts)

            # Construct task outcomes data with compatibility fields
            outcomes_data = []
            for t in exec_result.task_outcomes:
                d = asdict(t)
                d["items"] = t.total_items
                d["task"] = {"company": t.company, "platform": t.platform}
                outcomes_data.append(d)

            # Company progress for backward compatibility
            company_progress: Dict[str, Dict[str, Any]] = {}
            for comp in request.companies:
                comp_mentions = [
                    m for m in exec_result.mentions if m.company.lower() == comp.name.lower()
                ]
                comp_attempts = [
                    a for a in exec_result.attempts if a.company.lower() == comp.name.lower()
                ]
                comp_sources: Dict[str, Dict[str, Any]] = {}
                for att in comp_attempts:
                    s_name = getattr(att, "source", None) or (
                        att.platform.value if hasattr(att.platform, "value") else str(att.platform)
                    )
                    comp_sources[s_name] = {
                        "status": (
                            att.status.value if hasattr(att.status, "value") else str(att.status)
                        ),
                        "mentions": att.item_count,
                    }
                company_progress[comp.name] = {
                    "mentions_count": len(comp_mentions),
                    "attempts_count": len(comp_attempts),
                    "sources": comp_sources,
                }

            # Per source results for backward compatibility
            per_source_results: Dict[str, Dict[str, Any]] = {}
            for att in exec_result.attempts:
                src_key = att.platform.value if hasattr(att.platform, "value") else str(att.platform)
                method_str = att.method.value if hasattr(att.method, "value") else str(att.method)
                if src_key not in per_source_results:
                    per_source_results[src_key] = {
                        "name": src_key,
                        "method": method_str,
                        "status": (
                            att.status.value if hasattr(att.status, "value") else str(att.status)
                        ),
                        "mentions_count": 0,
                        "attempts_count": 0,
                    }
                per_source_results[src_key]["attempts_count"] += 1
                per_source_results[src_key]["mentions_count"] += att.item_count
                if att.status == AttemptStatus.success:
                    per_source_results[src_key]["status"] = "success"
                elif per_source_results[src_key]["status"] != "success":
                    per_source_results[src_key]["status"] = (
                        att.status.value if hasattr(att.status, "value") else str(att.status)
                    )

            decisions_data = [d.to_dict() for d in decisions]
            sanitized_decisions = sanitize_obj(decisions_data)

            summary = {
                "run_id": run_id,
                "status": overall_status,
                "created_at": current_summary.get("created_at", started_at.isoformat()),
                "started_at": started_at.isoformat(),
                "finished_at": finished_at.isoformat(),
                "companies": [c.name for c in request.companies],
                "counts": {
                    "mentions_count": len(exec_result.mentions),
                    "attempts_count": len(exec_result.attempts),
                    "cost_usd": round(total_cost, 4),
                },
                "budget_snapshot": tracker.snapshot(),
                "progress": company_progress,
                "per_source_results": per_source_results,
                "task_outcomes": outcomes_data,
                "decisions": sanitized_decisions,
                "invalid_companies": invalid_data,
            }

            if overall_status == "failed":
                failed_reasons = [
                    a.reason
                    for a in exec_result.attempts
                    if a.status == AttemptStatus.failed and a.reason
                ]
                if not failed_reasons:
                    failed_reasons = [d.summary for d in decisions if d.summary]
                summary["error"] = (
                    failed_reasons[0] if failed_reasons else "All collection tasks failed"
                )

            run_store.save_run_summary(run_id, summary)
            return summary

        except Exception as unexpected_err:
            finished_at = datetime.now(timezone.utc)
            clean_error = sanitize_secret(str(unexpected_err))
            summary = {
                "run_id": run_id,
                "status": "failed",
                "error": clean_error,
                "created_at": current_summary.get("created_at", started_at.isoformat()),
                "started_at": started_at.isoformat(),
                "finished_at": finished_at.isoformat(),
                "companies": [c.name for c in request.companies],
                "counts": {
                    "mentions_count": 0,
                    "attempts_count": 0,
                    "cost_usd": 0.0,
                },
                "budget_snapshot": current_summary.get("budget_snapshot", {}),
                "progress": {},
                "per_source_results": {},
                "task_outcomes": [],
                "decisions": [],
                "invalid_companies": [],
            }
            try:
                run_store.save_run_summary(run_id, summary)
            except Exception:
                pass
            return summary


# Default global runner
default_runner = RunRunner()
