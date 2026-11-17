"""Tests for the collection -> processing gateway.

Member 2's processing modules are replaced with small fakes, so these tests
need neither MongoDB, Presidio nor SOCL_AUTHOR_PEPPER.
"""
import json
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict

from src.service import processing_gateway as gateway
from src.service.main import app
from src.service.run_store import run_store

MENTION = {
    "schema_version": "1.0",
    "company": "Zomato",
    "run_id": "run_gw000001",
    "platform": "other",
    "item_id": "R1",
    "url": None,
    "branch": None,
    "content_type_hint": "review",
    "raw_payload": {"review_text": "Zomato was quick"},
    "source": "Sample",
    "method_used": "dataset",
    "tool_used": "Dataset: Sample",
    "fallback_from": None,
    "cost_usd": 0.0,
    "collected_at": "2026-11-17T07:00:00Z",
}
ATTEMPT = {
    "company": "Zomato",
    "platform": "other",
    "method": "dataset",
    "status": "success",
    "reason": None,
    "item_count": 1,
    "cost_usd": 0.0,
    "started_at": "2026-11-17T07:00:00Z",
    "finished_at": "2026-11-17T07:00:01Z",
    "scraping_checks": None,
    # collection-only diagnostics, not declared by the processing model
    "pages_fetched": 0,
    "pages_from_cache": 0,
    "delay_used": 0.0,
}


class FakeRawMention(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str
    company: str
    run_id: str | None = None
    platform: str
    item_id: str | None = None
    url: str | None = None
    branch: str | None = None
    content_type_hint: str | None = None
    raw_payload: dict
    source: str
    method_used: str
    tool_used: str
    fallback_from: str | None = None
    cost_usd: float = 0.0
    collected_at: str


class FakeAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company: str
    platform: str
    method: str
    status: str
    reason: str | None = None
    item_count: int
    cost_usd: float
    started_at: str
    finished_at: str
    scraping_checks: dict | None = None


@pytest.fixture
def runs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(run_store, "base_dir", tmp_path)
    gateway._active.clear()
    return tmp_path


@pytest.fixture
def fake_processing(monkeypatch):
    calls = []

    def process_handoff(mentions, attempts, industry_map, run_id=None, run_extra=None):
        calls.append(
            {
                "mentions": mentions,
                "attempts": attempts,
                "industry_map": industry_map,
                "run_id": run_id,
                "run_extra": run_extra,
            }
        )
        return {
            "run_id": run_id,
            "record_count": len(mentions),
            "counters": {"collected": len(mentions), "duplicates": 0},
            "report": {"total_cost_usd": 0.0},
        }

    modules = {
        "main": SimpleNamespace(process_handoff=process_handoff),
        "models": SimpleNamespace(RawMention=FakeRawMention, CollectionAttempt=FakeAttempt),
        "storage": SimpleNamespace(ensure_indexes=lambda: None),
    }
    monkeypatch.setattr(gateway, "load_processing_modules", lambda: (modules, None))
    monkeypatch.setattr(gateway, "check_mongo", lambda timeout_ms=2000: None)
    return calls


def _make_run(base, run_id="run_gw000001", status="completed", mentions=(MENTION,), attempts=(ATTEMPT,)):
    d = base / run_id
    d.mkdir(parents=True)
    (d / "run_summary.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "status": status,
                "companies": ["Zomato"],
                "counts": {"mentions_count": len(mentions), "attempts_count": len(attempts), "cost_usd": 0.0},
            }
        ),
        encoding="utf-8",
    )
    (d / "mentions.jsonl").write_text("".join(json.dumps(m) + "\n" for m in mentions), encoding="utf-8")
    (d / "attempts.jsonl").write_text("".join(json.dumps(a) + "\n" for a in attempts), encoding="utf-8")
    return run_id


def _wait_done(client, run_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/runs/{run_id}/processing").json()
        if body["status"] in ("completed", "failed"):
            return body
        time.sleep(0.05)
    raise AssertionError("processing did not finish")


client = TestClient(app)


def test_state_not_started_for_finished_run(runs_dir, fake_processing):
    rid = _make_run(runs_dir)
    body = client.get(f"/api/runs/{rid}/processing").json()
    assert body["status"] == "not_started"
    assert body["can_process"] is True
    assert body["collection_status"] == "completed"


def test_state_unknown_run_is_404(runs_dir):
    assert client.get("/api/runs/run_missing/processing").status_code == 404
    assert client.post("/api/runs/run_missing/process").status_code == 404


def test_process_hands_collection_output_to_processing(runs_dir, fake_processing):
    rid = _make_run(runs_dir)
    resp = client.post(f"/api/runs/{rid}/process")
    assert resp.status_code == 202
    body = _wait_done(client, rid)

    assert body["status"] == "completed"
    assert body["record_count"] == 1
    assert body["mentions_in"] == 1 and body["attempts_in"] == 1

    call = fake_processing[0]
    # the collection run ID is reused, so both dashboards show the same ID
    assert call["run_id"] == rid
    assert call["run_extra"] == {"source": "collection_gateway", "collection_run_id": rid}
    # industry comes from config/companies.yaml
    assert call["industry_map"] == {"Zomato": "food_delivery"}
    # raw_payload is passed through unchanged
    assert call["mentions"][0].raw_payload == MENTION["raw_payload"]
    # processing.json is written beside the collection files
    assert (runs_dir / rid / "processing.json").is_file()


def test_collection_only_attempt_fields_are_dropped(runs_dir, fake_processing):
    rid = _make_run(runs_dir)
    client.post(f"/api/runs/{rid}/process")
    _wait_done(client, rid)
    attempt = fake_processing[0]["attempts"][0]
    assert not hasattr(attempt, "pages_fetched")


def test_run_summary_is_not_modified(runs_dir, fake_processing):
    rid = _make_run(runs_dir)
    before = (runs_dir / rid / "run_summary.json").read_text(encoding="utf-8")
    client.post(f"/api/runs/{rid}/process")
    _wait_done(client, rid)
    assert (runs_dir / rid / "run_summary.json").read_text(encoding="utf-8") == before


@pytest.mark.parametrize("status", ["running", "queued", "failed"])
def test_unfinished_or_failed_runs_are_refused(runs_dir, fake_processing, status):
    rid = _make_run(runs_dir, status=status)
    resp = client.post(f"/api/runs/{rid}/process")
    assert resp.status_code == 409
    assert fake_processing == []


def test_partial_runs_can_be_processed(runs_dir, fake_processing):
    rid = _make_run(runs_dir, status="partial")
    assert client.post(f"/api/runs/{rid}/process").status_code == 202
    assert _wait_done(client, rid)["status"] == "completed"


def test_run_with_no_mentions_is_refused(runs_dir, fake_processing):
    rid = _make_run(runs_dir, mentions=())
    resp = client.post(f"/api/runs/{rid}/process")
    assert resp.status_code == 409
    assert "no mentions" in resp.json()["detail"]


def test_already_processed_run_is_refused(runs_dir, fake_processing):
    rid = _make_run(runs_dir)
    client.post(f"/api/runs/{rid}/process")
    _wait_done(client, rid)
    resp = client.post(f"/api/runs/{rid}/process")
    assert resp.status_code == 409
    assert len(fake_processing) == 1


def test_processing_unavailable_returns_503(runs_dir, monkeypatch):
    rid = _make_run(runs_dir)
    monkeypatch.setattr(
        gateway, "load_processing_modules", lambda: (None, "SOCL_AUTHOR_PEPPER env var is required")
    )
    resp = client.post(f"/api/runs/{rid}/process")
    assert resp.status_code == 503
    assert "SOCL_AUTHOR_PEPPER" in resp.json()["detail"]
    status = client.get("/api/processing/status").json()
    assert status == {"available": False, "reason": "SOCL_AUTHOR_PEPPER env var is required"}


def test_mongo_down_returns_503(runs_dir, fake_processing, monkeypatch):
    rid = _make_run(runs_dir)
    monkeypatch.setattr(gateway, "check_mongo", lambda timeout_ms=2000: "MongoDB is not reachable")
    assert client.post(f"/api/runs/{rid}/process").status_code == 503
    assert client.get("/api/processing/status").json()["available"] is False


def test_processing_error_is_reported_as_failed(runs_dir, fake_processing, monkeypatch):
    rid = _make_run(runs_dir)
    modules, _ = gateway.load_processing_modules()

    def boom(*args, **kwargs):
        raise ValueError("could not convert string to float: ''")

    modules["main"].process_handoff = boom
    client.post(f"/api/runs/{rid}/process")
    body = _wait_done(client, rid)
    assert body["status"] == "failed"
    assert "could not convert" in body["error"]
    # a failed run can be retried
    modules["main"].process_handoff = lambda *a, **k: {"record_count": 0, "counters": {}, "report": {}}
    assert client.post(f"/api/runs/{rid}/process").status_code == 202


def test_interrupted_processing_is_reported_as_failed(runs_dir, fake_processing):
    rid = _make_run(runs_dir)
    (runs_dir / rid / "processing.json").write_text(json.dumps({"status": "running"}), encoding="utf-8")
    body = client.get(f"/api/runs/{rid}/processing").json()
    assert body["status"] == "failed"
    assert "interrupted" in body["error"]


def test_invalid_mention_line_fails_with_line_number(runs_dir, fake_processing):
    bad = {**MENTION}
    bad.pop("company")
    rid = _make_run(runs_dir, mentions=(MENTION, bad))
    client.post(f"/api/runs/{rid}/process")
    body = _wait_done(client, rid)
    assert body["status"] == "failed"
    assert "mentions.jsonl line 2" in body["error"]


def test_mount_processing_routes_adds_member2_routes(monkeypatch):
    from fastapi import FastAPI

    m2 = FastAPI()

    @m2.post("/process")
    def _p():
        return {"ok": True}

    modules = {"main": SimpleNamespace(app=m2), "storage": SimpleNamespace(ensure_indexes=lambda: None)}
    monkeypatch.setattr(gateway, "load_processing_modules", lambda: (modules, None))
    host = FastAPI()
    assert gateway.mount_processing_routes(host) is None
    assert TestClient(host).post("/process").json() == {"ok": True}


def test_mount_processing_routes_skips_when_unavailable(monkeypatch):
    from fastapi import FastAPI

    monkeypatch.setattr(gateway, "load_processing_modules", lambda: (None, "no pepper"))
    host = FastAPI()
    before = len(host.router.routes)
    assert gateway.mount_processing_routes(host) == "no pepper"
    assert len(host.router.routes) == before
