"""Tests for Google Places API connector."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import pytest
import requests
import responses

from src.collection.base import CollectionRequest
from src.collection.budget import BudgetTracker
from src.collection.cache import ResultCache
from src.collection.plugins.api.google_places import GooglePlacesConnector
from src.contracts.enums import AttemptStatus, ContentType, Method, Platform

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"


@pytest.fixture
def places_search_fixture() -> dict:
    with open(FIXTURES_DIR / "places_search_sample.json", "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def places_details_fixture() -> dict:
    with open(FIXTURES_DIR / "places_details_sample.json", "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def mock_google_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "AIzaSyFakeGooglePlacesKey12345")


def test_missing_key_gives_can_run_false(monkeypatch):
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    connector = GooglePlacesConnector()
    can_run, reason = connector.can_run(CollectionRequest(company="Tata Motors"))
    assert can_run is False
    assert "Google Places key missing" in reason


def test_key_never_appears_in_logs_or_reasons(mock_google_env):
    key = "AIzaSyFakeGooglePlacesKey12345"
    connector = GooglePlacesConnector()
    request = CollectionRequest(company="Tata Motors", platforms=[Platform.reddit])
    _, attempt = connector.collect(request)

    assert key not in (attempt.reason or "")
    assert attempt.status == AttemptStatus.failed


@responses.activate
def test_places_success_maps_fields_and_keeps_raw_payload(
    mock_google_env, places_search_fixture, places_details_fixture
):
    responses.add(
        responses.POST,
        "https://places.googleapis.com/v1/places:searchText",
        json=places_search_fixture,
        status=200,
    )
    responses.add(
        responses.GET,
        "https://places.googleapis.com/v1/places/ChIJN1t_tDeuEmsRUsoyG83frY4",
        json=places_details_fixture,
        status=200,
    )

    connector = GooglePlacesConnector()
    request = CollectionRequest(
        company="Tata Motors",
        branches=["Gurugram HQ"],
        platforms=[Platform.google],
    )

    mentions, attempt = connector.collect(request)

    assert attempt.status == AttemptStatus.success
    assert attempt.item_count == 2
    assert len(mentions) == 2
    assert attempt.cost_usd > 0.0

    first = mentions[0]
    assert first.platform == Platform.google
    assert first.content_type_hint == ContentType.review
    assert first.branch == "Tata Motors Dealership"
    assert first.item_id == "places/ChIJN1t_tDeuEmsRUsoyG83frY4/reviews/rev1"
    assert first.source == "google.com/maps"
    assert first.tool_used == "Google Places API"
    assert first.cost_usd > 0.0

    # raw_payload has original review dict + place_id and place_name
    assert first.raw_payload["place_id"] == "ChIJN1t_tDeuEmsRUsoyG83frY4"
    assert first.raw_payload["place_name"] == "Tata Motors Dealership"
    assert first.raw_payload["rating"] == 5


@responses.activate
def test_places_multiple_branches(
    mock_google_env, places_search_fixture, places_details_fixture
):
    # Branch 1
    responses.add(
        responses.POST,
        "https://places.googleapis.com/v1/places:searchText",
        json=places_search_fixture,
        status=200,
    )
    responses.add(
        responses.GET,
        "https://places.googleapis.com/v1/places/ChIJN1t_tDeuEmsRUsoyG83frY4",
        json=places_details_fixture,
        status=200,
    )
    # Branch 2
    branch2_search = {"places": [{"id": "place_branch_2", "displayName": {"text": "Branch 2"}}]}
    branch2_details = {
        "id": "place_branch_2",
        "displayName": {"text": "Branch 2"},
        "reviews": [{"name": "rev_b2_1", "rating": 4, "text": {"text": "Branch 2 review"}}],
    }
    responses.add(
        responses.POST,
        "https://places.googleapis.com/v1/places:searchText",
        json=branch2_search,
        status=200,
    )
    responses.add(
        responses.GET,
        "https://places.googleapis.com/v1/places/place_branch_2",
        json=branch2_details,
        status=200,
    )

    connector = GooglePlacesConnector()
    request = CollectionRequest(
        company="Tata Motors",
        branches=["Gurugram", "Bangalore"],
        platforms=[Platform.google],
    )

    mentions, attempt = connector.collect(request)

    assert len(mentions) == 3
    assert attempt.status == AttemptStatus.success
    assert attempt.item_count == 3


@responses.activate
def test_places_no_place_found(mock_google_env):
    responses.add(
        responses.POST,
        "https://places.googleapis.com/v1/places:searchText",
        json={"places": []},
        status=200,
    )

    connector = GooglePlacesConnector()
    request = CollectionRequest(company="NonExistentPlaceXYZ", platforms=[Platform.google])
    mentions, attempt = connector.collect(request)

    assert len(mentions) == 0
    assert attempt.status == AttemptStatus.empty
    assert "no matching places" in attempt.reason.lower()


@responses.activate
def test_places_5_review_cap_noted(mock_google_env, places_search_fixture):
    # Construct 5 reviews in details response
    five_reviews = [
        {"name": f"places/p1/reviews/rev{i}", "rating": 5, "text": {"text": f"Review {i}"}}
        for i in range(1, 6)
    ]
    details_with_5 = {
        "id": "ChIJN1t_tDeuEmsRUsoyG83frY4",
        "displayName": {"text": "Tata Motors"},
        "reviews": five_reviews,
    }

    responses.add(
        responses.POST,
        "https://places.googleapis.com/v1/places:searchText",
        json=places_search_fixture,
        status=200,
    )
    responses.add(
        responses.GET,
        "https://places.googleapis.com/v1/places/ChIJN1t_tDeuEmsRUsoyG83frY4",
        json=details_with_5,
        status=200,
    )

    connector = GooglePlacesConnector()
    request = CollectionRequest(company="Tata Motors", platforms=[Platform.google])
    mentions, attempt = connector.collect(request)

    assert len(mentions) == 5
    assert attempt.status == AttemptStatus.success
    assert "capped at google places limit of 5" in attempt.reason.lower()


@responses.activate
def test_places_cost_recorded_per_call(
    mock_google_env, places_search_fixture, places_details_fixture
):
    responses.add(
        responses.POST,
        "https://places.googleapis.com/v1/places:searchText",
        json=places_search_fixture,
        status=200,
    )
    responses.add(
        responses.GET,
        "https://places.googleapis.com/v1/places/ChIJN1t_tDeuEmsRUsoyG83frY4",
        json=places_details_fixture,
        status=200,
    )

    budget_tracker = BudgetTracker(limit_usd=5.0)
    connector = GooglePlacesConnector(budget_tracker=budget_tracker)
    request = CollectionRequest(company="Tata Motors", platforms=[Platform.google])

    mentions, attempt = connector.collect(request)

    expected_cost = connector.cost_per_search_call + connector.cost_per_details_call
    assert abs(attempt.cost_usd - expected_cost) < 0.0001
    assert abs(budget_tracker.spent_total - expected_cost) < 0.0001
    assert budget_tracker.spent_by_platform["google"] == round(expected_cost, 4)


@responses.activate
def test_places_budget_exhausted_mid_run_keeps_partial_results(
    mock_google_env, places_search_fixture, places_details_fixture
):
    # Set limit enough for search call 1 and details call 1, but not branch 2
    exact_limit = 0.032 + 0.017  # 1 search + 1 details = 0.049
    budget_tracker = BudgetTracker(limit_usd=exact_limit)

    # Branch 1 calls
    responses.add(
        responses.POST,
        "https://places.googleapis.com/v1/places:searchText",
        json=places_search_fixture,
        status=200,
    )
    responses.add(
        responses.GET,
        "https://places.googleapis.com/v1/places/ChIJN1t_tDeuEmsRUsoyG83frY4",
        json=places_details_fixture,
        status=200,
    )

    connector = GooglePlacesConnector(budget_tracker=budget_tracker)
    request = CollectionRequest(
        company="Tata Motors",
        branches=["Branch 1", "Branch 2"],
        platforms=[Platform.google],
    )

    mentions, attempt = connector.collect(request)

    assert len(mentions) == 2  # Branch 1 was completed
    assert attempt.status == AttemptStatus.budget_exhausted
    assert "budget exhausted" in attempt.reason.lower()
    assert "2 reviews" in attempt.reason.lower()


@responses.activate
def test_places_429_rate_limited(mock_google_env):
    responses.add(
        responses.POST,
        "https://places.googleapis.com/v1/places:searchText",
        status=429,
        headers={"Retry-After": "30"},
    )

    connector = GooglePlacesConnector()
    request = CollectionRequest(company="Tata Motors", platforms=[Platform.google])
    mentions, attempt = connector.collect(request)

    assert len(mentions) == 0
    assert attempt.status == AttemptStatus.rate_limited
    assert "rate limited" in attempt.reason.lower()


@responses.activate
def test_places_403_no_retry(mock_google_env):
    responses.add(
        responses.POST,
        "https://places.googleapis.com/v1/places:searchText",
        status=403,
        body="Forbidden",
    )

    connector = GooglePlacesConnector()
    request = CollectionRequest(company="Tata Motors", platforms=[Platform.google])
    mentions, attempt = connector.collect(request)

    assert len(mentions) == 0
    assert attempt.status == AttemptStatus.failed
    assert "authentication or client error" in attempt.reason.lower()
    # Must not retry on 403
    assert len(responses.calls) == 1


@responses.activate
def test_places_500_then_success_retries(
    mock_google_env, places_search_fixture, places_details_fixture
):
    responses.add(
        responses.POST,
        "https://places.googleapis.com/v1/places:searchText",
        status=500,
    )
    responses.add(
        responses.POST,
        "https://places.googleapis.com/v1/places:searchText",
        json=places_search_fixture,
        status=200,
    )
    responses.add(
        responses.GET,
        "https://places.googleapis.com/v1/places/ChIJN1t_tDeuEmsRUsoyG83frY4",
        json=places_details_fixture,
        status=200,
    )

    connector = GooglePlacesConnector()
    request = CollectionRequest(company="Tata Motors", platforms=[Platform.google])
    mentions, attempt = connector.collect(request)

    assert attempt.status == AttemptStatus.success
    assert len(mentions) == 2
    # Verify search was called twice (1 failure + 1 retry success)
    search_calls = [
        c for c in responses.calls if "places:searchText" in c.request.url
    ]
    assert len(search_calls) == 2


@responses.activate
def test_places_cache_hit_makes_no_second_call(
    tmp_path, mock_google_env, places_search_fixture, places_details_fixture
):
    cache = ResultCache(cache_dir=tmp_path)
    connector = GooglePlacesConnector(cache=cache)
    connector.cache_ttl_days = 7.0  # Enable caching for this test

    responses.add(
        responses.POST,
        "https://places.googleapis.com/v1/places:searchText",
        json=places_search_fixture,
        status=200,
    )
    responses.add(
        responses.GET,
        "https://places.googleapis.com/v1/places/ChIJN1t_tDeuEmsRUsoyG83frY4",
        json=places_details_fixture,
        status=200,
    )

    request = CollectionRequest(company="Tata Motors", platforms=[Platform.google])

    # First call: cache miss, makes HTTP requests
    mentions1, attempt1 = connector.collect(request)
    assert len(mentions1) == 2
    assert len(responses.calls) == 2

    # Second call: cache hit, makes NO HTTP requests
    mentions2, attempt2 = connector.collect(request)
    assert len(mentions2) == 2
    assert len(responses.calls) == 2  # Still 2 calls, none added


@pytest.mark.live
def test_places_live_api():
    """Live integration test against Google Places API (New).

    Requires GOOGLE_PLACES_API_KEY in environment.
    """
    key = os.environ.get("GOOGLE_PLACES_API_KEY")
    if not key:
        pytest.skip("GOOGLE_PLACES_API_KEY not set in environment")

    connector = GooglePlacesConnector()
    request = CollectionRequest(company="Googleplex", platforms=[Platform.google])
    can_run, reason = connector.can_run(request)
    assert can_run is True

    mentions, attempt = connector.collect(request)
    assert attempt.status in (AttemptStatus.success, AttemptStatus.empty, AttemptStatus.rate_limited)

