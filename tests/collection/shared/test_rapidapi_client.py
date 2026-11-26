"""Tests for the shared RapidAPI client."""
import pytest
import responses

from src.collection.common import rapidapi
from src.collection.common.rapidapi import RapidAPIClient
from src.contracts.enums import AttemptStatus

HOST = "example-api.p.rapidapi.com"
URL = f"https://{HOST}/search"
FAKE_KEY = "fake-rapidapi-key-abcdef"


@pytest.fixture
def rapidapi_env(monkeypatch):
    monkeypatch.setenv("RAPIDAPI_KEY", FAKE_KEY)
    monkeypatch.setattr(rapidapi.time, "sleep", lambda _s: None)


def test_missing_key_fails_without_request(monkeypatch):
    monkeypatch.delenv("RAPIDAPI_KEY", raising=False)
    result = RapidAPIClient(HOST, "Example").get("/search")
    assert not result.ok
    assert result.error == (AttemptStatus.failed, "RAPIDAPI_KEY missing")


@responses.activate
def test_get_sends_rapidapi_headers_and_reads_quota(rapidapi_env):
    responses.add(responses.GET, URL, json={"items": [1]}, status=200,
                  headers={"x-ratelimit-requests-remaining": "41"})

    result = RapidAPIClient(HOST, "Example").get("/search", params={"q": "taj"})

    assert result.ok
    assert result.data == {"items": [1]}
    assert result.quota_remaining == 41
    sent = responses.calls[0].request
    assert sent.headers["x-rapidapi-key"] == FAKE_KEY
    assert sent.headers["x-rapidapi-host"] == HOST
    assert "q=taj" in sent.url


@responses.activate
def test_server_error_is_retried_then_succeeds(rapidapi_env):
    responses.add(responses.GET, URL, status=503)
    responses.add(responses.GET, URL, json=[], status=200)

    result = RapidAPIClient(HOST, "Example", max_retries=1).get("/search")

    assert result.ok
    assert len(responses.calls) == 2


@responses.activate
def test_server_error_without_retries_fails(rapidapi_env):
    responses.add(responses.GET, URL, status=502)

    result = RapidAPIClient(HOST, "Example", max_retries=0).get("/search")

    assert result.error[0] == AttemptStatus.failed
    assert "HTTP 502" in result.error[1]
    assert len(responses.calls) == 1


@responses.activate
def test_bad_request_includes_provider_message_but_not_key(rapidapi_env):
    responses.add(responses.POST, URL, json={"message": f"places is required ({FAKE_KEY})"}, status=400)

    result = RapidAPIClient(HOST, "Example").post("/search", {})

    assert result.error[0] == AttemptStatus.failed
    assert "places is required" in result.error[1]
    assert FAKE_KEY not in result.error[1]


@responses.activate
def test_non_json_body_fails(rapidapi_env):
    responses.add(responses.GET, URL, body="<html>oops</html>", status=200)

    result = RapidAPIClient(HOST, "Example").get("/search")

    assert result.error == (AttemptStatus.failed, "Example: response was not JSON")
