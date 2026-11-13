"""Collection Agent module for collection method selection and orchestration.

Implements data-driven candidate evaluation, ranking, and decision-making for tasks.
"""
import argparse
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Union

from src.collection.base import BaseConnector, CollectionRequest
from src.collection.budget import BudgetTracker
from src.collection.common.dates import to_utc
from src.collection.planner import Task
from src.collection.plugins.dataset.catalogue import load_dataset_catalogue
from src.collection.policy import PolicyCandidate, SourcePolicy, load_source_policy
from src.collection.policy import load_scraping_sites_cfg, platform_has_scrapable_site
from src.contracts.enums import Platform


def sanitize_secrets(text: str) -> str:
    """Mask known credentials and sensitive token patterns from text."""
    if not text:
        return ""
    res = str(text)

    # Check common credential environment variables
    secret_env_vars = (
        "REDDIT_CLIENT_ID",
        "REDDIT_CLIENT_SECRET",
        "GOOGLE_MAPS_API_KEY",
        "KAGGLE_KEY",
        "KAGGLE_USERNAME",
        "HUGGINGFACE_TOKEN",
        "SECRET_KEY",
    )
    for var in secret_env_vars:
        val = os.environ.get(var, "").strip()
        if val and len(val) >= 4 and val in res:
            res = res.replace(val, "[REDACTED]")

    # Mask token-like patterns
    res = re.sub(r"(Bearer\s+)[A-Za-z0-9_\-\.]{8,}", r"\1[REDACTED]", res, flags=re.IGNORECASE)
    res = re.sub(r"(key|secret|token|password)=([A-Za-z0-9_\-\.]{8,})", r"\1=[REDACTED]", res, flags=re.IGNORECASE)
    return res


@dataclass
class Candidate:
    """An eligible, ranked collection method candidate."""

    connector: str
    method: str
    cost_class: str
    reason: str
    estimated_cost: float = 0.0
    conditional: bool = False
    conditions: Optional[List[str]] = None
    conditions_status: Optional[Dict[str, Optional[bool]]] = None
    known_conditions: Optional[Dict[str, bool]] = None
    role: str = "first_choice"


@dataclass
class Rejected:
    """A collection method candidate that failed eligibility checks."""

    connector: str
    reason: str


@dataclass
class Decision:
    """Selection decision for a specific task containing candidates and rejections."""

    task: Union[Task, Dict[str, Any]]
    candidates: List[Candidate] = field(default_factory=list)
    rejected: List[Rejected] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert decision to a JSON-serializable dictionary."""
        if hasattr(self.task, "company"):
            task_plat = self.task.platform
            task_dict = {
                "company": self.task.company,
                "platform": task_plat.value if isinstance(task_plat, Platform) else str(task_plat),
            }
        elif isinstance(self.task, dict):
            task_dict = dict(self.task)
        else:
            task_dict = {"raw": str(self.task)}

        return {
            "task": task_dict,
            "candidates": [asdict(c) for c in self.candidates],
            "rejected": [asdict(r) for r in self.rejected],
            "summary": self.summary,
        }


def _lookup_connector(name: str, registry: Any) -> Optional[Any]:
    """Resolve a connector class or instance by name from registry."""
    if registry is None:
        try:
            from src.collection.registry import get_connector
            return get_connector(name)
        except Exception:
            return None

    if isinstance(registry, dict):
        return registry.get(name)

    if hasattr(registry, "get_connector"):
        return registry.get_connector(name)

    if isinstance(registry, (list, tuple)):
        for item in registry:
            if getattr(item, "name", None) == name or getattr(item, "__name__", None) == name:
                return item

    return None


def _get_connector_instance(conn_target: Any) -> Optional[Any]:
    """Obtain a callable/executable connector instance."""
    if conn_target is None:
        return None
    if isinstance(conn_target, type):
        try:
            return conn_target()
        except Exception:
            return None
    return conn_target


def decide(
    task: Union[Task, Dict[str, Any]],
    request: CollectionRequest,
    registry: Optional[Any] = None,
    budget: Optional[Union[BudgetTracker, float, int]] = None,
    policy: Optional[SourcePolicy] = None,
    prefer_paid: bool = False,
    history_only: bool = False,
    scraping_sites_cfg: Optional[Dict[str, Any]] = None,
) -> Decision:
    """Decide which collection methods to try and in what order for a given task."""
    pol = policy if policy is not None else load_source_policy()

    # Determine platform string
    if hasattr(task, "platform"):
        p_val = task.platform
        plat_str = p_val.value if isinstance(p_val, Platform) else str(p_val)
    elif isinstance(task, dict):
        p_val = task.get("platform", "other")
        plat_str = p_val.value if isinstance(p_val, Platform) else str(p_val)
    else:
        plat_str = "other"

    company_name = task.company if hasattr(task, "company") else (task.get("company", "") if isinstance(task, dict) else "")

    # Retrieve candidate list from policy
    raw_candidates = pol.get_candidates(plat_str)

    eligible_candidates: List[Tuple[Candidate, int, float, int]] = []
    rejected: List[Rejected] = []

    # Determine remaining budget
    remaining_budget: Optional[float] = None
    if isinstance(budget, BudgetTracker):
        remaining_budget = budget.snapshot()["remaining_usd"]
    elif isinstance(budget, (float, int)):
        remaining_budget = float(budget)
    elif request.budget_usd is not None:
        remaining_budget = float(request.budget_usd)

    for cand in raw_candidates:
        c_name = cand.connector

        # 0. Real platform tasks must never list dataset connector, except news_blog and history_baseline
        if plat_str in ("reddit", "google", "twitter_x", "instagram", "linkedin", "facebook") and (
            cand.method == "dataset" or "dataset" in c_name.lower()
        ):
            continue

        # Scraping special handling:
        if cand.method == "scraping" or c_name == "scraping":
            if not request.scraping_allowed:
                rejected.append(Rejected(c_name, "scraping not allowed for this run"))
                continue
            conn_target = _lookup_connector(c_name, registry)
            if not cand.available or conn_target is None:
                rejected.append(Rejected(c_name, "not implemented yet"))
                continue
            conn_inst = _get_connector_instance(conn_target)
            if conn_inst is None:
                rejected.append(Rejected(c_name, "not implemented yet"))
                continue
            # Check scraping_sites.yaml (primary) then fall back to policy (legacy/tests)
            if scraping_sites_cfg is not None:
                _site_ok = platform_has_scrapable_site(plat_str, scraping_sites_cfg)
            else:
                _sites = load_scraping_sites_cfg()
                _site_ok = platform_has_scrapable_site(plat_str, _sites) or bool(
                    pol.scraping.allows_scraping or plat_str in pol.scraping.allowed_sites
                )
            if not _site_ok:
                rejected.append(Rejected(c_name, "scraping not allowed for this run"))
                continue
        else:
            # 1. Unbuilt check
            if not cand.available:
                rejected.append(Rejected(c_name, f"Connector '{c_name}' is not built"))
                continue

            # 2. Registry lookup
            conn_target = _lookup_connector(c_name, registry)
            if conn_target is None:
                rejected.append(Rejected(c_name, f"Connector '{c_name}' is not built or not in registry"))
                continue

            conn_inst = _get_connector_instance(conn_target)
            if conn_inst is None:
                rejected.append(Rejected(c_name, f"Failed to instantiate connector '{c_name}'"))
                continue

        # 3. can_run check
        try:
            can_run, reason = conn_inst.can_run(request)
        except Exception as e:
            can_run, reason = False, f"Error in can_run: {e}"

        if not can_run:
            clean_reason = sanitize_secrets(reason)
            rejected.append(Rejected(c_name, clean_reason))
            continue

        # 4. Dataset-specific eligibility checks
        if cand.method == "dataset":
            if not request.dataset_keys:
                rejected.append(Rejected(c_name, "Dataset not selected in request.dataset_keys"))
                continue

            if request.require_fresh and request.max_age_days is not None and request.max_age_days > 0:
                catalogue = load_dataset_catalogue()
                is_stale = False
                stale_reason = ""
                now_utc = datetime.now(timezone.utc)
                for dkey in request.dataset_keys:
                    entry = catalogue.get(dkey)
                    if entry and entry.last_updated_override:
                        dt = to_utc(entry.last_updated_override)
                        if dt:
                            age_days = (now_utc - dt).total_seconds() / 86400.0
                            if age_days > request.max_age_days:
                                is_stale = True
                                stale_reason = f"Dataset '{dkey}' is older than {request.max_age_days} days (stale dataset)"
                                break
                if is_stale:
                    rejected.append(Rejected(c_name, stale_reason))
                    continue

        # 5. Budget check
        try:
            cost = float(conn_inst.estimate_cost(request))
        except Exception:
            cost = 0.0

        if remaining_budget is not None and cost > 0.0:
            if cost > remaining_budget:
                rejected.append(
                    Rejected(
                        c_name,
                        f"Estimated cost ${cost:.2f} exceeds remaining budget of ${remaining_budget:.2f}",
                    )
                )
                continue

        # Candidate is eligible! Build Candidate object & calculate ranking sort key
        is_scraping = (cand.method == "scraping")
        is_third_party = "third_party" in c_name.lower() or (cand.role == "backup" and cand.method == "api")

        if is_scraping:
            # Determine site_policy_allows status at plan time
            if scraping_sites_cfg is not None:
                _spa = platform_has_scrapable_site(plat_str, scraping_sites_cfg)
            else:
                _sites = load_scraping_sites_cfg()
                _spa = platform_has_scrapable_site(plat_str, _sites) or bool(
                    pol.scraping.allows_scraping or plat_str in pol.scraping.allowed_sites
                )
            c_obj = Candidate(
                connector=c_name,
                method=cand.method,
                cost_class=cand.cost_class,
                reason=cand.notes or "Fallback web scraping (conditional on primary failure)",
                estimated_cost=cost,
                conditional=True,
                conditions=["site_policy_allows", "other_methods_failed", "below_min_threshold"],
                conditions_status={
                    "site_policy_allows": _spa,
                    "other_methods_failed": None,   # not known at plan time
                    "below_min_threshold": None,     # not known at plan time
                },
                known_conditions={
                    "site_policy_allows": _spa,
                },
                role=cand.role,
            )
            tier = 99  # Scraping is ALWAYS last
            legal_risk = 3
        else:
            c_obj = Candidate(
                connector=c_name,
                method=cand.method,
                cost_class=cand.cost_class,
                reason=cand.notes or f"Eligible {cand.method} collection via {c_name}",
                estimated_cost=cost,
                conditional=False,
                conditions=None,
                role=cand.role,
            )
            legal_risk = 1
            if history_only or plat_str == "dataset":
                if cand.method == "dataset":
                    tier = 0
                elif cand.cost_class == "free" and not is_third_party:
                    tier = 2 if prefer_paid else 1
                elif cand.cost_class == "paid" and not is_third_party:
                    tier = 1 if prefer_paid else 2
                elif is_third_party:
                    tier = 4
                    legal_risk = 2
                else:
                    tier = 5
            else:
                if cand.method == "api" and not is_third_party:
                    if cand.cost_class == "free":
                        tier = 2 if prefer_paid else 1
                    elif cand.cost_class == "paid":
                        tier = 1 if prefer_paid else 2
                    else:
                        tier = 3
                elif cand.method == "dataset":
                    tier = 3
                elif is_third_party:
                    tier = 4
                    legal_risk = 2
                else:
                    tier = 5

        eligible_candidates.append((c_obj, tier, cost, legal_risk))

    # Sort candidates by: tier -> cost (cheaper first) -> legal_risk
    eligible_candidates.sort(key=lambda x: (x[1], x[2], x[3]))
    ranked_candidates = [item[0] for item in eligible_candidates]

    # Generate one readable sentence summary
    if ranked_candidates:
        first = ranked_candidates[0]
        cond_str = " (conditional)" if first.conditional else ""
        summary = (
            f"Selected '{first.connector}' ({first.cost_class} {first.method}{cond_str}) "
            f"as primary collection method for {company_name} on {plat_str}."
        )
    else:
        if rejected:
            reason_summaries = []
            seen_reasons = set()
            for r in rejected:
                if r.reason not in seen_reasons:
                    seen_reasons.add(r.reason)
                    reason_summaries.append(r.reason)
            summary = f"No eligible method for {company_name} on {plat_str}: {'; '.join(reason_summaries)}."
        else:
            summary = f"No eligible method for {company_name} on {plat_str}: no configured candidates."

    return Decision(
        task=task,
        candidates=ranked_candidates,
        rejected=rejected,
        summary=sanitize_secrets(summary),
    )


def plan_decisions(
    plan: Any,
    registry: Optional[Any] = None,
    budget: Optional[Union[BudgetTracker, float, int]] = None,
    policy: Optional[SourcePolicy] = None,
    prefer_paid: bool = False,
    history_only: bool = False,
    scraping_sites_cfg: Optional[Dict[str, Any]] = None,
) -> List[Decision]:
    """Evaluate decisions for all tasks in a collection plan in stable order."""
    decisions: List[Decision] = []
    requests_by_company = {
        req.company.lower(): req for req in getattr(plan, "requests", [])
    }

    for task in getattr(plan, "tasks", []):
        comp_name = task.company if hasattr(task, "company") else task.get("company", "")
        req = requests_by_company.get(comp_name.lower())
        if req is None:
            req = CollectionRequest(company=comp_name)

        decision = decide(
            task=task,
            request=req,
            registry=registry,
            budget=budget,
            policy=policy,
            prefer_paid=prefer_paid,
            history_only=history_only,
            scraping_sites_cfg=scraping_sites_cfg,
        )
        decisions.append(decision)

    return decisions


def main(argv: Optional[List[str]] = None) -> int:
    """CLI tool to explain collection decisions for an input plan."""
    parser = argparse.ArgumentParser(description="Collection Agent Decision Planner CLI")
    parser.add_argument(
        "--input",
        "-i",
        required=True,
        help="Path to JSON or YAML targets/plan file",
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        default=True,
        help="Print detailed explanations of candidate ranking and rejections",
    )
    args = parser.parse_args(argv)

    from src.collection.planner import plan as generate_plan

    plan_obj = generate_plan(args.input)
    decisions = plan_decisions(plan_obj)

    print("=== Collection Agent Decisions ===")
    print(f"Total Tasks Evaluated: {len(decisions)}\n")

    for idx, dec in enumerate(decisions, 1):
        if hasattr(dec.task, "company"):
            c_name = dec.task.company
            p_val = dec.task.platform
            plat = p_val.value if isinstance(p_val, Platform) else str(p_val)
        elif isinstance(dec.task, dict):
            c_name = dec.task.get("company", "")
            p_val = dec.task.get("platform", "")
            plat = p_val.value if isinstance(p_val, Platform) else str(p_val)
        else:
            c_name, plat = str(dec.task), ""

        print(f"[{idx}] Task: {c_name} -> {plat}")
        print(f"    Summary: {dec.summary}")

        if dec.candidates:
            print("    Ranked Candidates:")
            for rank, cand in enumerate(dec.candidates, 1):
                cond_tag = " [CONDITIONAL]" if cand.conditional else ""
                print(f"      {rank}. {cand.connector} ({cand.cost_class} {cand.method}){cond_tag}")
                print(f"         Reason: {cand.reason}")
                if cand.conditions:
                    print(f"         Conditions: {', '.join(cand.conditions)}")
        else:
            print("    Ranked Candidates: None")

        if dec.rejected:
            print("    Rejections:")
            for rej in dec.rejected:
                print(f"      * {rej.connector}: {rej.reason}")

        print()

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
