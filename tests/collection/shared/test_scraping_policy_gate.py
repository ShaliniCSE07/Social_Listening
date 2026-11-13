"""Tests for scraping policy gating, candidate ranking, and executor fallback conditions.

Covers the requirements for Stage 3 Scraping Gateway:
1. Scraping not allowed -> no scraping candidate.
2. Allowed with site enabled -> conditional candidate ranked last.
3. Skipped when dataset already returned enough items (below_min_threshold is False).
4. Skipped when site has allows_scraping False (site_policy_allows is False).
5. Runs when dataset returned nothing and site allows it.
6. scraping_checks holds all three keys in every case.
7. fallback_from is set on mentions when scraping follows a failed/empty method.
8. news_blog task with no dataset selected records 'no other method available'.
"""
from datetime import datetime, timezone
from typing import Dict, List, Tuple
import pytest

from src.collection.agent import Candidate, Decision, decide
from src.collection.base import BaseConnector, CollectionRequest
from src.collection.executor import execute
from src.collection.planner import Plan, Task
from src.collection.policy import (
    PolicyCandidate,
    ScrapingPolicy,
    SourcePolicy,
)
from src.contracts.enums import AttemptStatus, ContentType, Method, Platform
from src.contracts.schemas import CollectionAttempt, RawMention


# ---------------------------------------------------------------------------
# Helpers & Mock Connectors
# ---------------------------------------------------------------------------

def _make_mention(company: str, platform: Platform, method: Method, source: str = "mock") -> RawMention:
    now = datetime.now(timezone.utc)
    return RawMention(
        company=company,
        platform=platform,
        source=source,
        method_used=method,
        tool_used="mock_tool",
        raw_payload={"text": f"mention about {company}"},
        collected_at=now,
    )


class MockDatasetSuccessConnector(BaseConnector):
    method = Method.dataset
    name = "mock_dataset"
    platforms = [Platform.news_blog, Platform.other]

    def can_run(self, request: CollectionRequest) -> Tuple[bool, str]:
        return True, "OK"

    def estimate_cost(self, request: CollectionRequest) -> float:
        return 0.0

    def collect(self, request: CollectionRequest) -> Tuple[List[RawMention], List[CollectionAttempt]]:
        now = datetime.now(timezone.utc)
        mentions = [
            _make_mention(request.company, Platform.news_blog, Method.dataset, "mock_dataset")
            for _ in range(5)
        ]
        attempt = CollectionAttempt(
            company=request.company,
            platform=Platform.news_blog,
            method=Method.dataset,
            status=AttemptStatus.success,
            reason="OK",
            item_count=5,
            started_at=now,
            finished_at=now,
        )
        return mentions, [attempt]


class MockDatasetEmptyConnector(BaseConnector):
    method = Method.dataset
    name = "mock_dataset"
    platforms = [Platform.news_blog, Platform.other]

    def can_run(self, request: CollectionRequest) -> Tuple[bool, str]:
        return True, "OK"

    def estimate_cost(self, request: CollectionRequest) -> float:
        return 0.0

    def collect(self, request: CollectionRequest) -> Tuple[List[RawMention], List[CollectionAttempt]]:
        now = datetime.now(timezone.utc)
        attempt = CollectionAttempt(
            company=request.company,
            platform=Platform.news_blog,
            method=Method.dataset,
            status=AttemptStatus.empty,
            reason="No items in dataset",
            item_count=0,
            started_at=now,
            finished_at=now,
        )
        return [], [attempt]


class MockDatasetFailingConnector(BaseConnector):
    method = Method.dataset
    name = "mock_dataset"
    platforms = [Platform.news_blog, Platform.other]

    def can_run(self, request: CollectionRequest) -> Tuple[bool, str]:
        return True, "OK"

    def estimate_cost(self, request: CollectionRequest) -> float:
        return 0.0

    def collect(self, request: CollectionRequest) -> Tuple[List[RawMention], List[CollectionAttempt]]:
        now = datetime.now(timezone.utc)
        attempt = CollectionAttempt(
            company=request.company,
            platform=Platform.news_blog,
            method=Method.dataset,
            status=AttemptStatus.failed,
            reason="Dataset read error",
            item_count=0,
            started_at=now,
            finished_at=now,
        )
        return [], [attempt]


class MockScrapingSuccessConnector(BaseConnector):
    method = Method.scraping
    name = "scraping"
    platforms = [Platform.news_blog, Platform.other]

    def can_run(self, request: CollectionRequest) -> Tuple[bool, str]:
        return True, "OK"

    def estimate_cost(self, request: CollectionRequest) -> float:
        return 0.0

    def collect(self, request: CollectionRequest) -> Tuple[List[RawMention], List[CollectionAttempt]]:
        now = datetime.now(timezone.utc)
        mentions = [
            _make_mention(request.company, Platform.news_blog, Method.scraping, "hackernews")
        ]
        attempt = CollectionAttempt(
            company=request.company,
            platform=Platform.news_blog,
            method=Method.scraping,
            status=AttemptStatus.success,
            reason="OK",
            item_count=1,
            started_at=now,
            finished_at=now,
            pages_fetched=1,
            delay_used=5.0,
        )
        return mentions, [attempt]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def news_blog_policy():
    return SourcePolicy(
        platforms={
            "news_blog": [
                PolicyCandidate(connector="mock_dataset", method="dataset", cost_class="free", role="backup", available=True),
                PolicyCandidate(connector="scraping", method="scraping", cost_class="free", role="backup", available=True),
            ]
        },
        scraping=ScrapingPolicy(min_results_threshold=5),
    )


@pytest.fixture
def mock_sites_cfg_allowed():
    return {
        "hackernews": {
            "key": "hackernews",
            "name": "Hacker News",
            "platform": "news_blog",
            "allows_scraping": True,
        }
    }


@pytest.fixture
def mock_sites_cfg_disallowed():
    return {
        "hackernews": {
            "key": "hackernews",
            "name": "Hacker News",
            "platform": "news_blog",
            "allows_scraping": False,
        }
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_scraping_not_allowed_gives_no_scraping_candidate(news_blog_policy, mock_sites_cfg_allowed):
    """When request.scraping_allowed is False, scraping candidate is rejected with standard reason."""
    registry = {
        "mock_dataset": MockDatasetSuccessConnector,
        "scraping": MockScrapingSuccessConnector,
    }
    task = Task("Acme", Platform.news_blog)
    req = CollectionRequest(company="Acme", scraping_allowed=False, dataset_keys=["sample_key"])

    decision = decide(
        task,
        req,
        registry=registry,
        policy=news_blog_policy,
        scraping_sites_cfg=mock_sites_cfg_allowed,
    )

    candidate_connectors = [c.connector for c in decision.candidates]
    assert "scraping" not in candidate_connectors

    rejected_reasons = {r.connector: r.reason for r in decision.rejected}
    assert "scraping" in rejected_reasons
    assert rejected_reasons["scraping"] == "scraping not allowed for this run"


def test_scraping_allowed_with_site_enabled_gives_conditional_candidate_ranked_last(
    news_blog_policy, mock_sites_cfg_allowed
):
    """When scraping_allowed is True and site allows it, scraping is ranked last with conditional=True and 3 conditions."""
    registry = {
        "mock_dataset": MockDatasetSuccessConnector,
        "scraping": MockScrapingSuccessConnector,
    }
    task = Task("Acme", Platform.news_blog)
    req = CollectionRequest(company="Acme", scraping_allowed=True, dataset_keys=["sample_key"])

    decision = decide(
        task,
        req,
        registry=registry,
        policy=news_blog_policy,
        scraping_sites_cfg=mock_sites_cfg_allowed,
    )

    assert len(decision.candidates) == 2
    assert decision.candidates[0].connector == "mock_dataset"
    assert decision.candidates[1].connector == "scraping"

    scraping_cand = decision.candidates[1]
    assert scraping_cand.conditional is True
    assert scraping_cand.conditions == ["site_policy_allows", "other_methods_failed", "below_min_threshold"]
    assert scraping_cand.conditions_status["site_policy_allows"] is True
    assert scraping_cand.conditions_status["other_methods_failed"] is None
    assert scraping_cand.conditions_status["below_min_threshold"] is None
    assert scraping_cand.known_conditions == {"site_policy_allows": True}


def test_scraping_skipped_when_dataset_returns_enough_items(news_blog_policy, mock_sites_cfg_allowed):
    """When primary dataset returns enough items (>= min_results_threshold), scraping is skipped."""
    registry = {
        "mock_dataset": MockDatasetSuccessConnector,
        "scraping": MockScrapingSuccessConnector,
    }
    task = Task("Acme", Platform.news_blog)
    req = CollectionRequest(company="Acme", scraping_allowed=True)
    plan = Plan(requests=[req], tasks=[task])

    # Dataset succeeds with 5 items (which meets scraping threshold of 5, but overall target min_results is 10)
    decision = Decision(
        task=task,
        candidates=[
            Candidate(connector="mock_dataset", method="dataset", cost_class="free", reason="Primary"),
            Candidate(
                connector="scraping",
                method="scraping",
                cost_class="free",
                reason="Fallback scraping",
                conditional=True,
                conditions=["site_policy_allows", "other_methods_failed", "below_min_threshold"],
            ),
        ],
    )

    res = execute(
        plan,
        [decision],
        registry=registry,
        config={"min_results": 10},
        policy=news_blog_policy,
        scraping_sites_cfg=mock_sites_cfg_allowed,
    )

    assert len(res.attempts) == 2
    dataset_att = res.attempts[0]
    scrape_att = res.attempts[1]

    assert dataset_att.status == AttemptStatus.success
    assert scrape_att.status == AttemptStatus.skipped
    assert "below_min_threshold" in scrape_att.reason
    assert scrape_att.scraping_checks == {
        "site_policy_allows": True,
        "other_methods_failed": False,  # dataset succeeded
        "below_min_threshold": False,   # 5 items collected >= min_results_threshold 5
    }


def test_scraping_skipped_when_site_has_allows_scraping_false(news_blog_policy, mock_sites_cfg_disallowed):
    """When the site config has allows_scraping=False, scraping candidate is skipped by executor."""
    registry = {
        "mock_dataset": MockDatasetEmptyConnector,
        "scraping": MockScrapingSuccessConnector,
    }
    task = Task("Acme", Platform.news_blog)
    req = CollectionRequest(company="Acme", scraping_allowed=True)
    plan = Plan(requests=[req], tasks=[task])

    decision = Decision(
        task=task,
        candidates=[
            Candidate(connector="mock_dataset", method="dataset", cost_class="free", reason="Primary"),
            Candidate(
                connector="scraping",
                method="scraping",
                cost_class="free",
                reason="Fallback scraping",
                conditional=True,
                conditions=["site_policy_allows", "other_methods_failed", "below_min_threshold"],
            ),
        ],
    )

    res = execute(
        plan,
        [decision],
        registry=registry,
        policy=news_blog_policy,
        scraping_sites_cfg=mock_sites_cfg_disallowed,
    )

    assert len(res.attempts) == 2
    scrape_att = res.attempts[1]
    assert scrape_att.status == AttemptStatus.skipped
    assert scrape_att.scraping_checks["site_policy_allows"] is False
    assert scrape_att.scraping_checks["other_methods_failed"] is True
    assert scrape_att.scraping_checks["below_min_threshold"] is True


def test_scraping_runs_when_dataset_returned_nothing_and_site_allows_it(news_blog_policy, mock_sites_cfg_allowed):
    """When dataset returned empty and site allows scraping, all 3 conditions pass and scraping runs."""
    registry = {
        "mock_dataset": MockDatasetEmptyConnector,
        "scraping": MockScrapingSuccessConnector,
    }
    task = Task("Acme", Platform.news_blog)
    req = CollectionRequest(company="Acme", scraping_allowed=True)
    plan = Plan(requests=[req], tasks=[task])

    decision = Decision(
        task=task,
        candidates=[
            Candidate(connector="mock_dataset", method="dataset", cost_class="free", reason="Primary empty"),
            Candidate(
                connector="scraping",
                method="scraping",
                cost_class="free",
                reason="Fallback scraping",
                conditional=True,
                conditions=["site_policy_allows", "other_methods_failed", "below_min_threshold"],
            ),
        ],
    )

    res = execute(
        plan,
        [decision],
        registry=registry,
        policy=news_blog_policy,
        scraping_sites_cfg=mock_sites_cfg_allowed,
    )

    assert len(res.attempts) == 2
    assert res.attempts[0].status == AttemptStatus.empty
    scrape_att = res.attempts[1]
    assert scrape_att.status == AttemptStatus.success
    assert scrape_att.scraping_checks == {
        "site_policy_allows": True,
        "other_methods_failed": True,
        "below_min_threshold": True,
    }
    assert len(res.mentions) == 1
    assert res.mentions[0].fallback_from == Method.dataset


def test_scraping_checks_holds_all_three_keys_in_every_case(news_blog_policy, mock_sites_cfg_allowed):
    """scraping_checks must strictly contain site_policy_allows, other_methods_failed, and below_min_threshold."""
    registry = {
        "mock_dataset": MockDatasetFailingConnector,
        "scraping": MockScrapingSuccessConnector,
    }
    task = Task("Acme", Platform.news_blog)
    req = CollectionRequest(company="Acme", scraping_allowed=True)
    plan = Plan(requests=[req], tasks=[task])

    decision = Decision(
        task=task,
        candidates=[
            Candidate(connector="mock_dataset", method="dataset", cost_class="free", reason="Primary fails"),
            Candidate(
                connector="scraping",
                method="scraping",
                cost_class="free",
                reason="Fallback scraping",
                conditional=True,
                conditions=["site_policy_allows", "other_methods_failed", "below_min_threshold"],
            ),
        ],
    )

    res = execute(
        plan,
        [decision],
        registry=registry,
        policy=news_blog_policy,
        scraping_sites_cfg=mock_sites_cfg_allowed,
    )

    scrape_att = res.attempts[1]
    assert set(scrape_att.scraping_checks.keys()) == {
        "site_policy_allows",
        "other_methods_failed",
        "below_min_threshold",
    }


def test_fallback_from_is_set_on_mentions(news_blog_policy, mock_sites_cfg_allowed):
    """Mentions gathered by scraping fallback must have fallback_from set to the prior failed method."""
    registry = {
        "mock_dataset": MockDatasetFailingConnector,
        "scraping": MockScrapingSuccessConnector,
    }
    task = Task("Acme", Platform.news_blog)
    req = CollectionRequest(company="Acme", scraping_allowed=True)
    plan = Plan(requests=[req], tasks=[task])

    decision = Decision(
        task=task,
        candidates=[
            Candidate(connector="mock_dataset", method="dataset", cost_class="free", reason="Primary fails"),
            Candidate(connector="scraping", method="scraping", cost_class="free", reason="Fallback"),
        ],
    )

    res = execute(
        plan,
        [decision],
        registry=registry,
        policy=news_blog_policy,
        scraping_sites_cfg=mock_sites_cfg_allowed,
    )

    assert len(res.mentions) == 1
    assert res.mentions[0].fallback_from == Method.dataset


def test_news_blog_task_no_dataset_selected_records_no_other_method_available(
    news_blog_policy, mock_sites_cfg_allowed
):
    """When a news_blog task has no dataset selected in request, scraping runs with 'no other method available'."""
    registry = {
        "mock_dataset": MockDatasetSuccessConnector,
        "scraping": MockScrapingSuccessConnector,
    }
    task = Task("Acme", Platform.news_blog)
    # No dataset_keys provided in request!
    req = CollectionRequest(company="Acme", scraping_allowed=True, dataset_keys=[])

    decision = decide(
        task,
        req,
        registry=registry,
        policy=news_blog_policy,
        scraping_sites_cfg=mock_sites_cfg_allowed,
    )

    # Dataset candidate should be rejected because no dataset_keys were given
    assert len(decision.candidates) == 1
    assert decision.candidates[0].connector == "scraping"

    plan = Plan(requests=[req], tasks=[task])
    res = execute(
        plan,
        [decision],
        registry=registry,
        policy=news_blog_policy,
        scraping_sites_cfg=mock_sites_cfg_allowed,
    )

    assert len(res.attempts) == 1
    att = res.attempts[0]
    assert att.status == AttemptStatus.success
    assert att.scraping_checks["other_methods_failed"] is True
    assert "no other method available" in att.reason


def test_service_plan_endpoint_shows_conditional_scraping(monkeypatch):
    """POST /api/plan generator shows scraping candidate as conditional with three conditions and known status."""
    from src.service.models import CompanyInput, CreateRunRequest, SourcesInput
    from src.service.routes.runs import _generate_plan

    monkeypatch.setenv("SCRAPER_CONTACT", "test@example.com")

    # 1. When scraping_allowed is False (default) -> no scraping candidate
    req_no_scrape = CreateRunRequest(
        companies=[CompanyInput(name="Acme")],
        sources=SourcesInput(api=["news_blog"]),
        scraping_allowed=False,
    )
    res_no = _generate_plan(req_no_scrape)
    assert len(res_no.decisions) >= 1
    cands_no = [c["connector"] for c in res_no.decisions[0]["candidates"]]
    assert "scraping" not in cands_no

    # 2. When scraping_allowed is True -> scraping candidate is conditional with 3 conditions and known status
    req_scrape = CreateRunRequest(
        companies=[CompanyInput(name="Acme")],
        sources=SourcesInput(api=["news_blog"]),
        scraping_allowed=True,
    )
    res_yes = _generate_plan(req_scrape)
    assert len(res_yes.decisions) >= 1
    scrape_cands = [c for c in res_yes.decisions[0]["candidates"] if c["connector"] == "scraping"]
    assert len(scrape_cands) == 1
    scrape_c = scrape_cands[0]
    assert scrape_c["conditional"] is True
    assert scrape_c["conditions"] == ["site_policy_allows", "other_methods_failed", "below_min_threshold"]
    assert scrape_c["conditions_status"]["site_policy_allows"] is True
    assert scrape_c["conditions_status"]["other_methods_failed"] is None
    assert scrape_c["conditions_status"]["below_min_threshold"] is None
    assert scrape_c["known_conditions"] == {"site_policy_allows": True}

