"""Tests for the Amazon-style star-rating summary (module + endpoint)."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from src.contracts.enums import AttemptStatus, Method, Platform
from src.contracts.schemas import CollectionAttempt, RawMention
from src.reporting.rating_summary import extract_rating, summarize_ratings
from src.service.main import app
from src.service.run_store import RunStore


def _m(platform="tripadvisor", **payload):
    return {"platform": platform, "company": "Acme", "raw_payload": payload}


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"rating": 5}, 5.0),
        ({"rating": "4.0"}, 4.0),
        ({"rating": "4/5"}, 4.0),
        ({"rating": "8 out of 10"}, 4.0),
        ({"stars": "3 stars"}, 3.0),
        ({"rating_mapped": 2, "rating": 5}, 2.0),  # dataset mapping wins
        ({"rating": {"value": 1}}, 1.0),
        ({"rating": 0}, None),  # out of range
        ({"rating": 9}, None),  # 1-10 scale is not guessed
        ({"rating": True}, None),
        ({"rating": "great"}, None),
        ({"score": 120, "text": "reddit post"}, None),  # upvotes are not stars
        ({}, None),
    ],
)
def test_extract_rating(payload, expected):
    assert extract_rating({"raw_payload": payload}) == expected


def test_summary_percentages_and_unrated():
    mentions = [_m(rating=5)] * 6 + [_m(rating=4)] * 3 + [_m(rating=1)] + [_m("reddit", text="no stars")] * 2
    s = summarize_ratings(mentions)

    assert s["total_mentions"] == 12
    assert s["rated_count"] == 10
    assert s["unrated_count"] == 2
    assert s["average"] == 4.3
    dist = {d["stars"]: (d["count"], d["percent"]) for d in s["distribution"]}
    assert [d["stars"] for d in s["distribution"]] == [5, 4, 3, 2, 1]
    assert dist == {5: (6, 60.0), 4: (3, 30.0), 3: (0, 0.0), 2: (0, 0.0), 1: (1, 10.0)}

    assert s["by_platform"]["tripadvisor"]["rated_count"] == 10
    assert s["by_platform"]["reddit"]["rated_count"] == 0
    assert s["by_platform"]["reddit"]["average"] is None


def test_half_stars_round_up_but_average_uses_exact_values():
    s = summarize_ratings([_m(rating=4.5), _m(rating=3.4)])
    dist = {d["stars"]: d["count"] for d in s["distribution"]}
    assert dist[5] == 1 and dist[3] == 1
    assert s["average"] == 3.95


def test_empty_run():
    s = summarize_ratings([])
    assert s["rated_count"] == 0 and s["average"] is None
    assert all(d["percent"] == 0.0 for d in s["distribution"])


def test_ratings_endpoint(monkeypatch, tmp_path):
    store = RunStore(base_dir=tmp_path / "runs")
    monkeypatch.setattr("src.service.routes.runs.run_store", store)
    run_id = "run_ratings"
    now = datetime.now(timezone.utc)

    def mention(i, platform, payload):
        return RawMention(
            company="Acme",
            run_id=run_id,
            platform=platform,
            item_id=f"i{i}",
            raw_payload=payload,
            source="s",
            method_used=Method.api,
            tool_used="t",
            collected_at=now,
        )

    mentions = [
        mention(1, Platform.tripadvisor, {"rating": 5}),
        mention(2, Platform.tripadvisor, {"rating": 4}),
        mention(3, Platform.google, {"rating": 2}),
        mention(4, Platform.reddit, {"text": "hi"}),
    ]
    attempt = CollectionAttempt(
        company="Acme", platform=Platform.tripadvisor, method=Method.api,
        status=AttemptStatus.success, started_at=now, finished_at=now,
    )
    store.save_artifacts(run_id, mentions, [attempt])
    store.save_run_summary(run_id, {"run_id": run_id, "status": "completed", "created_at": now.isoformat()})

    client = TestClient(app)
    body = client.get(f"/api/runs/{run_id}/ratings").json()
    assert body["rated_count"] == 3 and body["unrated_count"] == 1
    assert body["average"] == pytest.approx(3.67)
    assert set(body["by_platform"]) == {"tripadvisor", "google", "reddit"}

    only_ta = client.get(f"/api/runs/{run_id}/ratings", params={"platform": "tripadvisor"}).json()
    assert only_ta["rated_count"] == 2
    assert {d["stars"]: d["percent"] for d in only_ta["distribution"]}[5] == 50.0

    assert client.get("/api/runs/does_not_exist/ratings").status_code == 404
