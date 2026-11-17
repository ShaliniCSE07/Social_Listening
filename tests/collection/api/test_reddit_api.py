"""Tests for Reddit API connector."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import pytest
import requests
import responses

from src.collection.base import CollectionRequest
from src.collection.plugins.api.reddit_api import RedditAPIConnector
from src.contracts.enums import AttemptStatus, ContentType, Method, Platform

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"


@pytest.fixture
def reddit_search_fixture() -> dict:
    fixture_path = FIXTURES_DIR / "reddit_search_sample.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def mock_reddit_env(monkeypatch):
    monkeypatch.setenv("REDDIT_CLIENT_ID", "mock_client_id_xyz")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "mock_client_secret_abc")
    monkeypatch.setenv("REDDIT_USER_AGENT", "TestBot/1.0")


def mock_oauth_token(status=200, body=None):
    if body is None:
        body = json.dumps({"access_token": "mock_bearer_token_123", "expires_in": 3600})
    responses.add(
        responses.POST,
        "https://www.reddit.com/api/v1/access_token",
        body=body,
        status=status,
        content_type="application/json",
    )


def test_missing_credentials_gives_can_run_false(monkeypatch):
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("REDDIT_USER_AGENT", raising=False)

    connector = RedditAPIConnector()
    can_run, reason = connector.can_run(CollectionRequest(company="Tata Motors"))
    assert can_run is False
    assert "Reddit credentials missing" in reason


def test_secrets_never_appear_in_attempt_reason(mock_reddit_env):
    secret = "mock_client_secret_abc"
    connector = RedditAPIConnector()
    request = CollectionRequest(company="Tata Motors", platforms=[Platform.twitter_x])
    _, attempt = connector.collect(request)

    assert secret not in (attempt.reason or "")
    assert attempt.status == AttemptStatus.failed


@responses.activate
def test_reddit_success_maps_fields_and_unaltered_payload(mock_reddit_env, reddit_search_fixture):
    mock_oauth_token()
    responses.add(
        responses.GET,
        "https://oauth.reddit.com/search",
        json=reddit_search_fixture,
        status=200,
    )

    connector = RedditAPIConnector()
    request = CollectionRequest(
        company="Tata Motors",
        alt_spellings=["Tata"],
        platforms=[Platform.reddit],
    )

    mentions, attempt = connector.collect(request)

    assert attempt.status == AttemptStatus.success
    assert attempt.item_count == 2
    assert len(mentions) == 2

    # Check mapping of first item
    first = mentions[0]
    assert first.platform == Platform.reddit
    assert first.method_used == Method.api
    assert first.tool_used == "Reddit API"
    assert first.item_id == "t3_item1"
    assert first.url == "https://reddit.com/r/cars/comments/item1/tata_motors_launches_new_ev/"
    assert first.source == "reddit.com/r/cars"
    assert first.content_type_hint == ContentType.post
    assert first.cost_usd == 0.0
    assert first.collected_at.tzinfo == timezone.utc

    # Verify raw_payload matches the fixture data dict exactly
    expected_payload = reddit_search_fixture["data"]["children"][0]["data"]
    assert first.raw_payload == expected_payload


@responses.activate
def test_reddit_empty_result(mock_reddit_env):
    mock_oauth_token()
    responses.add(
        responses.GET,
        "https://oauth.reddit.com/search",
        json={"kind": "Listing", "data": {"after": None, "children": []}},
        status=200,
    )

    connector = RedditAPIConnector()
    request = CollectionRequest(company="UnknownBrand", platforms=[Platform.reddit])
    mentions, attempt = connector.collect(request)

    assert len(mentions) == 0
    assert attempt.status == AttemptStatus.empty
    assert attempt.item_count == 0


@responses.activate
def test_reddit_pagination_follows_after(mock_reddit_env):
    mock_oauth_token()

    page1 = {
        "kind": "Listing",
        "data": {
            "after": "t3_cursor2",
            "children": [
                {
                    "kind": "t3",
                    "data": {
                        "name": "t3_page1_item",
                        "id": "page1_item",
                        "title": "Tata Motors page 1 update",
                        "selftext": "Tata Motors announcement",
                        "subreddit": "news",
                        "permalink": "/r/news/comments/p1/tata/",
                    },
                }
            ],
        },
    }
    page2 = {
        "kind": "Listing",
        "data": {
            "after": None,
            "children": [
                {
                    "kind": "t3",
                    "data": {
                        "name": "t3_page2_item",
                        "id": "page2_item",
                        "title": "Tata Motors page 2 expansion",
                        "selftext": "Tata Motors updates",
                        "subreddit": "investing",
                        "permalink": "/r/investing/comments/p2/tata/",
                    },
                }
            ],
        },
    }

    responses.add(
        responses.GET,
        "https://oauth.reddit.com/search",
        json=page1,
        status=200,
    )
    responses.add(
        responses.GET,
        "https://oauth.reddit.com/search",
        json=page2,
        status=200,
    )

    connector = RedditAPIConnector()
    request = CollectionRequest(company="Tata Motors", platforms=[Platform.reddit])
    mentions, attempt = connector.collect(request)

    assert len(mentions) == 2
    assert mentions[0].item_id == "t3_page1_item"
    assert mentions[1].item_id == "t3_page2_item"
    assert attempt.status == AttemptStatus.success


@responses.activate
def test_reddit_company_filter_drops_unrelated_items(mock_reddit_env, reddit_search_fixture):
    mock_oauth_token()
    responses.add(
        responses.GET,
        "https://oauth.reddit.com/search",
        json=reddit_search_fixture,
        status=200,
    )

    connector = RedditAPIConnector()
    # The fixture has 3 items: 2 mentioning Tata/Tata Motors, 1 about space exploration
    request = CollectionRequest(company="Tata Motors", alt_spellings=["Tata"])
    mentions, _ = connector.collect(request)

    assert len(mentions) == 2
    item_ids = {m.item_id for m in mentions}
    assert "t3_item1" in item_ids
    assert "t3_item2" in item_ids
    assert "t3_item3" not in item_ids


@responses.activate
def test_reddit_date_filter(mock_reddit_env, reddit_search_fixture):
    mock_oauth_token()
    responses.add(
        responses.GET,
        "https://oauth.reddit.com/search",
        json=reddit_search_fixture,
        status=200,
    )

    connector = RedditAPIConnector()
    # item1 created_utc = 1762500000.0 (approx 2025-11-07 07:20:00 UTC)
    # item2 created_utc = 1762490000.0 (approx 2025-11-07 04:33:20 UTC)
    date_from = datetime.fromtimestamp(1762495000.0, tz=timezone.utc)
    request = CollectionRequest(
        company="Tata Motors",
        alt_spellings=["Tata"],
        date_from=date_from,
    )
    mentions, _ = connector.collect(request)

    assert len(mentions) == 1
    assert mentions[0].item_id == "t3_item1"


@responses.activate
def test_reddit_429_gives_rate_limited(mock_reddit_env):
    mock_oauth_token()
    responses.add(
        responses.GET,
        "https://oauth.reddit.com/search",
        status=429,
        headers={"Retry-After": "60"},
    )

    connector = RedditAPIConnector()
    request = CollectionRequest(company="Tata Motors")
    mentions, attempt = connector.collect(request)

    assert len(mentions) == 0
    assert attempt.status == AttemptStatus.rate_limited
    assert "rate limited" in attempt.reason.lower()


@responses.activate
def test_reddit_401_gives_failed_with_no_retry(mock_reddit_env):
    mock_oauth_token()
    responses.add(
        responses.GET,
        "https://oauth.reddit.com/search",
        status=401,
        body="Unauthorized",
    )

    connector = RedditAPIConnector()
    request = CollectionRequest(company="Tata Motors")
    mentions, attempt = connector.collect(request)

    assert len(mentions) == 0
    assert attempt.status == AttemptStatus.failed
    assert "authentication or permission error" in attempt.reason
    # Ensure it did not retry on 401
    search_calls = [c for c in responses.calls if "oauth.reddit.com" in c.request.url]
    assert len(search_calls) == 1


@responses.activate
def test_reddit_500_then_success_retries(mock_reddit_env):
    mock_oauth_token()
    # First search call returns 500, second returns 200
    responses.add(
        responses.GET,
        "https://oauth.reddit.com/search",
        status=500,
    )
    responses.add(
        responses.GET,
        "https://oauth.reddit.com/search",
        json={
            "kind": "Listing",
            "data": {
                "after": None,
                "children": [
                    {
                        "kind": "t3",
                        "data": {
                            "name": "t3_recovered",
                            "id": "recov",
                            "title": "Tata Motors recovery post",
                            "selftext": "Recovered from 500",
                            "subreddit": "news",
                            "permalink": "/r/news/comments/recov/tata/",
                        },
                    }
                ],
            },
        },
        status=200,
    )

    connector = RedditAPIConnector()
    request = CollectionRequest(company="Tata Motors")
    mentions, attempt = connector.collect(request)

    assert attempt.status == AttemptStatus.success
    assert len(mentions) == 1
    assert mentions[0].item_id == "t3_recovered"
    search_calls = [c for c in responses.calls if "oauth.reddit.com" in c.request.url]
    assert len(search_calls) == 2


@responses.activate
def test_reddit_timeout_gives_failed(mock_reddit_env):
    mock_oauth_token()
    responses.add(
        responses.GET,
        "https://oauth.reddit.com/search",
        body=requests.exceptions.Timeout("Connection timed out"),
    )
    responses.add(
        responses.GET,
        "https://oauth.reddit.com/search",
        body=requests.exceptions.Timeout("Connection timed out retry"),
    )
    responses.add(
        responses.GET,
        "https://oauth.reddit.com/search",
        body=requests.exceptions.Timeout("Connection timed out final"),
    )

    connector = RedditAPIConnector()
    request = CollectionRequest(company="Tata Motors")
    mentions, attempt = connector.collect(request)

    assert len(mentions) == 0
    assert attempt.status == AttemptStatus.failed
    assert "network error" in attempt.reason.lower() or "timeout" in attempt.reason.lower()


@responses.activate
def test_reddit_token_request_failure_gives_failed(mock_reddit_env):
    mock_oauth_token(status=401, body="Bad Credentials")

    connector = RedditAPIConnector()
    request = CollectionRequest(company="Tata Motors")
    mentions, attempt = connector.collect(request)

    assert len(mentions) == 0
    assert attempt.status == AttemptStatus.failed
    assert "authentication or permission error" in attempt.reason


@pytest.mark.live
def test_reddit_live_api():
    """Live integration test against Reddit API.

    Requires valid REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, and REDDIT_USER_AGENT in env.
    """
    client_id = os.environ.get("REDDIT_CLIENT_ID")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET")
    user_agent = os.environ.get("REDDIT_USER_AGENT")

    if not client_id or not client_secret or not user_agent:
        pytest.skip("Reddit live credentials not set in environment")

    connector = RedditAPIConnector()
    request = CollectionRequest(company="Python", platforms=[Platform.reddit])
    can_run, reason = connector.can_run(request)
    assert can_run is True

    mentions, attempt = connector.collect(request)
    assert attempt.status in (AttemptStatus.success, AttemptStatus.empty, AttemptStatus.rate_limited)
    if attempt.status == AttemptStatus.success:
        assert len(mentions) > 0
