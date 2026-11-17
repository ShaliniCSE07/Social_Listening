"""Tests for collection executor module (src/collection/executor.py)."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import pytest

from src.collection.agent import Candidate, Decision
from src.collection.base import BaseConnector, CollectionRequest
from src.collection.budget import BudgetTracker
from src.collection.executor import (
    ExecutionResult,
    TaskOutcome,
    execute,
    main,
    write_outputs,
)
from src.collection.planner import Plan, Task
from src.collection.policy import ScrapingPolicy, SourcePolicy
from src.contracts.enums import AttemptStatus, Method, Platform
from src.contracts.io import read_attempts_jsonl, read_mentions_jsonl
from src.contracts.schemas import CollectionAttempt, RawMention


def make_mention(
    company: str = "Acme",
    platform: Platform = Platform.reddit,
    method: Method = Method.api,
    item_id: str = "item_1",
    fallback_from: Optional[Method] = None,
    raw_payload: Optional[dict] = None,
) -> RawMention:
    now = datetime.now(timezone.utc)
    return RawMention(
        schema_version="1.0",
        company=company,
        platform=platform,
        item_id=item_id,
        raw_payload=raw_payload if raw_payload is not None else {"text": "sample mention", "id": item_id},
        source="mock_source",
        method_used=method,
        tool_used="Mock Tool",
        fallback_from=fallback_from,
        cost_usd=0.0,
        collected_at=now,
    )


def make_attempt(
    company: str = "Acme",
    platform: Platform = Platform.reddit,
    method: Method = Method.api,
    status: AttemptStatus = AttemptStatus.success,
    item_count: int = 5,
    cost_usd: float = 0.0,
    reason: Optional[str] = None,
) -> CollectionAttempt:
    now = datetime.now(timezone.utc)
    return CollectionAttempt(
        company=company,
        platform=platform,
        method=method,
        status=status,
        reason=reason or f"Mock {status.value}",
        item_count=item_count,
        cost_usd=cost_usd,
        started_at=now,
        finished_at=now,
    )


# --- Mock Connector Classes ---

class SuccessConnector(BaseConnector):
    method = Method.api
    name = "success_conn"
    platforms = [Platform.reddit]

    def can_run(self, request: CollectionRequest):
        return True, "OK"

    def estimate_cost(self, request: CollectionRequest) -> float:
        return 0.0

    def collect(self, request: CollectionRequest):
        mentions = [make_mention(company=request.company, item_id=f"m_{i}") for i in range(5)]
        att = make_attempt(company=request.company, status=AttemptStatus.success, item_count=5)
        return mentions, att


class FewMentionsConnector(BaseConnector):
    method = Method.api
    name = "few_conn"
    platforms = [Platform.reddit]

    def can_run(self, request: CollectionRequest):
        return True, "OK"

    def estimate_cost(self, request: CollectionRequest) -> float:
        return 0.0

    def collect(self, request: CollectionRequest):
        mentions = [make_mention(company=request.company, item_id=f"few_{i}") for i in range(2)]
        att = make_attempt(company=request.company, status=AttemptStatus.success, item_count=2)
        return mentions, att


class FailingConnector(BaseConnector):
    method = Method.api
    name = "failing_conn"
    platforms = [Platform.reddit]

    def can_run(self, request: CollectionRequest):
        return True, "OK"

    def estimate_cost(self, request: CollectionRequest) -> float:
        return 0.0

    def collect(self, request: CollectionRequest):
        att = make_attempt(company=request.company, status=AttemptStatus.failed, item_count=0, reason="API call failed")
        return [], att


class RateLimitedConnector(BaseConnector):
    method = Method.api
    name = "rate_limit_conn"
    platforms = [Platform.reddit]

    def can_run(self, request: CollectionRequest):
        return True, "OK"

    def estimate_cost(self, request: CollectionRequest) -> float:
        return 0.0

    def collect(self, request: CollectionRequest):
        att = make_attempt(company=request.company, status=AttemptStatus.rate_limited, item_count=0, reason="Rate limit 429")
        return [], att


class EmptyConnector(BaseConnector):
    method = Method.api
    name = "empty_conn"
    platforms = [Platform.reddit]

    def can_run(self, request: CollectionRequest):
        return True, "OK"

    def estimate_cost(self, request: CollectionRequest) -> float:
        return 0.0

    def collect(self, request: CollectionRequest):
        att = make_attempt(company=request.company, status=AttemptStatus.empty, item_count=0, reason="No results found")
        return [], att


class AuthFailingConnector(BaseConnector):
    method = Method.api
    name = "auth_fail_conn"
    platforms = [Platform.reddit]
    call_count = 0

    def can_run(self, request: CollectionRequest):
        return True, "OK"

    def estimate_cost(self, request: CollectionRequest) -> float:
        return 0.0

    def collect(self, request: CollectionRequest):
        AuthFailingConnector.call_count += 1
        att = make_attempt(company=request.company, status=AttemptStatus.failed, item_count=0, reason="401 Unauthorized: Invalid token")
        return [], att


class ExplodingConnector(BaseConnector):
    method = Method.api
    name = "exploding_conn"
    platforms = [Platform.reddit]

    def can_run(self, request: CollectionRequest):
        return True, "OK"

    def estimate_cost(self, request: CollectionRequest) -> float:
        return 0.0

    def collect(self, request: CollectionRequest):
        raise RuntimeError("Low-level fatal network socket crashed")


class PaidSuccessConnector(BaseConnector):
    method = Method.api
    name = "paid_conn"
    platforms = [Platform.google]

    def can_run(self, request: CollectionRequest):
        return True, "OK"

    def estimate_cost(self, request: CollectionRequest) -> float:
        return 10.0

    def collect(self, request: CollectionRequest):
        mentions = [make_mention(company=request.company, platform=Platform.google, item_id=f"paid_{i}") for i in range(5)]
        att = make_attempt(company=request.company, platform=Platform.google, status=AttemptStatus.success, item_count=5, cost_usd=10.0)
        return mentions, att


class FreeSuccessConnector(BaseConnector):
    method = Method.api
    name = "free_conn"
    platforms = [Platform.google]

    def can_run(self, request: CollectionRequest):
        return True, "OK"

    def estimate_cost(self, request: CollectionRequest) -> float:
        return 0.0

    def collect(self, request: CollectionRequest):
        mentions = [make_mention(company=request.company, platform=Platform.google, item_id=f"free_{i}") for i in range(5)]
        att = make_attempt(company=request.company, platform=Platform.google, status=AttemptStatus.success, item_count=5, cost_usd=0.0)
        return mentions, att


class MockDatasetConnector(BaseConnector):
    method = Method.dataset
    name = "dataset"
    platforms = [Platform.other]

    def can_run(self, request: CollectionRequest):
        return True, "OK"

    def estimate_cost(self, request: CollectionRequest) -> float:
        return 0.0

    def collect(self, request: CollectionRequest):
        mentions = [make_mention(company=request.company, platform=Platform.other, method=Method.dataset, item_id="ds_1")]
        att = make_attempt(company=request.company, platform=Platform.other, method=Method.dataset, status=AttemptStatus.success, item_count=1)
        return mentions, att


class MockScrapingUnimplementedConnector(BaseConnector):
    method = Method.scraping
    name = "scraping"
    platforms = [Platform.other]

    def can_run(self, request: CollectionRequest):
        return True, "OK"

    def estimate_cost(self, request: CollectionRequest) -> float:
        return 0.0

    def collect(self, request: CollectionRequest):
        raise NotImplementedError("Scraping plugin not implemented yet")


@pytest.fixture
def base_registry():
    return {
        "success_conn": SuccessConnector,
        "few_conn": FewMentionsConnector,
        "failing_conn": FailingConnector,
        "rate_limit_conn": RateLimitedConnector,
        "empty_conn": EmptyConnector,
        "auth_fail_conn": AuthFailingConnector,
        "exploding_conn": ExplodingConnector,
        "paid_conn": PaidSuccessConnector,
        "free_conn": FreeSuccessConnector,
        "dataset": MockDatasetConnector,
        "scraping": MockScrapingUnimplementedConnector,
    }


# -----------------------------------------------------------------------------
# Test Cases
# -----------------------------------------------------------------------------

def test_first_candidate_succeeds_no_fallback(base_registry):
    """When the first candidate yields >= min_results, the chain stops immediately."""
    task = Task("Acme", Platform.reddit)
    req = CollectionRequest(company="Acme")
    plan = Plan(requests=[req], tasks=[task])

    decision = Decision(
        task=task,
        candidates=[
            Candidate(connector="success_conn", method="api", cost_class="free", reason="Primary"),
            Candidate(connector="free_conn", method="api", cost_class="free", reason="Backup"),
        ],
    )

    res = execute(plan, [decision], registry=base_registry)
    assert len(res.mentions) == 5
    assert len(res.attempts) == 1
    assert res.task_outcomes[0].fallback_path == ["success_conn"]
    assert res.task_outcomes[0].status == "ok"
    assert res.task_outcomes[0].chosen_method == "success_conn"


def test_first_fails_and_second_succeeds_with_fallback_from_set(base_registry):
    """When candidate 1 fails, candidate 2 runs and its mentions have fallback_from set."""
    task = Task("Acme", Platform.reddit)
    req = CollectionRequest(company="Acme")
    plan = Plan(requests=[req], tasks=[task])

    decision = Decision(
        task=task,
        candidates=[
            Candidate(connector="failing_conn", method="api", cost_class="free", reason="Primary"),
            Candidate(connector="success_conn", method="api", cost_class="free", reason="Backup"),
        ],
    )

    res = execute(plan, [decision], registry=base_registry)
    assert len(res.attempts) == 2
    assert res.attempts[0].status == AttemptStatus.failed
    assert res.attempts[1].status == AttemptStatus.success
    assert len(res.mentions) == 5
    for m in res.mentions:
        assert m.fallback_from == Method.api


def test_rate_limited_moves_on(base_registry):
    """When a candidate is rate_limited, the fallback chain advances to the next candidate."""
    task = Task("Acme", Platform.reddit)
    req = CollectionRequest(company="Acme")
    plan = Plan(requests=[req], tasks=[task])

    decision = Decision(
        task=task,
        candidates=[
            Candidate(connector="rate_limit_conn", method="api", cost_class="free", reason="Primary"),
            Candidate(connector="success_conn", method="api", cost_class="free", reason="Backup"),
        ],
    )

    res = execute(plan, [decision], registry=base_registry)
    assert len(res.attempts) == 2
    assert res.attempts[0].status == AttemptStatus.rate_limited
    assert res.attempts[1].status == AttemptStatus.success
    assert len(res.mentions) == 5


def test_empty_moves_on(base_registry):
    """When an attempt returns empty (0 items), the chain moves to the next candidate."""
    task = Task("Acme", Platform.reddit)
    req = CollectionRequest(company="Acme")
    plan = Plan(requests=[req], tasks=[task])

    decision = Decision(
        task=task,
        candidates=[
            Candidate(connector="empty_conn", method="api", cost_class="free", reason="Primary"),
            Candidate(connector="success_conn", method="api", cost_class="free", reason="Backup"),
        ],
    )

    res = execute(plan, [decision], registry=base_registry)
    assert len(res.attempts) == 2
    assert res.attempts[0].status == AttemptStatus.empty
    assert res.attempts[1].status == AttemptStatus.success
    assert len(res.mentions) == 5


def test_auth_failure_is_not_retried(base_registry):
    """Authentication or permission failures must not be retried."""
    AuthFailingConnector.call_count = 0
    task = Task("Acme", Platform.reddit)
    req = CollectionRequest(company="Acme")
    plan = Plan(requests=[req], tasks=[task])

    decision = Decision(
        task=task,
        candidates=[
            Candidate(connector="auth_fail_conn", method="api", cost_class="free", reason="Primary"),
            Candidate(connector="success_conn", method="api", cost_class="free", reason="Backup"),
        ],
    )

    res = execute(plan, [decision], registry=base_registry)
    assert AuthFailingConnector.call_count == 1  # Called exactly once, no retries
    assert len(res.attempts) == 2
    assert res.attempts[0].status == AttemptStatus.failed
    assert res.attempts[1].status == AttemptStatus.success


def test_too_few_results_kept_and_next_method_adds_more(base_registry):
    """Mentions from a candidate that returned too few results are preserved, next method adds more."""
    task = Task("Acme", Platform.reddit)
    req = CollectionRequest(company="Acme")
    plan = Plan(requests=[req], tasks=[task])

    decision = Decision(
        task=task,
        candidates=[
            Candidate(connector="few_conn", method="api", cost_class="free", reason="Primary (2 items)"),
            Candidate(connector="success_conn", method="api", cost_class="free", reason="Backup (5 items)"),
        ],
    )

    res = execute(plan, [decision], registry=base_registry, config={"collection": {"min_results": 5}})
    # Total mentions: 2 from few_conn + 5 from success_conn = 7
    assert len(res.mentions) == 7
    # First 2 mentions had no fallback_from
    assert res.mentions[0].fallback_from is None
    assert res.mentions[1].fallback_from is None
    # Subsequent mentions from backup have fallback_from == Method.api
    for m in res.mentions[2:]:
        assert m.fallback_from == Method.api
    assert res.task_outcomes[0].status == "ok"


def test_all_candidates_fail_gives_failed_outcome_with_attempts(base_registry):
    """When all candidates fail, the task outcome is failed and attempts exist for each."""
    task = Task("Acme", Platform.reddit)
    req = CollectionRequest(company="Acme")
    plan = Plan(requests=[req], tasks=[task])

    decision = Decision(
        task=task,
        candidates=[
            Candidate(connector="failing_conn", method="api", cost_class="free", reason="Primary"),
            Candidate(connector="empty_conn", method="api", cost_class="free", reason="Backup"),
        ],
    )

    res = execute(plan, [decision], registry=base_registry)
    assert len(res.mentions) == 0
    assert len(res.attempts) == 2
    assert res.task_outcomes[0].status == "failed"
    assert res.task_outcomes[0].fallback_path == ["failing_conn", "empty_conn"]


def test_budget_exhausted_mid_run_stops_paid_runs_free(base_registry):
    """When budget is exhausted mid-run, paid candidates are skipped, free ones still execute."""
    budget = BudgetTracker(limit_usd=5.0)  # paid_conn costs 10.0, free_conn costs 0.0
    task = Task("Acme", Platform.google)
    req = CollectionRequest(company="Acme")
    plan = Plan(requests=[req], tasks=[task])

    decision = Decision(
        task=task,
        candidates=[
            Candidate(connector="paid_conn", method="api", cost_class="paid", reason="Paid"),
            Candidate(connector="free_conn", method="api", cost_class="free", reason="Free"),
        ],
    )

    res = execute(plan, [decision], registry=base_registry, budget=budget)
    assert len(res.attempts) == 2
    assert res.attempts[0].status == AttemptStatus.budget_exhausted
    assert res.attempts[1].status == AttemptStatus.success
    assert len(res.mentions) == 5


def test_scraping_skipped_with_scraping_checks_when_conditions_not_met(base_registry):
    """Scraping candidate is skipped with scraping_checks recorded when conditions are not satisfied."""
    policy = SourcePolicy(
        scraping=ScrapingPolicy(allows_scraping=False, allowed_sites=[])  # site_policy_allows is False
    )
    task = Task("Acme", Platform.reddit)
    req = CollectionRequest(company="Acme", scraping_allowed=True)
    plan = Plan(requests=[req], tasks=[task])

    decision = Decision(
        task=task,
        candidates=[
            Candidate(connector="scraping", method="scraping", cost_class="free", reason="Scrape"),
        ],
    )

    res = execute(plan, [decision], registry=base_registry, policy=policy)
    assert len(res.attempts) == 1
    att = res.attempts[0]
    assert att.status == AttemptStatus.skipped
    assert att.scraping_checks is not None
    assert att.scraping_checks["site_policy_allows"] is False


def test_scraping_runs_only_when_all_three_pass(base_registry):
    """When all three conditions pass, scraping executes and NotImplementedError becomes expected failed attempt."""
    policy = SourcePolicy(
        scraping=ScrapingPolicy(allows_scraping=True, allowed_sites=["reddit"], min_results_threshold=5)
    )
    task = Task("Acme", Platform.reddit)
    req = CollectionRequest(company="Acme", scraping_allowed=True)
    plan = Plan(requests=[req], tasks=[task])

    decision = Decision(
        task=task,
        candidates=[
            Candidate(connector="failing_conn", method="api", cost_class="free", reason="Primary failed"),
            Candidate(connector="scraping", method="scraping", cost_class="free", reason="Fallback scrape"),
        ],
    )

    res = execute(plan, [decision], registry=base_registry, policy=policy)
    assert len(res.attempts) == 2
    scrape_att = res.attempts[1]
    assert scrape_att.status == AttemptStatus.failed
    assert "scraping not implemented yet" in scrape_att.reason
    assert scrape_att.scraping_checks == {
        "site_policy_allows": True,
        "other_methods_failed": True,
        "below_min_threshold": True,
    }


def test_exception_in_connector_does_not_stop_other_tasks(base_registry):
    """A connector raising an unhandled exception becomes a failed attempt without halting other tasks."""
    task1 = Task("ExplodingCo", Platform.reddit)
    task2 = Task("HealthyCo", Platform.reddit)
    req1 = CollectionRequest(company="ExplodingCo")
    req2 = CollectionRequest(company="HealthyCo")
    plan = Plan(requests=[req1, req2], tasks=[task1, task2])

    dec1 = Decision(task=task1, candidates=[Candidate(connector="exploding_conn", method="api", cost_class="free", reason="Explodes")])
    dec2 = Decision(task=task2, candidates=[Candidate(connector="success_conn", method="api", cost_class="free", reason="Succeeds")])

    res = execute(plan, [dec1, dec2], registry=base_registry)
    assert len(res.task_outcomes) == 2
    assert res.task_outcomes[0].status == "failed"
    assert res.task_outcomes[1].status == "ok"
    assert len(res.mentions) == 5


def test_two_companies_where_one_fails(base_registry):
    """Isolation: Company A failing all methods does not prevent Company B from succeeding."""
    taskA = Task("CompA", Platform.reddit)
    taskB = Task("CompB", Platform.reddit)
    reqA = CollectionRequest(company="CompA")
    reqB = CollectionRequest(company="CompB")
    plan = Plan(requests=[reqA, reqB], tasks=[taskA, taskB])

    decA = Decision(task=taskA, candidates=[Candidate(connector="failing_conn", method="api", cost_class="free", reason="Fails")])
    decB = Decision(task=taskB, candidates=[Candidate(connector="success_conn", method="api", cost_class="free", reason="Succeeds")])

    res = execute(plan, [decA, decB], registry=base_registry)
    assert res.task_outcomes[0].company == "CompA"
    assert res.task_outcomes[0].status == "failed"
    assert res.task_outcomes[1].company == "CompB"
    assert res.task_outcomes[1].status == "ok"


def test_dataset_task_runs_even_when_platform_tasks_fail(base_registry):
    """Dataset tasks are independent and execute even if all platform tasks fail."""
    task_plat = Task("Acme", Platform.reddit)
    task_ds = Task("Acme", "dataset", dataset_key="sample_reviews_local")
    req = CollectionRequest(company="Acme", dataset_keys=["sample_reviews_local"])
    plan = Plan(requests=[req], tasks=[task_plat, task_ds])

    dec_plat = Decision(task=task_plat, candidates=[Candidate(connector="failing_conn", method="api", cost_class="free", reason="Fails")])
    dec_ds = Decision(task=task_ds, candidates=[Candidate(connector="dataset", method="dataset", cost_class="free", reason="Historical DS")])

    res = execute(plan, [dec_plat, dec_ds], registry=base_registry)
    assert res.task_outcomes[0].platform == "reddit"
    assert res.task_outcomes[0].status == "failed"
    assert res.task_outcomes[1].platform == "dataset"
    assert res.task_outcomes[1].status in ("ok", "partial")
    assert len(res.mentions) == 1
    assert res.mentions[0].method_used == Method.dataset


def test_raw_payload_never_altered(base_registry):
    """Setting fallback_from on mentions must never alter or mutate raw_payload."""
    initial_payload = {"key1": "value1", "nested": {"a": 123}}

    class CustomMentionConnector(BaseConnector):
        method = Method.api
        name = "custom_mention_conn"
        platforms = [Platform.reddit]

        def can_run(self, request: CollectionRequest):
            return True, "OK"

        def estimate_cost(self, request: CollectionRequest):
            return 0.0

        def collect(self, request: CollectionRequest):
            m = make_mention(company=request.company, raw_payload=dict(initial_payload))
            return [m], make_attempt(company=request.company, status=AttemptStatus.success, item_count=1)

    reg = {
        "failing_conn": FailingConnector,
        "custom_mention_conn": CustomMentionConnector,
    }
    task = Task("Acme", Platform.reddit)
    req = CollectionRequest(company="Acme")
    plan = Plan(requests=[req], tasks=[task])

    decision = Decision(
        task=task,
        candidates=[
            Candidate(connector="failing_conn", method="api", cost_class="free", reason="Fails"),
            Candidate(connector="custom_mention_conn", method="api", cost_class="free", reason="Succeeds with payload"),
        ],
    )

    res = execute(plan, [decision], registry=reg)
    assert len(res.mentions) == 1
    mention = res.mentions[0]
    assert mention.fallback_from == Method.api
    assert mention.raw_payload == initial_payload


def test_no_secret_appears_in_any_attempt_reason(monkeypatch, base_registry):
    """Secret tokens leaking in connector error messages must be sanitized in attempt reasons."""
    secret = "SUPER_SECRET_CLIENT_KEY_9999"
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", secret)

    class SecretLeakingErrorConnector(BaseConnector):
        method = Method.api
        name = "secret_error_conn"
        platforms = [Platform.reddit]

        def can_run(self, request: CollectionRequest):
            return True, "OK"

        def estimate_cost(self, request: CollectionRequest):
            return 0.0

        def collect(self, request: CollectionRequest):
            raise ValueError(f"Connection failed with token={secret}")

    reg = {"secret_error_conn": SecretLeakingErrorConnector}
    task = Task("Acme", Platform.reddit)
    req = CollectionRequest(company="Acme")
    plan = Plan(requests=[req], tasks=[task])

    decision = Decision(task=task, candidates=[Candidate(connector="secret_error_conn", method="api", cost_class="free", reason="Fails")])

    res = execute(plan, [decision], registry=reg)
    assert len(res.attempts) == 1
    reason = res.attempts[0].reason
    assert secret not in reason
    assert "[REDACTED]" in reason


def test_output_files_load_with_readers(tmp_path, base_registry):
    """ExecutionResult outputs can be read back with read_mentions_jsonl and read_attempts_jsonl."""
    task = Task("Acme", Platform.reddit)
    req = CollectionRequest(company="Acme")
    plan = Plan(requests=[req], tasks=[task])

    decision = Decision(task=task, candidates=[Candidate(connector="success_conn", method="api", cost_class="free", reason="Succeeds")])
    result = execute(plan, [decision], registry=base_registry)

    out_dir = tmp_path / "output_test"
    write_outputs(result, out_dir)

    mentions_file = out_dir / "mentions.jsonl"
    attempts_file = out_dir / "attempts.jsonl"
    summary_file = out_dir / "run_summary.json"

    assert mentions_file.is_file()
    assert attempts_file.is_file()
    assert summary_file.is_file()

    loaded_mentions = read_mentions_jsonl(mentions_file)
    assert "Acme" in loaded_mentions
    assert len(loaded_mentions["Acme"]) == 5

    loaded_attempts = read_attempts_jsonl(attempts_file)
    assert len(loaded_attempts) == 1
    assert loaded_attempts[0].status == AttemptStatus.success

    with open(summary_file, "r", encoding="utf-8") as f:
        summary_data = json.load(f)
    assert summary_data["mentions_count"] == 5
    assert summary_data["attempts_count"] == 1
