"""Tests for collection agent and policy decision engine."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import pytest
import yaml

from src.collection.agent import (
    Candidate,
    Decision,
    Rejected,
    decide,
    plan_decisions,
    sanitize_secrets,
)
from src.collection.base import BaseConnector, CollectionRequest
from src.collection.budget import BudgetTracker
from src.collection.planner import Plan, Task
from src.collection.plugins.dataset.catalogue import DatasetEntry
from src.collection.policy import (
    PolicyCandidate,
    ScrapingPolicy,
    SourcePolicy,
    load_source_policy,
)
from src.contracts.enums import Method, Platform


# --- Mocks for Registry and Connectors ---

class MockFreeConnector(BaseConnector):
    method = Method.api
    name = "mock_free_api"
    platforms = [Platform.reddit]

    def can_run(self, request: CollectionRequest):
        return True, "OK"

    def estimate_cost(self, request: CollectionRequest) -> float:
        return 0.0

    def collect(self, request: CollectionRequest):
        raise NotImplementedError()


class MockPaidConnector(BaseConnector):
    method = Method.api
    name = "mock_paid_api"
    platforms = [Platform.google]

    def can_run(self, request: CollectionRequest):
        return True, "OK"

    def estimate_cost(self, request: CollectionRequest) -> float:
        return 10.0

    def collect(self, request: CollectionRequest):
        raise NotImplementedError()


class MockFailingConnector(BaseConnector):
    method = Method.api
    name = "mock_failing_api"
    platforms = [Platform.reddit]

    def can_run(self, request: CollectionRequest):
        return False, "Reddit credentials missing"

    def estimate_cost(self, request: CollectionRequest) -> float:
        return 0.0

    def collect(self, request: CollectionRequest):
        raise NotImplementedError()


class MockDatasetConnector(BaseConnector):
    method = Method.dataset
    name = "mock_dataset"
    platforms = [Platform.other]

    def can_run(self, request: CollectionRequest):
        return True, "OK"

    def estimate_cost(self, request: CollectionRequest) -> float:
        return 0.0

    def collect(self, request: CollectionRequest):
        raise NotImplementedError()


class MockScrapingConnector(BaseConnector):
    method = Method.scraping
    name = "mock_scraping"
    platforms = [Platform.other]

    def can_run(self, request: CollectionRequest):
        return True, "OK"

    def estimate_cost(self, request: CollectionRequest) -> float:
        return 0.0

    def collect(self, request: CollectionRequest):
        raise NotImplementedError()


@pytest.fixture
def test_policy():
    """Policy fixture with mixed methods for testing ranking and gates."""
    return SourcePolicy(
        platforms={
            "reddit": [
                PolicyCandidate(connector="mock_free_api", method="api", cost_class="free", role="first_choice", available=True),
                PolicyCandidate(connector="mock_paid_api", method="api", cost_class="paid", role="backup", available=True),
                PolicyCandidate(connector="mock_scraping", method="scraping", cost_class="free", role="backup", available=True),
            ],
            "dataset_platform": [
                PolicyCandidate(connector="mock_free_api", method="api", cost_class="free", role="first_choice", available=True),
                PolicyCandidate(connector="mock_dataset", method="dataset", cost_class="free", role="backup", available=True),
            ],
        },
        scraping=ScrapingPolicy(allows_scraping=True, allowed_sites=["reddit", "instagram"], min_results_threshold=5),
    )


@pytest.fixture
def mock_registry():
    return {
        "mock_free_api": MockFreeConnector,
        "mock_paid_api": MockPaidConnector,
        "mock_failing_api": MockFailingConnector,
        "mock_dataset": MockDatasetConnector,
        "mock_scraping": MockScrapingConnector,
    }


def test_free_ranks_before_paid(test_policy, mock_registry):
    """Free official API candidates rank before paid ones by default."""
    task = Task("Acme", Platform.reddit)
    req = CollectionRequest(company="Acme", scraping_allowed=False)
    decision = decide(task, req, registry=mock_registry, policy=test_policy)

    assert len(decision.candidates) >= 2
    assert decision.candidates[0].connector == "mock_free_api"
    assert decision.candidates[1].connector == "mock_paid_api"


def test_paid_ranks_before_scraping(test_policy, mock_registry):
    """Paid official API ranks before scraping."""
    task = Task("Acme", Platform.reddit)
    req = CollectionRequest(company="Acme", scraping_allowed=True)
    decision = decide(task, req, registry=mock_registry, policy=test_policy)

    assert len(decision.candidates) == 3
    assert decision.candidates[1].connector == "mock_paid_api"
    assert decision.candidates[2].connector == "mock_scraping"


def test_scraping_always_last_and_conditional(test_policy, mock_registry):
    """Scraping candidate is always ranked last, marked conditional, and has expected conditions."""
    task = Task("Acme", Platform.reddit)
    req = CollectionRequest(company="Acme", scraping_allowed=True)
    decision = decide(task, req, registry=mock_registry, policy=test_policy)

    assert decision.candidates[-1].connector == "mock_scraping"
    scraping_cand = decision.candidates[-1]
    assert scraping_cand.conditional is True
    assert scraping_cand.conditions == ["site_policy_allows", "other_methods_failed", "below_min_threshold"]


def test_connector_can_run_false_rejected_with_own_reason(mock_registry):
    """When can_run is False, connector is rejected using its own reason text."""
    policy = SourcePolicy(
        platforms={
            "reddit": [
                PolicyCandidate(connector="mock_failing_api", method="api", cost_class="free", role="first_choice", available=True),
            ]
        }
    )
    task = Task("Acme", Platform.reddit)
    req = CollectionRequest(company="Acme")
    decision = decide(task, req, registry=mock_registry, policy=policy)

    assert len(decision.candidates) == 0
    assert len(decision.rejected) == 1
    assert decision.rejected[0].connector == "mock_failing_api"
    assert "Reddit credentials missing" in decision.rejected[0].reason


def test_budget_too_low_rejects_paid_keeps_free(test_policy, mock_registry):
    """Budget limit lower than estimated cost rejects the paid connector but keeps the free one."""
    task = Task("Acme", Platform.reddit)
    req = CollectionRequest(company="Acme", budget_usd=5.0)  # paid costs 10.0, free costs 0.0
    budget = BudgetTracker(limit_usd=5.0)
    decision = decide(task, req, registry=mock_registry, budget=budget, policy=test_policy)

    cand_names = [c.connector for c in decision.candidates]
    assert "mock_free_api" in cand_names
    assert "mock_paid_api" not in cand_names

    rej_names = [r.connector for r in decision.rejected]
    assert "mock_paid_api" in rej_names
    paid_rej = next(r for r in decision.rejected if r.connector == "mock_paid_api")
    assert "budget" in paid_rej.reason.lower()


def test_dataset_not_selected_rejected(mock_registry):
    """When no dataset is selected in request.dataset_keys, dataset candidate is rejected."""
    policy = SourcePolicy(
        platforms={
            "other": [
                PolicyCandidate(connector="mock_dataset", method="dataset", cost_class="free", role="first_choice", available=True),
            ]
        }
    )
    task = Task("Acme", Platform.other)
    req = CollectionRequest(company="Acme", dataset_keys=[])  # empty
    decision = decide(task, req, registry=mock_registry, policy=policy)

    assert len(decision.candidates) == 0
    assert len(decision.rejected) == 1
    assert "dataset not selected" in decision.rejected[0].reason.lower()


def test_stale_dataset_rejected_only_when_require_fresh(monkeypatch, mock_registry):
    """Stale dataset is rejected when require_fresh=True, but allowed when require_fresh=False."""
    policy = SourcePolicy(
        platforms={
            "other": [
                PolicyCandidate(connector="mock_dataset", method="dataset", cost_class="free", role="first_choice", available=True),
            ]
        }
    )
    # Mock dataset catalogue with an old date (2020)
    mock_cat = {
        "old_dataset": DatasetEntry(
            key="old_dataset",
            name="Old Dataset",
            source_type="local",
            path_or_ref="data.csv",
            format="csv",
            platform="other",
            content_type="review",
            last_updated_override="2020-01-01T00:00:00Z",
        )
    }
    monkeypatch.setattr("src.collection.agent.load_dataset_catalogue", lambda: mock_cat)

    task = Task("Acme", Platform.other)

    # Case 1: require_fresh=False -> not rejected for staleness
    req_not_fresh = CollectionRequest(company="Acme", dataset_keys=["old_dataset"], max_age_days=30, require_fresh=False)
    d1 = decide(task, req_not_fresh, registry=mock_registry, policy=policy)
    assert len(d1.candidates) == 1
    assert d1.candidates[0].connector == "mock_dataset"

    # Case 2: require_fresh=True -> rejected as stale
    req_fresh = CollectionRequest(company="Acme", dataset_keys=["old_dataset"], max_age_days=30, require_fresh=True)
    d2 = decide(task, req_fresh, registry=mock_registry, policy=policy)
    assert len(d2.candidates) == 0
    assert len(d2.rejected) == 1
    assert "older than 30" in d2.rejected[0].reason.lower() or "stale" in d2.rejected[0].reason.lower()


def test_history_only_request_puts_dataset_first(mock_registry):
    """When history_only is requested, dataset ranks before API connectors."""
    policy = SourcePolicy(
        platforms={
            "other": [
                PolicyCandidate(connector="mock_free_api", method="api", cost_class="free", role="first_choice", available=True),
                PolicyCandidate(connector="mock_dataset", method="dataset", cost_class="free", role="backup", available=True),
            ]
        }
    )
    task = Task("Acme", Platform.other)
    req = CollectionRequest(company="Acme", dataset_keys=["sample_key"])

    decision = decide(task, req, registry=mock_registry, policy=policy, history_only=True)
    assert len(decision.candidates) == 2
    assert decision.candidates[0].connector == "mock_dataset"
    assert decision.candidates[1].connector == "mock_free_api"


def test_no_eligible_method_gives_empty_list_and_explanation(mock_registry):
    """When all candidates are rejected, candidates list is empty and summary explains why."""
    policy = SourcePolicy(
        platforms={
            "reddit": [
                PolicyCandidate(connector="mock_failing_api", method="api", cost_class="free", role="first_choice", available=True),
            ]
        }
    )
    task = Task("Acme", Platform.reddit)
    req = CollectionRequest(company="Acme")
    decision = decide(task, req, registry=mock_registry, policy=policy)

    assert len(decision.candidates) == 0
    assert len(decision.rejected) == 1
    assert "No eligible method" in decision.summary
    assert "credentials missing" in decision.summary


def test_unbuilt_connectors_rejected_as_not_built():
    """Unbuilt connectors defined in source policy are rejected with 'not built' in the reason."""
    policy = load_source_policy()  # loads actual source_policy.yaml
    task_x = Task("Acme", Platform.twitter_x)
    req = CollectionRequest(company="Acme")
    decision = decide(task_x, req, policy=policy)

    assert len(decision.candidates) == 0
    assert len(decision.rejected) >= 1
    for r in decision.rejected:
        assert "not built" in r.reason.lower()


def test_scraping_rejected_when_scraping_allowed_false(mock_registry):
    """Scraping candidate is rejected when request.scraping_allowed is False."""
    policy = SourcePolicy(
        platforms={
            "reddit": [
                PolicyCandidate(connector="mock_scraping", method="scraping", cost_class="free", role="backup", available=True),
            ]
        },
        scraping=ScrapingPolicy(allows_scraping=True, allowed_sites=["reddit"]),
    )
    task = Task("Acme", Platform.reddit)
    req = CollectionRequest(company="Acme", scraping_allowed=False)
    decision = decide(task, req, registry=mock_registry, policy=policy)

    assert len(decision.candidates) == 0
    assert len(decision.rejected) == 1
    assert decision.rejected[0].reason == "scraping not allowed for this run"


def test_policy_file_with_unknown_method_gives_clear_error(tmp_path):
    """Source policy YAML containing an unknown method raises ValueError with a clear message."""
    bad_yaml = tmp_path / "bad_policy.yaml"
    content = {
        "platforms": {
            "reddit": [
                {
                    "connector": "some_conn",
                    "method": "magic_unknown_method",
                    "cost_class": "free",
                    "role": "first_choice",
                }
            ]
        }
    }
    with open(bad_yaml, "w", encoding="utf-8") as f:
        yaml.dump(content, f)

    with pytest.raises(ValueError) as excinfo:
        load_source_policy(bad_yaml)

    assert "Unknown method" in str(excinfo.value)
    assert "magic_unknown_method" in str(excinfo.value)


def test_decisions_serialize_to_json(test_policy, mock_registry):
    """Decisions must be completely JSON serializable via to_dict()."""
    task = Task("Acme", Platform.reddit)
    req = CollectionRequest(company="Acme", scraping_allowed=True)
    decision = decide(task, req, registry=mock_registry, policy=test_policy)

    d_dict = decision.to_dict()
    # Serialize to JSON string
    json_str = json.dumps(d_dict)
    assert isinstance(json_str, str)

    parsed = json.loads(json_str)
    assert parsed["task"]["company"] == "Acme"
    assert parsed["task"]["platform"] == "reddit"
    assert len(parsed["candidates"]) > 0
    assert "summary" in parsed


def test_no_credential_value_appears_in_decision(monkeypatch):
    """Secret credentials must never appear in any Decision field or summary."""
    secret_token = "SUPER_SECRET_TOKEN_99999"
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", secret_token)

    class SecretLeakingConnector(BaseConnector):
        method = Method.api
        name = "secret_leak"
        platforms = [Platform.reddit]

        def can_run(self, request: CollectionRequest):
            return False, f"Failed with client_secret={secret_token}"

        def estimate_cost(self, request: CollectionRequest) -> float:
            return 0.0

        def collect(self, request: CollectionRequest):
            raise NotImplementedError()

    policy = SourcePolicy(
        platforms={
            "reddit": [
                PolicyCandidate(connector="secret_leak", method="api", cost_class="free", role="first_choice", available=True),
            ]
        }
    )
    reg = {"secret_leak": SecretLeakingConnector}
    task = Task("Acme", Platform.reddit)
    req = CollectionRequest(company="Acme")

    decision = decide(task, req, registry=reg, policy=policy)
    d_json = json.dumps(decision.to_dict())

    assert secret_token not in d_json
    assert "[REDACTED]" in d_json
    assert secret_token not in decision.summary


def test_plan_decisions_stable_order(test_policy, mock_registry):
    """plan_decisions produces one decision per task in the planner's plan in stable order."""
    task1 = Task("CompanyA", Platform.reddit)
    task2 = Task("CompanyB", Platform.reddit)
    reqA = CollectionRequest(company="CompanyA")
    reqB = CollectionRequest(company="CompanyB")
    plan = Plan(requests=[reqA, reqB], tasks=[task1, task2])

    decisions = plan_decisions(plan, registry=mock_registry, policy=test_policy)
    assert len(decisions) == 2
    assert decisions[0].task.company == "CompanyA"
    assert decisions[1].task.company == "CompanyB"



def test_reddit_task_does_not_list_dataset(mock_registry):
    """Reddit task must never list dataset as a candidate even if dataset is in policy/selected."""
    policy = SourcePolicy(
        platforms={
            "reddit": [
                PolicyCandidate(connector="mock_free_api", method="api", cost_class="free", role="first_choice", available=True),
                PolicyCandidate(connector="mock_dataset", method="dataset", cost_class="free", role="backup", available=True),
            ]
        }
    )
    task = Task("Zomato", Platform.reddit)
    req = CollectionRequest(company="Zomato", dataset_keys=["sample_reviews_local"])

    decision = decide(task, req, registry=mock_registry, policy=policy)
    candidate_connectors = [c.connector for c in decision.candidates]
    assert "mock_dataset" not in candidate_connectors
    assert all(c.method != "dataset" for c in decision.candidates)


def test_scraping_rejection_reasons(mock_registry):
    """Verify specific scraping rejection messages: not allowed for this run vs not implemented yet."""
    # Case 1: scraping_allowed is False
    policy = SourcePolicy(
        platforms={
            "reddit": [
                PolicyCandidate(connector="mock_scraping", method="scraping", cost_class="free", role="backup", available=True),
            ]
        },
        scraping=ScrapingPolicy(allows_scraping=True, allowed_sites=["reddit"]),
    )
    task = Task("Acme", Platform.reddit)
    req1 = CollectionRequest(company="Acme", scraping_allowed=False)
    d1 = decide(task, req1, registry=mock_registry, policy=policy)
    assert len(d1.rejected) == 1
    assert d1.rejected[0].reason == "scraping not allowed for this run"

    # Case 2: scraping_allowed is True, but scraping connector is unbuilt / available=False
    unbuilt_policy = SourcePolicy(
        platforms={
            "reddit": [
                PolicyCandidate(connector="mock_scraping", method="scraping", cost_class="free", role="backup", available=False),
            ]
        },
        scraping=ScrapingPolicy(allows_scraping=True, allowed_sites=["reddit"]),
    )
    req2 = CollectionRequest(company="Acme", scraping_allowed=True)
    d2 = decide(task, req2, registry=mock_registry, policy=unbuilt_policy)
    assert len(d2.rejected) == 1
    assert d2.rejected[0].reason == "not implemented yet"
