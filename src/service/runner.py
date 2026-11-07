"""Collection run execution engine."""
from datetime import datetime, timezone
import logging
import os
from typing import Any, Dict, List, Optional, Type

from src.collection.base import BaseConnector, CollectionRequest
from src.collection.budget import BudgetTracker
from src.collection.registry import get_all_connectors
from src.contracts.enums import AttemptStatus, Method, Platform
from src.contracts.schemas import CollectionAttempt, RawMention
from src.service.models import CreateRunRequest
from src.service.run_store import run_store

logger = logging.getLogger(__name__)


def sanitize_secret(text: str) -> str:
    """Ensure no secrets or tokens leak in error messages."""
    for var in (
        "REDDIT_CLIENT_SECRET",
        "REDDIT_CLIENT_ID",
        "GOOGLE_PLACES_API_KEY",
        "KAGGLE_KEY",
        "HUGGINGFACE_TOKEN",
    ):
        val = os.environ.get(var, "").strip()
        if val and val in text:
            text = text.replace(val, "[REDACTED]")
    return text


def resolve_connectors(
    sources: Optional[Any],
    connector_classes: Optional[List[Type[BaseConnector]]] = None,
) -> List[BaseConnector]:
    """Resolve and instantiate connectors based on sources configuration."""
    available_classes = connector_classes or get_all_connectors()
    instances: List[BaseConnector] = []

    # If no sources specified at all, select all available non-scraping connectors
    if sources is None or (sources.api is None and sources.dataset_keys is None):
        for cls in available_classes:
            try:
                if getattr(cls, "method", None) == Method.scraping:
                    continue
                instances.append(cls())
            except Exception as e:
                logger.warning("Could not instantiate connector %s: %s", cls, e)
        return instances

    # Filter API connectors by platform
    if sources.api:
        requested_platforms = {p.lower() for p in sources.api}
        for cls in available_classes:
            if getattr(cls, "method", None) == Method.api:
                cls_platforms = {p.value.lower() for p in getattr(cls, "platforms", [])}
                if cls_platforms & requested_platforms:
                    instances.append(cls())

    # Dataset connector if dataset_keys specified
    if sources.dataset_keys is not None:
        for cls in available_classes:
            if getattr(cls, "method", None) == Method.dataset:
                instances.append(cls())
                break

    return instances


class RunRunner:
    """Orchestrates collection across companies and connectors for a run."""

    def __init__(self, connector_classes: Optional[List[Type[BaseConnector]]] = None):
        self.connector_classes = connector_classes

    def run(self, run_id: str, request: CreateRunRequest) -> Dict[str, Any]:
        """Execute all selected sources for all companies synchronously."""
        started_at = datetime.now(timezone.utc)
        all_mentions: List[RawMention] = []
        all_attempts: List[CollectionAttempt] = []
        per_source_results: Dict[str, Dict[str, Any]] = {}
        company_progress: Dict[str, Dict[str, Any]] = {}
        current_summary = run_store.get_run(run_id) or {}

        try:
            tracker = BudgetTracker(limit_usd=request.budget_usd)
            current_summary["status"] = "running"
            current_summary["started_at"] = started_at.isoformat()
            current_summary["budget_snapshot"] = tracker.snapshot()
            run_store.save_run_summary(run_id, current_summary)

            connectors = resolve_connectors(request.sources, self.connector_classes)

            for company in request.companies:
                comp_attempts: List[CollectionAttempt] = []
                comp_mentions: List[RawMention] = []
                comp_source_info: Dict[str, Dict[str, Any]] = {}

                try:
                    # Build CollectionRequest ensuring strictly valid types
                    col_req = CollectionRequest(
                        company=company.name,
                        alt_spellings=list(company.alt_spellings or []),
                        handles=list(company.handles or []),
                        branches=list(company.branches or []),
                        industry=company.industry,
                        date_from=request.date_from,
                        date_to=request.date_to,
                        budget_usd=tracker.limit_usd,
                        run_id=run_id,
                        dataset_keys=(
                            list(request.sources.dataset_keys)
                            if request.sources and request.sources.dataset_keys is not None
                            else None
                        ),
                        max_age_days=(
                            float(request.max_age_days)
                            if request.max_age_days is not None
                            else None
                        ),
                        require_fresh=bool(request.require_fresh),
                        refresh=bool(getattr(request, "refresh", False)),
                    )

                    for conn in connectors:
                        conn_name = getattr(conn, "name", str(conn.__class__.__name__))
                        conn_method = getattr(conn, "method", Method.api)
                        conn_platforms = getattr(conn, "platforms", [Platform.other])
                        primary_platform = conn_platforms[0] if conn_platforms else Platform.other

                        if conn_name not in per_source_results:
                            per_source_results[conn_name] = {
                                "name": conn_name,
                                "method": (
                                    conn_method.value
                                    if hasattr(conn_method, "value")
                                    else str(conn_method)
                                ),
                                "status": "pending",
                                "mentions_count": 0,
                                "attempts_count": 0,
                            }

                        # Wrap each source individually so one failing source gives partial
                        try:
                            # 1. Check can_run
                            try:
                                can_run, reason = conn.can_run(col_req)
                            except Exception as e:
                                can_run, reason = False, f"Check error: {sanitize_secret(str(e))}"

                            if not can_run:
                                now = datetime.now(timezone.utc)
                                clean_reason = sanitize_secret(reason)
                                skipped_att = CollectionAttempt(
                                    company=company.name,
                                    platform=primary_platform,
                                    method=conn_method,
                                    status=AttemptStatus.skipped,
                                    reason=clean_reason,
                                    item_count=0,
                                    cost_usd=0.0,
                                    started_at=now,
                                    finished_at=now,
                                )
                                all_attempts.append(skipped_att)
                                comp_attempts.append(skipped_att)
                                comp_source_info[conn_name] = {
                                    "status": "skipped",
                                    "reason": clean_reason,
                                    "mentions": 0,
                                }
                                per_source_results[conn_name]["status"] = "skipped"
                                per_source_results[conn_name]["attempts_count"] += 1
                                continue

                            # 2. Budget check and reservation
                            cost_est = conn.estimate_cost(col_req)
                            if not tracker.can_afford(primary_platform, cost_est):
                                exhausted_att = tracker.create_exhausted_attempt(
                                    company.name, primary_platform, conn_method
                                )
                                all_attempts.append(exhausted_att)
                                comp_attempts.append(exhausted_att)
                                comp_source_info[conn_name] = {
                                    "status": "budget_exhausted",
                                    "mentions": 0,
                                }
                                per_source_results[conn_name]["status"] = "budget_exhausted"
                                per_source_results[conn_name]["attempts_count"] += 1
                                continue

                            token = tracker.reserve(primary_platform, cost_est)

                            # 3. Run collection
                            try:
                                mentions, att_or_atts = conn.collect(col_req)
                                collected_atts = (
                                    att_or_atts if isinstance(att_or_atts, list) else [att_or_atts]
                                )
                                actual_cost = sum(a.cost_usd for a in collected_atts)
                                tracker.commit(token, actual_cost)

                                all_mentions.extend(mentions)
                                comp_mentions.extend(mentions)
                                all_attempts.extend(collected_atts)
                                comp_attempts.extend(collected_atts)

                                primary_status = (
                                    collected_atts[0].status.value if collected_atts else "success"
                                )
                                comp_source_info[conn_name] = {
                                    "status": primary_status,
                                    "mentions": len(mentions),
                                }
                                per_source_results[conn_name]["status"] = primary_status
                                per_source_results[conn_name]["mentions_count"] += len(mentions)
                                per_source_results[conn_name]["attempts_count"] += len(collected_atts)

                            except Exception as exc:
                                tracker.release(token)
                                now = datetime.now(timezone.utc)
                                err_msg = sanitize_secret(str(exc))
                                failed_att = CollectionAttempt(
                                    company=company.name,
                                    platform=primary_platform,
                                    method=conn_method,
                                    status=AttemptStatus.failed,
                                    reason=f"Connector failure: {err_msg}",
                                    item_count=0,
                                    cost_usd=0.0,
                                    started_at=now,
                                    finished_at=now,
                                )
                                all_attempts.append(failed_att)
                                comp_attempts.append(failed_att)
                                comp_source_info[conn_name] = {
                                    "status": "failed",
                                    "reason": err_msg,
                                    "mentions": 0,
                                }
                                per_source_results[conn_name]["status"] = "failed"
                                per_source_results[conn_name]["attempts_count"] += 1

                        except Exception as source_err:
                            now = datetime.now(timezone.utc)
                            err_msg = sanitize_secret(str(source_err))
                            failed_att = CollectionAttempt(
                                company=company.name,
                                platform=primary_platform,
                                method=conn_method,
                                status=AttemptStatus.failed,
                                reason=f"Source execution error: {err_msg}",
                                item_count=0,
                                cost_usd=0.0,
                                started_at=now,
                                finished_at=now,
                            )
                            all_attempts.append(failed_att)
                            comp_attempts.append(failed_att)
                            comp_source_info[conn_name] = {
                                "status": "failed",
                                "reason": err_msg,
                                "mentions": 0,
                            }
                            per_source_results[conn_name]["status"] = "failed"
                            per_source_results[conn_name]["attempts_count"] += 1

                except Exception as comp_err:
                    logger.error("Error processing company %s: %s", company.name, comp_err)

                company_progress[company.name] = {
                    "mentions_count": len(comp_mentions),
                    "attempts_count": len(comp_attempts),
                    "sources": comp_source_info,
                }

            # Determine overall run status
            has_success = any(
                a.status in (AttemptStatus.success, AttemptStatus.empty) for a in all_attempts
            )
            has_failure = any(a.status == AttemptStatus.failed for a in all_attempts)

            if has_success and has_failure:
                overall_status = "partial"
            elif has_failure and not has_success:
                overall_status = "failed"
            else:
                overall_status = "completed"

            finished_at = datetime.now(timezone.utc)
            total_cost = sum(a.cost_usd for a in all_attempts)

            summary = {
                "run_id": run_id,
                "status": overall_status,
                "created_at": current_summary.get("created_at", started_at.isoformat()),
                "started_at": started_at.isoformat(),
                "finished_at": finished_at.isoformat(),
                "companies": [c.name for c in request.companies],
                "counts": {
                    "mentions_count": len(all_mentions),
                    "attempts_count": len(all_attempts),
                    "cost_usd": round(total_cost, 4),
                },
                "budget_snapshot": tracker.snapshot(),
                "progress": company_progress,
                "per_source_results": per_source_results,
            }

            if overall_status == "failed":
                failed_reasons = [
                    a.reason for a in all_attempts if a.status == AttemptStatus.failed and a.reason
                ]
                summary["error"] = (
                    failed_reasons[0] if failed_reasons else "All collection sources failed"
                )

            run_store.save_artifacts(run_id, all_mentions, all_attempts)
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
                    "mentions_count": len(all_mentions),
                    "attempts_count": len(all_attempts),
                    "cost_usd": round(sum(a.cost_usd for a in all_attempts), 4),
                },
                "budget_snapshot": current_summary.get("budget_snapshot", {}),
                "progress": company_progress,
                "per_source_results": per_source_results,
            }
            try:
                run_store.save_artifacts(run_id, all_mentions, all_attempts)
                run_store.save_run_summary(run_id, summary)
            except Exception:
                pass
            return summary


# Default global runner
default_runner = RunRunner()
