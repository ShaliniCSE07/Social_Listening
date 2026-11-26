"""Tests for the TripAdvisor reviews connector (RapidAPI "Tripadvisor Reviews Scraper")."""
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest
import responses

from src.collection.base import CollectionRequest
from src.collection.cache import ResultCache
from src.collection.plugins.api.tripadvisor_reviews import TripadvisorReviewsConnector
from src.collection.registry import get_connector
from src.contracts.enums import AttemptStatus, ContentType, Method, Platform

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"
API_URL = "https://tripadvisor-reviews-scraper1.p.rapidapi.com/"
FAKE_KEY = "fake-rapidapi-key-0123456789abcdef"

PAGE_A = "https://www.tripadvisor.com/Hotel_Review-g60763-d93437-Reviews-Hotel_Edison_Times_Square-New_York_City_New_York.html"
PAGE_B = "https://www.tripadvisor.com/Restaurant_Review-g304554-d20328639-Reviews-Delhi_Highway-Mumbai_Maharashtra.html"

COMPANIES = {
    "Hotel Edison": {"api": {"tripadvisor_urls": [PAGE_A]}},
    "Zomato": {"api": {"places_query": "Zomato office"}},
}


@pytest.fixture
def reviews_fixture() -> list:
    with open(FIXTURES_DIR / "tripadvisor_reviews_sample.json", "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def rapidapi_env(monkeypatch):
    monkeypatch.setenv("RAPIDAPI_KEY", FAKE_KEY)


def make_connector(tmp_path, companies=None, **overrides) -> TripadvisorReviewsConnector:
    conn = TripadvisorReviewsConnector(
        cache=ResultCache(cache_dir=tmp_path / "cache"),
        companies=companies if companies is not None else COMPANIES,
    )
    for key, value in overrides.items():
        setattr(conn, key, value)
    return conn


def request_for(company="Hotel Edison", **kwargs) -> CollectionRequest:
    kwargs.setdefault("platforms", [Platform.tripadvisor])
    return CollectionRequest(company=company, **kwargs)


# ---- can_run ---------------------------------------------------------------


def test_missing_key_gives_can_run_false(monkeypatch, tmp_path):
    monkeypatch.delenv("RAPIDAPI_KEY", raising=False)
    ok, reason = make_connector(tmp_path).can_run(request_for())
    assert ok is False
    assert "RAPIDAPI_KEY missing" in reason


def test_other_platform_requested_gives_can_run_false(rapidapi_env, tmp_path):
    ok, reason = make_connector(tmp_path).can_run(request_for(platforms=[Platform.reddit]))
    assert ok is False
    assert "TripAdvisor platform not requested" in reason


def test_listed_company_without_urls_is_rejected(rapidapi_env, tmp_path):
    ok, reason = make_connector(tmp_path).can_run(request_for("Zomato"))
    assert ok is False
    assert "No TripAdvisor URLs configured for 'Zomato'" in reason


def test_unlisted_company_passes_probe_when_some_company_has_urls(rapidapi_env, tmp_path):
    # The sources page probes every connector with a placeholder company.
    ok, _ = make_connector(tmp_path).can_run(CollectionRequest(company="ProbeCompany"))
    assert ok is True


def test_no_urls_anywhere_gives_can_run_false(rapidapi_env, tmp_path):
    conn = make_connector(tmp_path, companies={"Zomato": {"api": {}}})
    ok, reason = conn.can_run(CollectionRequest(company="ProbeCompany"))
    assert ok is False
    assert "companies.yaml" in reason


def test_unlisted_company_collect_reports_missing_urls(rapidapi_env, tmp_path):
    mentions, attempt = make_connector(tmp_path).collect(request_for("Some New Cafe"))
    assert mentions == []
    assert attempt.status == AttemptStatus.failed
    assert "No TripAdvisor URLs configured for 'Some New Cafe'" in attempt.reason


# ---- collect ---------------------------------------------------------------


@responses.activate
def test_success_maps_reviews_and_keeps_raw_payload(rapidapi_env, tmp_path, reviews_fixture):
    responses.add(
        responses.POST, API_URL, json=reviews_fixture, status=200,
        headers={"x-ratelimit-requests-remaining": "9"},
    )

    mentions, attempt = make_connector(tmp_path).collect(request_for(run_id="run-1"))

    # Request: one call, right headers and body
    assert len(responses.calls) == 1
    sent = responses.calls[0].request
    assert sent.headers["x-rapidapi-key"] == FAKE_KEY
    assert sent.headers["x-rapidapi-host"] == "tripadvisor-reviews-scraper1.p.rapidapi.com"
    assert json.loads(sent.body) == {"places": [PAGE_A], "maxReviewsPerPlace": 20}

    # Attempt
    assert attempt.status == AttemptStatus.success
    assert attempt.platform == Platform.tripadvisor
    assert attempt.method == Method.api
    assert attempt.item_count == 3
    assert attempt.pages_fetched == 1
    assert "Collected 3 TripAdvisor reviews" in attempt.reason

    # Mentions
    assert len(mentions) == 3
    first = mentions[0]
    assert first.company == "Hotel Edison"
    assert first.run_id == "run-1"
    assert first.platform == Platform.tripadvisor
    assert first.item_id == "1085940974"
    assert first.url.endswith("r1085940974-Hotel_Edison_Times_Square-New_York_City_New_York.html")
    assert first.branch == "Hotel Edison Times Square"
    assert first.content_type_hint == ContentType.review
    assert first.source == "tripadvisor.com"
    assert first.method_used == Method.api
    assert first.tool_used == "RapidAPI: Tripadvisor Reviews Scraper"
    assert first.collected_at.tzinfo is not None

    # Raw payload keeps the provider's fields and adds the page match marker
    payload = mentions[1].raw_payload
    assert payload["text"].startswith("This trip was for my mother's")
    assert payload["rating"] == 5
    assert payload["subRatings"]["Service"] == 5
    assert payload["ownerResponse"]["role"] == "Guest Services / Front Office"
    assert payload["source_match_basis"] == "place_page"


@responses.activate
def test_date_from_is_sent_and_dates_are_filtered(rapidapi_env, tmp_path, reviews_fixture):
    responses.add(responses.POST, API_URL, json=reviews_fixture, status=200)

    req = request_for(
        date_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        date_to=datetime(2026, 11, 18, tzinfo=timezone.utc),
    )
    mentions, attempt = make_connector(tmp_path).collect(req)

    assert json.loads(responses.calls[0].request.body)["reviewsSince"] == "2026-01-01"
    # 2025-03-24 is before date_from; 2026-11-18T17:53 is after date_to
    assert [m.item_id for m in mentions] == ["1085819742"]
    assert attempt.status == AttemptStatus.success


@responses.activate
def test_quota_exhausted_429_is_rate_limited(rapidapi_env, tmp_path):
    responses.add(responses.POST, API_URL, json={"message": "You have exceeded the quota"}, status=429)

    mentions, attempt = make_connector(tmp_path).collect(request_for())

    assert mentions == []
    assert attempt.status == AttemptStatus.rate_limited
    assert "429" in attempt.reason


@responses.activate
def test_not_subscribed_403_fails_without_leaking_key(rapidapi_env, tmp_path):
    responses.add(
        responses.POST, API_URL,
        json={"message": f"You are not subscribed to this API. key={FAKE_KEY}"}, status=403,
    )

    mentions, attempt = make_connector(tmp_path).collect(request_for())

    assert mentions == []
    assert attempt.status == AttemptStatus.failed
    assert "not subscribed" in attempt.reason
    assert FAKE_KEY not in attempt.reason


@responses.activate
def test_empty_array_is_empty_status(rapidapi_env, tmp_path):
    responses.add(responses.POST, API_URL, json=[], status=200)

    mentions, attempt = make_connector(tmp_path).collect(request_for())

    assert mentions == []
    assert attempt.status == AttemptStatus.empty


@responses.activate
def test_max_places_per_run_limits_requests(rapidapi_env, tmp_path, reviews_fixture):
    responses.add(responses.POST, API_URL, json=reviews_fixture, status=200)
    companies = {"Hotel Edison": {"api": {"tripadvisor_urls": [PAGE_A, PAGE_B]}}}

    conn = make_connector(tmp_path, companies=companies, max_places_per_run=1)
    _, attempt = conn.collect(request_for())

    assert len(responses.calls) == 1
    assert "1 more URL(s) skipped by max_places_per_run" in attempt.reason


@responses.activate
def test_low_quota_stops_before_next_page(rapidapi_env, tmp_path, reviews_fixture):
    responses.add(
        responses.POST, API_URL, json=reviews_fixture, status=200,
        headers={"x-ratelimit-requests-remaining": "0"},
    )
    companies = {"Hotel Edison": {"api": {"tripadvisor_urls": [PAGE_A, PAGE_B]}}}

    mentions, attempt = make_connector(tmp_path, companies=companies).collect(request_for())

    assert len(responses.calls) == 1
    assert len(mentions) == 3
    assert attempt.status == AttemptStatus.success
    assert "RapidAPI quota left: 0" in attempt.reason


@responses.activate
def test_second_run_uses_cache_and_spends_no_request(rapidapi_env, tmp_path, reviews_fixture):
    responses.add(responses.POST, API_URL, json=reviews_fixture, status=200)
    conn = make_connector(tmp_path)

    conn.collect(request_for())
    mentions, attempt = conn.collect(request_for())

    assert len(responses.calls) == 1
    assert len(mentions) == 3
    assert attempt.pages_fetched == 0
    assert attempt.pages_from_cache == 1


@responses.activate
def test_refresh_skips_cache(rapidapi_env, tmp_path, reviews_fixture):
    responses.add(responses.POST, API_URL, json=reviews_fixture, status=200)
    conn = make_connector(tmp_path)

    conn.collect(request_for())
    conn.collect(request_for(refresh=True))

    assert len(responses.calls) == 2


@responses.activate
def test_cost_is_spread_over_reviews(rapidapi_env, tmp_path, reviews_fixture):
    responses.add(responses.POST, API_URL, json=reviews_fixture, status=200)

    conn = make_connector(tmp_path, cost_per_request=0.03)
    mentions, attempt = conn.collect(request_for(budget_usd=1.0))

    assert attempt.cost_usd == pytest.approx(0.03)
    assert sum(m.cost_usd for m in mentions) == pytest.approx(0.03)


def test_budget_too_small_stops_before_request(rapidapi_env, tmp_path):
    conn = make_connector(tmp_path, cost_per_request=0.5)
    mentions, attempt = conn.collect(request_for(budget_usd=0.1))

    assert mentions == []
    assert attempt.status == AttemptStatus.budget_exhausted


# ---- wiring ----------------------------------------------------------------


def test_connector_is_discovered_by_registry():
    assert get_connector("third_party_tripadvisor") is TripadvisorReviewsConnector


def test_source_policy_lists_tripadvisor_candidate():
    from src.collection.policy import load_source_policy

    candidates = load_source_policy().get_candidates("tripadvisor")
    assert [c.connector for c in candidates] == ["third_party_tripadvisor"]
    assert candidates[0].available is True
