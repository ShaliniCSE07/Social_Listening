"""Collection Pipeline Executor module.

Executes collection decisions, handles fallback chains, conditional scraping gates,
budget tracking, and output generation.
"""
import argparse
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from config.settings import load_config
from src.collection.agent import (
    Candidate,
    Decision,
    _get_connector_instance,
    _lookup_connector,
    sanitize_secrets,
)
from src.collection.base import CollectionRequest
from src.collection.budget import BudgetTracker
from src.collection.policy import SourcePolicy, load_source_policy
from src.contracts.enums import AttemptStatus, Method, Platform
from src.contracts.io import write_attempts_jsonl, write_mentions_jsonl
from src.contracts.schemas import CollectionAttempt, RawMention


@dataclass
class TaskOutcome:
    """Outcome summary for a single collection task."""

    company: str
    platform: str
    chosen_method: Optional[str]
    fallback_path: List[str]
    total_items: int
    status: str  # "ok", "partial", "failed"


@dataclass
class ExecutionResult:
    """Complete collection execution result."""

    mentions: List[RawMention] = field(default_factory=list)
    attempts: List[CollectionAttempt] = field(default_factory=list)
    task_outcomes: List[TaskOutcome] = field(default_factory=list)
    budget_snapshot: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to a JSON-serializable dictionary."""
        return {
            "mentions_count": len(self.mentions),
            "attempts_count": len(self.attempts),
            "task_outcomes": [asdict(t) for t in self.task_outcomes],
            "budget_snapshot": self.budget_snapshot,
        }


def write_outputs(result: ExecutionResult, out_dir: Union[str, Path]) -> None:
    """Write execution outputs (mentions.jsonl, attempts.jsonl, run_summary.json)."""
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    write_mentions_jsonl(out_path / "mentions.jsonl", result.mentions)
    write_attempts_jsonl(out_path / "attempts.jsonl", result.attempts)

    summary_file = out_path / "run_summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, indent=2)


def execute(
    plan: Any,
    decisions: List[Decision],
    registry: Optional[Any] = None,
    budget: Optional[BudgetTracker] = None,
    config: Optional[Dict[str, Any]] = None,
    policy: Optional[SourcePolicy] = None,
) -> ExecutionResult:
    """Run collection decisions in order, handling fallback chains and scraping conditions."""
    cfg = config if config is not None else load_config()
    pol = policy if policy is not None else load_source_policy()

    # Shared budget tracker across entire execution
    if budget is not None:
        budget_tracker = budget
    else:
        limit = float(cfg.get("budget_usd", 10.0))
        budget_tracker = BudgetTracker(limit_usd=limit)

    # Minimum results threshold
    default_min_results = int(
        cfg.get("collection", {}).get("min_results", cfg.get("thresholds", {}).get("min_mentions", 5))
    )
    per_platform_min = cfg.get("collection", {}).get("platform_min_results", {})

    all_mentions: List[RawMention] = []
    all_attempts: List[CollectionAttempt] = []
    task_outcomes: List[TaskOutcome] = []

    requests_by_company = {
        req.company.lower(): req for req in getattr(plan, "requests", [])
    }

    for decision in decisions:
        task = decision.task
        comp_name = task.company if hasattr(task, "company") else task.get("company", "")
        plat_val = task.platform if hasattr(task, "platform") else task.get("platform", "other")
        plat_str = plat_val.value if isinstance(plat_val, Platform) else str(plat_val)
        plat_enum = plat_val if isinstance(plat_val, Platform) else (
            Platform(plat_str) if plat_str in Platform.__members__ else Platform.other
        )

        req = requests_by_company.get(comp_name.lower())
        if req is None:
            req = CollectionRequest(company=comp_name)

        min_results = int(per_platform_min.get(plat_str, default_min_results))
        is_dataset_task = (plat_str == "dataset" or getattr(task, "dataset_key", None) is not None)

        task_mentions: List[RawMention] = []
        task_attempts: List[CollectionAttempt] = []
        fallback_path: List[str] = []
        chosen_method: Optional[str] = None
        last_failed_method: Optional[Method] = None

        try:
            # -----------------------------------------------------------------
            # 1. Dataset Task: independent, never a fallback. Always run if selected
            # -----------------------------------------------------------------
            if is_dataset_task:
                if not decision.candidates:
                    # Dataset task had no candidates (e.g. unselected or stale)
                    now = datetime.now(timezone.utc)
                    att = CollectionAttempt(
                        company=comp_name,
                        platform=Platform.other,
                        method=Method.dataset,
                        status=AttemptStatus.skipped,
                        reason=sanitize_secrets(decision.summary),
                        item_count=0,
                        cost_usd=0.0,
                        started_at=now,
                        finished_at=now,
                    )
                    task_attempts.append(att)
                else:
                    cand = decision.candidates[0]
                    c_name = cand.connector
                    fallback_path.append(c_name)

                    conn_target = _lookup_connector(c_name, registry)
                    if conn_target is None:
                        now = datetime.now(timezone.utc)
                        att = CollectionAttempt(
                            company=comp_name,
                            platform=Platform.other,
                            method=Method.dataset,
                            status=AttemptStatus.failed,
                            reason=f"Dataset connector '{c_name}' not in registry",
                            item_count=0,
                            cost_usd=0.0,
                            started_at=now,
                            finished_at=now,
                        )
                        task_attempts.append(att)
                    else:
                        conn_inst = _get_connector_instance(conn_target)
                        # Dataset request targeting specific dataset_key if present on task
                        d_key = getattr(task, "dataset_key", None)
                        if d_key:
                            task_req = req.model_copy(update={"dataset_keys": [d_key]})
                        else:
                            task_req = req

                        now_start = datetime.now(timezone.utc)
                        try:
                            m_res, a_res = conn_inst.collect(task_req)
                            if isinstance(a_res, list):
                                task_attempts.extend(a_res)
                            else:
                                task_attempts.append(a_res)
                            task_mentions.extend(m_res)
                            chosen_method = c_name
                        except Exception as ds_err:
                            now_finish = datetime.now(timezone.utc)
                            safe_err = sanitize_secrets(str(ds_err).split("\n")[0])
                            att = CollectionAttempt(
                                company=comp_name,
                                platform=Platform.other,
                                method=Method.dataset,
                                status=AttemptStatus.failed,
                                reason=f"Dataset collection failed: {safe_err}",
                                item_count=0,
                                cost_usd=0.0,
                                started_at=now_start,
                                finished_at=now_finish,
                            )
                            task_attempts.append(att)

            # -----------------------------------------------------------------
            # 2. Platform Task: sequential fallback chain
            # -----------------------------------------------------------------
            else:
                if not decision.candidates:
                    # No candidates eligible
                    now = datetime.now(timezone.utc)
                    att = CollectionAttempt(
                        company=comp_name,
                        platform=plat_enum,
                        method=Method.api,
                        status=AttemptStatus.failed,
                        reason=sanitize_secrets(decision.summary),
                        item_count=0,
                        cost_usd=0.0,
                        started_at=now,
                        finished_at=now,
                    )
                    task_attempts.append(att)
                else:
                    for cand_idx, cand in enumerate(decision.candidates):
                        c_name = cand.connector
                        fallback_path.append(c_name)
                        cand_method = Method(cand.method) if cand.method in Method.__members__ else Method.api

                        # 2a. Conditional Scraping candidate evaluation
                        if cand.method == "scraping" or c_name == "scraping":
                            site_policy_allows = bool(
                                pol.scraping.allows_scraping or plat_str in pol.scraping.allowed_sites
                            )

                            other_methods_failed = True
                            for prev_att in task_attempts:
                                if prev_att.status not in (
                                    AttemptStatus.failed,
                                    AttemptStatus.rate_limited,
                                    AttemptStatus.empty,
                                ):
                                    other_methods_failed = False
                                    break

                            min_scraping_thresh = pol.scraping.min_results_threshold
                            below_min_threshold = (len(task_mentions) < min_scraping_thresh)

                            scraping_checks = {
                                "site_policy_allows": bool(site_policy_allows),
                                "other_methods_failed": bool(other_methods_failed),
                                "below_min_threshold": bool(below_min_threshold),
                            }

                            if not all(scraping_checks.values()):
                                now = datetime.now(timezone.utc)
                                failed_conds = [k for k, v in scraping_checks.items() if not v]
                                att = CollectionAttempt(
                                    company=comp_name,
                                    platform=plat_enum,
                                    method=Method.scraping,
                                    status=AttemptStatus.skipped,
                                    reason=f"Scraping conditions not met: {', '.join(failed_conds)}",
                                    item_count=0,
                                    cost_usd=0.0,
                                    started_at=now,
                                    finished_at=now,
                                    scraping_checks=scraping_checks,
                                )
                                task_attempts.append(att)
                                last_failed_method = Method.scraping
                                continue

                            # All 3 scraping conditions passed! Attempt execution
                            conn_target = _lookup_connector(c_name, registry)
                            now_sc = datetime.now(timezone.utc)
                            if conn_target is None:
                                att = CollectionAttempt(
                                    company=comp_name,
                                    platform=plat_enum,
                                    method=Method.scraping,
                                    status=AttemptStatus.failed,
                                    reason="scraping not implemented yet",
                                    item_count=0,
                                    cost_usd=0.0,
                                    started_at=now_sc,
                                    finished_at=now_sc,
                                    scraping_checks=scraping_checks,
                                )
                                task_attempts.append(att)
                                last_failed_method = Method.scraping
                                continue

                            conn_inst = _get_connector_instance(conn_target)
                            try:
                                m_res, a_res = conn_inst.collect(req)
                                if isinstance(a_res, list):
                                    for a in a_res:
                                        a.scraping_checks = scraping_checks
                                    task_attempts.extend(a_res)
                                else:
                                    a_res.scraping_checks = scraping_checks
                                    task_attempts.append(a_res)
                            except NotImplementedError:
                                att = CollectionAttempt(
                                    company=comp_name,
                                    platform=plat_enum,
                                    method=Method.scraping,
                                    status=AttemptStatus.failed,
                                    reason="scraping not implemented yet",
                                    item_count=0,
                                    cost_usd=0.0,
                                    started_at=now_sc,
                                    finished_at=now_sc,
                                    scraping_checks=scraping_checks,
                                )
                                task_attempts.append(att)
                                last_failed_method = Method.scraping
                                continue
                            except Exception as sc_err:
                                safe_err = sanitize_secrets(str(sc_err).split("\n")[0])
                                att = CollectionAttempt(
                                    company=comp_name,
                                    platform=plat_enum,
                                    method=Method.scraping,
                                    status=AttemptStatus.failed,
                                    reason=f"Scraping failed: {safe_err}",
                                    item_count=0,
                                    cost_usd=0.0,
                                    started_at=now_sc,
                                    finished_at=now_sc,
                                    scraping_checks=scraping_checks,
                                )
                                task_attempts.append(att)
                                last_failed_method = Method.scraping
                                continue

                            # If scraping returned mentions
                            new_m = []
                            for m in m_res:
                                if last_failed_method is not None:
                                    new_m.append(m.model_copy(update={"fallback_from": last_failed_method}))
                                else:
                                    new_m.append(m)
                            if new_m:
                                task_mentions.extend(new_m)
                                chosen_method = c_name
                            if len(task_mentions) >= min_results:
                                break
                            last_failed_method = Method.scraping
                            continue

                        # 2b. Standard candidate execution (API / dataset)
                        conn_target = _lookup_connector(c_name, registry)
                        if conn_target is None:
                            now = datetime.now(timezone.utc)
                            att = CollectionAttempt(
                                company=comp_name,
                                platform=plat_enum,
                                method=cand_method,
                                status=AttemptStatus.failed,
                                reason=f"Connector '{c_name}' not in registry",
                                item_count=0,
                                cost_usd=0.0,
                                started_at=now,
                                finished_at=now,
                            )
                            task_attempts.append(att)
                            last_failed_method = cand_method
                            continue

                        conn_inst = _get_connector_instance(conn_target)

                        # Budget Check
                        try:
                            cost_est = float(conn_inst.estimate_cost(req))
                        except Exception:
                            cost_est = 0.0

                        if cost_est > 0.0 and not budget_tracker.can_afford(plat_enum, cost_est):
                            now = datetime.now(timezone.utc)
                            att = CollectionAttempt(
                                company=comp_name,
                                platform=plat_enum,
                                method=cand_method,
                                status=AttemptStatus.budget_exhausted,
                                reason=f"Budget limit reached: cannot afford estimated cost ${cost_est:.2f}",
                                item_count=0,
                                cost_usd=0.0,
                                started_at=now,
                                finished_at=now,
                            )
                            task_attempts.append(att)
                            last_failed_method = cand_method

                            # Stop the chain unless a free candidate remains
                            has_free_remaining = any(
                                (rem.cost_class == "free" or getattr(rem, "estimated_cost", 0.0) == 0.0)
                                for rem in decision.candidates[cand_idx + 1 :]
                            )
                            if not has_free_remaining:
                                break
                            continue

                        # Budget Reservation
                        token = None
                        if cost_est > 0.0:
                            try:
                                token = budget_tracker.reserve(plat_enum, cost_est)
                            except Exception:
                                token = None

                        now_start = datetime.now(timezone.utc)
                        try:
                            m_res, a_res = conn_inst.collect(req)
                        except Exception as conn_err:
                            now_finish = datetime.now(timezone.utc)
                            safe_err = sanitize_secrets(str(conn_err).split("\n")[0])
                            att = CollectionAttempt(
                                company=comp_name,
                                platform=plat_enum,
                                method=cand_method,
                                status=AttemptStatus.failed,
                                reason=f"Connector error: {safe_err}",
                                item_count=0,
                                cost_usd=0.0,
                                started_at=now_start,
                                finished_at=now_finish,
                            )
                            task_attempts.append(att)
                            if token:
                                budget_tracker.release(token)
                            last_failed_method = cand_method
                            continue

                        if isinstance(a_res, list):
                            task_attempts.extend(a_res)
                            primary_att = a_res[0] if a_res else None
                        else:
                            task_attempts.append(a_res)
                            primary_att = a_res

                        actual_cost = primary_att.cost_usd if primary_att else 0.0
                        if token:
                            budget_tracker.commit(token, actual_cost)

                        # Tag mentions with fallback_from if this attempt succeeded another method
                        new_mentions = []
                        for m in m_res:
                            if last_failed_method is not None:
                                new_mentions.append(m.model_copy(update={"fallback_from": last_failed_method}))
                            else:
                                new_mentions.append(m)

                        if new_mentions:
                            task_mentions.extend(new_mentions)
                            chosen_method = c_name

                        total_so_far = len(task_mentions)
                        att_status = primary_att.status if primary_att else AttemptStatus.failed

                        # Stop chain if enough data collected
                        if total_so_far >= min_results:
                            break

                        # Otherwise fell short or failed: update last_failed_method and continue chain
                        if (
                            att_status in (AttemptStatus.failed, AttemptStatus.rate_limited, AttemptStatus.empty)
                            or total_so_far < min_results
                        ):
                            last_failed_method = cand_method

        except Exception as task_err:
            # Task-level isolation: an error here never halts subsequent tasks
            now = datetime.now(timezone.utc)
            safe_task_err = sanitize_secrets(str(task_err).split("\n")[0])
            att = CollectionAttempt(
                company=comp_name,
                platform=plat_enum,
                method=Method.api,
                status=AttemptStatus.failed,
                reason=f"Task error: {safe_task_err}",
                item_count=0,
                cost_usd=0.0,
                started_at=now,
                finished_at=now,
            )
            task_attempts.append(att)

        # Record results for this task
        total_items = len(task_mentions)
        if total_items >= min_results:
            status_str = "ok"
        elif total_items > 0:
            status_str = "partial"
        else:
            status_str = "failed"

        task_outcomes.append(
            TaskOutcome(
                company=comp_name,
                platform=plat_str,
                chosen_method=chosen_method,
                fallback_path=fallback_path,
                total_items=total_items,
                status=status_str,
            )
        )
        all_mentions.extend(task_mentions)
        all_attempts.extend(task_attempts)

    return ExecutionResult(
        mentions=all_mentions,
        attempts=all_attempts,
        task_outcomes=task_outcomes,
        budget_snapshot=budget_tracker.snapshot(),
    )


def main(argv: Optional[List[str]] = None) -> int:
    """CLI tool to execute collection plans, save outputs, and print summary tables."""
    parser = argparse.ArgumentParser(description="Collection Pipeline Executor CLI")
    parser.add_argument("--input", "-i", required=True, help="Path to input targets/plan file")
    parser.add_argument("--out", "-o", default="data/output", help="Directory to save output files")
    args = parser.parse_args(argv)

    from src.collection.agent import plan_decisions
    from src.collection.planner import plan as generate_plan

    plan_obj = generate_plan(args.input)
    decisions = plan_decisions(plan_obj)
    result = execute(plan_obj, decisions)

    write_outputs(result, args.out)

    print("\n=== Collection Execution Summary ===")
    header = f"{'Task':<28} {'Method':<12} {'Fallback Path':<28} {'Items':<7} {'Status':<8}"
    print(header)
    print("-" * len(header))
    for t in result.task_outcomes:
        task_str = f"{t.company} ({t.platform})"
        method_str = t.chosen_method or "None"
        fb_str = f"[{', '.join(t.fallback_path)}]" if t.fallback_path else "[]"
        print(f"{task_str:<28} {method_str:<12} {fb_str:<28} {t.total_items:<7} {t.status:<8}")

    print(f"\nTotal Mentions: {len(result.mentions)} | Total Attempts: {len(result.attempts)}")
    print(f"Outputs written to: {args.out}/ (mentions.jsonl, attempts.jsonl, run_summary.json)")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

