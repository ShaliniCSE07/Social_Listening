"""Unit and integration tests for the FastAPI service layer."""
from datetime import datetime, timezone
from pathlib import Path
import time
from typing import ClassVar, List, Tuple
import pytest
from fastapi.testclient import TestClient

from src.collection.base import BaseConnector, CollectionRequest
from src.contracts.enums import AttemptStatus, Method, Platform
from src.contracts.schemas import CollectionAttempt, RawMention
from src.service.main import app
from src.service.models import CompanyInput, CreateRunRequest, SourcesInput
from src.service.run_store import RunStore, run_store
from src.service.runner import RunRunner, default_runner


def make_mention(**overrides) -> RawMention:
    """Helper that fills every required RawMention field with valid defaults."""
    now = datetime.now(timezone.utc)
    base = {
        "schema_version": "1.0",
        "company": "TestCompany",
        "platform": Platform.reddit,
        "raw_payload": {"text": "Test mention text", "created_utc": "2026-01-01"},
        "source": "reddit.com/r/test",
        "method_used": Method.api,
        "tool_used": "Reddit API",
        "cost_usd": 0.0,
        "collected_at": now,
        "item_id": "m1",
    }
    base.update(overrides)
    return RawMention(**base)


class MockSuccessConnector(BaseConnector):
    method: ClassVar[Method] = Method.api
    name: ClassVar[str] = "mock_success"
    platforms: ClassVar[List[Platform]] = [Platform.reddit]

    def can_run(self, request: CollectionRequest) -> Tuple[bool, str]:
        return True, "OK"

    def estimate_cost(self, request: CollectionRequest) -> float:
        return 0.0

    def collect(self, request: CollectionRequest) -> Tuple[List[RawMention], CollectionAttempt]:
        now = datetime.now(timezone.utc)
        m = make_mention(
            company=request.company,
            run_id=request.run_id,
            tool_used="Reddit API",
            raw_payload={"text": f"Great post about {request.company}", "created_utc": "2026-01-01"},
        )
        att = CollectionAttempt(
            company=request.company,
            platform=Platform.reddit,
            method=self.method,
            status=AttemptStatus.success,
            reason="Mock collection succeeded",
            item_count=1,
            cost_usd=0.0,
            started_at=now,
            finished_at=now,
        )
        return [m], att


class MockFailConnector(BaseConnector):
    method: ClassVar[Method] = Method.api
    name: ClassVar[str] = "mock_fail"
    platforms: ClassVar[List[Platform]] = [Platform.google]

    def can_run(self, request: CollectionRequest) -> Tuple[bool, str]:
        return True, "OK"

    def estimate_cost(self, request: CollectionRequest) -> float:
        return 0.0

    def collect(self, request: CollectionRequest) -> Tuple[List[RawMention], CollectionAttempt]:
        now = datetime.now(timezone.utc)
        att = CollectionAttempt(
            company=request.company,
            platform=Platform.google,
            method=self.method,
            status=AttemptStatus.failed,
            reason="Mock API 500 internal server error",
            item_count=0,
            cost_usd=0.0,
            started_at=now,
            finished_at=now,
        )
        return [], att


class MockExplodingConnector(BaseConnector):
    method: ClassVar[Method] = Method.api
    name: ClassVar[str] = "mock_explode"
    platforms: ClassVar[List[Platform]] = [Platform.reddit]

    def can_run(self, request: CollectionRequest) -> Tuple[bool, str]:
        return True, "OK"

    def estimate_cost(self, request: CollectionRequest) -> float:
        return 0.0

    def collect(self, request: CollectionRequest) -> Tuple[List[RawMention], CollectionAttempt]:
        raise RuntimeError("Fatal unhandled connector exception")


@pytest.fixture
def client():
    return TestClient(app)


def test_health(client):
    """GET /health returns 200 with ok status."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_sources_endpoint_shows_missing_credentials_and_no_secrets(client, monkeypatch):
    """Sources endpoint reports can_run=False when credentials missing and never leaks secrets."""
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("REDDIT_USER_AGENT", raising=False)

    resp = client.get("/api/config/sources")
    assert resp.status_code == 200
    items = resp.json()
    assert isinstance(items, list)

    reddit_item = next((item for item in items if item["name"] == "reddit_api"), None)
    assert reddit_item is not None
    assert reddit_item["can_run"] is False
    assert "Reddit credentials missing" in reddit_item["reason"]

    # Verify no secret tokens leaked
    for item in items:
        assert "secret" not in item["reason"].lower() or "missing" in item["reason"].lower()


def test_datasets_endpoint(client):
    """GET /api/config/datasets returns catalogue entries."""
    resp = client.get("/api/config/datasets")
    assert resp.status_code == 200
    datasets = resp.json()
    assert isinstance(datasets, list)


def test_unknown_dataset_key_gives_422(client):
    """Unknown dataset key in sources gives HTTP 422 with clear message."""
    payload = {
        "companies": [{"name": "Acme"}],
        "sources": {"dataset_keys": ["nonexistent_key_9999"]},
    }
    resp = client.post("/api/runs", json=payload)
    assert resp.status_code == 422
    assert "Unknown dataset key" in resp.json()["detail"]


def test_unknown_api_platform_gives_422(client):
    """Unknown API platform in sources gives HTTP 422."""
    payload = {
        "companies": [{"name": "Acme"}],
        "sources": {"api": ["unsupported_platform_xyz"]},
    }
    resp = client.post("/api/runs", json=payload)
    assert resp.status_code == 422
    assert "Unknown API platform" in resp.json()["detail"]


def test_create_run_returns_202_and_finishes(client, monkeypatch, tmp_path):
    """POST /api/runs returns 202 with run_id, finishes collection, and is queryable."""
    custom_store = RunStore(base_dir=tmp_path / "runs")
    monkeypatch.setattr("src.service.routes.runs.run_store", custom_store)
    monkeypatch.setattr("src.service.runner.run_store", custom_store)

    test_runner = RunRunner(connector_classes=[MockSuccessConnector])
    monkeypatch.setattr("src.service.routes.runs.default_runner", test_runner)

    payload = {
        "companies": [{"name": "Zomato", "alt_spellings": ["Zomato Ltd"]}],
        "sources": {"api": ["reddit"]},
        "budget_usd": 15.0,
    }

    post_resp = client.post("/api/runs", json=payload)
    assert post_resp.status_code == 202
    data = post_resp.json()
    run_id = data["run_id"]
    assert run_id.startswith("run_")

    # Wait briefly for background thread to complete
    for _ in range(20):
        time.sleep(0.05)
        run_data = custom_store.get_run(run_id)
        if run_data and run_data.get("status") in ("completed", "failed", "partial"):
            break

    run_detail = custom_store.get_run(run_id)
    assert run_detail is not None
    assert run_detail["status"] == "completed"
    assert run_detail["counts"]["mentions_count"] == 1
    assert run_detail["budget_snapshot"]["limit_usd"] == 15.0


def test_one_failing_source_gives_partial(monkeypatch, tmp_path):
    """When one source succeeds and another fails, run status is 'partial'."""
    custom_store = RunStore(base_dir=tmp_path / "runs")
    test_runner = RunRunner(connector_classes=[MockSuccessConnector, MockFailConnector])
    monkeypatch.setattr("src.service.runner.run_store", custom_store)

    req = CreateRunRequest(
        companies=[CompanyInput(name="Zomato")],
        sources=SourcesInput(api=["reddit", "google"]),
    )

    summary = test_runner.run("run_partial_test", req)
    assert summary["status"] == "partial"
    assert summary["counts"]["mentions_count"] == 1
    assert summary["counts"]["attempts_count"] == 2


def test_mentions_pagination_and_filters(client, monkeypatch, tmp_path):
    """Mentions endpoint handles pagination (page, page_size max 200), compact vs full view, and filters."""
    custom_store = RunStore(base_dir=tmp_path / "runs")
    monkeypatch.setattr("src.service.routes.runs.run_store", custom_store)

    run_id = "run_pagination_test"
    now = datetime.now(timezone.utc)
    mentions: List[RawMention] = []

    for i in range(10):
        company = "Zomato" if i < 6 else "Swiggy"
        platform = Platform.reddit if i % 2 == 0 else Platform.google
        mentions.append(
            make_mention(
                company=company,
                run_id=run_id,
                platform=platform,
                item_id=f"item_{i}",
                raw_payload={"text": f"Mention {i} for {company}", "date": "2026-03-01"},
                source=f"source_{i}",
                method_used=Method.api,
                tool_used="Reddit API",
                cost_usd=0.01 * i,
                collected_at=now,
            )
        )

    attempts = [
        CollectionAttempt(
            company="Zomato",
            platform=Platform.reddit,
            method=Method.api,
            status=AttemptStatus.success,
            reason="Done",
            item_count=10,
            cost_usd=0.0,
            started_at=now,
            finished_at=now,
        )
    ]

    custom_store.save_artifacts(run_id, mentions, attempts)
    custom_store.save_run_summary(
        run_id,
        {
            "run_id": run_id,
            "status": "completed",
            "created_at": now.isoformat(),
            "companies": ["Zomato", "Swiggy"],
            "counts": {"mentions_count": 10, "attempts_count": 1, "cost_usd": 0.0},
        },
    )

    # 1. Pagination check
    resp = client.get(f"/api/runs/{run_id}/mentions?page=1&page_size=4")
    assert resp.status_code == 200
    res_data = resp.json()
    assert len(res_data["items"]) == 4
    assert res_data["total"] == 10
    assert res_data["pages"] == 3
    # Compact view check: contains short_text, platform, source
    assert "short_text" in res_data["items"][0]
    assert "raw_payload" not in res_data["items"][0]

    # 2. Company filter check
    resp_comp = client.get(f"/api/runs/{run_id}/mentions?company=Swiggy")
    assert resp_comp.status_code == 200
    assert resp_comp.json()["total"] == 4

    # 3. Full format check
    resp_full = client.get(f"/api/runs/{run_id}/mentions?full=true&page_size=2")
    assert resp_full.status_code == 200
    full_data = resp_full.json()
    assert "raw_payload" in full_data["items"][0]
    assert "schema_version" in full_data["items"][0]

    # 4. Limit check (page_size > 200 returns 422)
    resp_limit = client.get(f"/api/runs/{run_id}/mentions?page_size=205")
    assert resp_limit.status_code == 422


def test_cors_allows_only_configured_origin(client):
    """CORS middleware allows only configured origin (e.g. http://localhost:3000), not *."""
    # Allowed origin
    res_allowed = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert res_allowed.headers.get("access-control-allow-origin") == "http://localhost:3000"

    # Disallowed origin
    res_disallowed = client.options(
        "/health",
        headers={
            "Origin": "http://unauthorized-domain.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert res_disallowed.headers.get("access-control-allow-origin") != "http://unauthorized-domain.com"
    assert res_disallowed.headers.get("access-control-allow-origin") != "*"


def test_downloads_return_right_file(client, monkeypatch, tmp_path):
    """Download endpoint returns mentions.jsonl and attempts.jsonl with right media type."""
    custom_store = RunStore(base_dir=tmp_path / "runs")
    monkeypatch.setattr("src.service.routes.runs.run_store", custom_store)

    run_id = "run_dl_test"
    now = datetime.now(timezone.utc)
    m = make_mention(
        company="Zomato",
        platform=Platform.reddit,
        raw_payload={"text": "dl test"},
        source="reddit",
        tool_used="Reddit API",
        collected_at=now,
    )
    att = CollectionAttempt(
        company="Zomato",
        platform=Platform.reddit,
        method=Method.api,
        status=AttemptStatus.success,
        reason="Downloaded ok",
        item_count=1,
        cost_usd=0.0,
        started_at=now,
        finished_at=now,
    )
    custom_store.save_artifacts(run_id, [m], [att])
    custom_store.save_run_summary(
        run_id,
        {
            "run_id": run_id,
            "status": "completed",
            "created_at": now.isoformat(),
            "companies": ["Zomato"],
            "counts": {"mentions_count": 1, "attempts_count": 1, "cost_usd": 0.0},
        },
    )

    # Valid download: mentions
    resp_m = client.get(f"/api/runs/{run_id}/download?file=mentions.jsonl")
    assert resp_m.status_code == 200
    assert resp_m.headers["content-type"] == "application/x-ndjson"
    assert "dl test" in resp_m.text

    # Valid download: attempts
    resp_a = client.get(f"/api/runs/{run_id}/download?file=attempts.jsonl")
    assert resp_a.status_code == 200
    assert "Downloaded ok" in resp_a.text

    # Invalid file param gives 422
    resp_bad = client.get(f"/api/runs/{run_id}/download?file=passwords.txt")
    assert resp_bad.status_code == 422

    # Nonexistent run gives 404
    resp_404 = client.get("/api/runs/nonexistent/download?file=mentions.jsonl")
    assert resp_404.status_code == 404


def test_restart_reload_run_list(tmp_path):
    """RunStore rebuilds run list across restarts from filesystem run_summary.json files."""
    store1 = RunStore(base_dir=tmp_path / "runs")
    store1.save_run_summary(
        "run_001",
        {
            "run_id": "run_001",
            "status": "completed",
            "created_at": "2026-02-01T10:00:00Z",
            "companies": ["Acme"],
            "counts": {"mentions_count": 5, "attempts_count": 1, "cost_usd": 0.0},
        },
    )
    store1.save_run_summary(
        "run_002",
        {
            "run_id": "run_002",
            "status": "failed",
            "created_at": "2026-02-02T10:00:00Z",
            "companies": ["Beta"],
            "counts": {"mentions_count": 0, "attempts_count": 1, "cost_usd": 0.0},
        },
    )

    # Simulate restart with fresh instance
    store2 = RunStore(base_dir=tmp_path / "runs")
    runs = store2.list_runs()

    assert len(runs) == 2
    # Newer run (run_002) first
    assert runs[0]["id"] == "run_002"
    assert runs[1]["id"] == "run_001"


def test_run_unexpected_exception_fails_and_not_running(monkeypatch, tmp_path):
    """When an unhandled exception occurs in a runner/connector, the run ends as 'failed' and never stays 'running'."""
    custom_store = RunStore(base_dir=tmp_path / "runs")
    monkeypatch.setattr("src.service.runner.run_store", custom_store)

    test_runner = RunRunner(connector_classes=[MockExplodingConnector])

    req = CreateRunRequest(
        companies=[CompanyInput(name="Acme")],
        sources=SourcesInput(api=["reddit"]),
    )

    summary = test_runner.run("run_crash_test", req)
    assert summary["status"] == "failed"
    assert summary["status"] != "running"

    # Verify persisted summary
    persisted = custom_store.get_run("run_crash_test")
    assert persisted is not None
    assert persisted["status"] == "failed"
    assert persisted["status"] != "running"


def test_handles_list_reaches_collection_request(monkeypatch, tmp_path):
    """Handles provided as a list in CompanyInput reach the CollectionRequest intact."""
    custom_store = RunStore(base_dir=tmp_path / "runs")
    monkeypatch.setattr("src.service.runner.run_store", custom_store)

    captured_requests: List[CollectionRequest] = []

    class MockCaptureConnector(BaseConnector):
        method: ClassVar[Method] = Method.api
        name: ClassVar[str] = "capture"
        platforms: ClassVar[List[Platform]] = [Platform.reddit]

        def can_run(self, request: CollectionRequest) -> Tuple[bool, str]:
            captured_requests.append(request)
            return True, "OK"

        def estimate_cost(self, request: CollectionRequest) -> float:
            return 0.0

        def collect(self, request: CollectionRequest) -> Tuple[List[RawMention], CollectionAttempt]:
            now = datetime.now(timezone.utc)
            return [], CollectionAttempt(
                company=request.company,
                platform=Platform.reddit,
                method=self.method,
                status=AttemptStatus.success,
                started_at=now,
                finished_at=now,
            )

    test_runner = RunRunner(connector_classes=[MockCaptureConnector])

    req = CreateRunRequest(
        companies=[CompanyInput(name="Acme", handles=["@acme_corp", "#acme"])],
        sources=SourcesInput(api=["reddit"]),
    )
    test_runner.run("run_handles_test", req)

    assert len(captured_requests) == 1
    assert captured_requests[0].handles == ["@acme_corp", "#acme"]
    assert isinstance(captured_requests[0].handles, list)


def test_require_fresh_omitted_becomes_false(monkeypatch, tmp_path):
    """When require_fresh is omitted from the request, it becomes False on the CollectionRequest."""
    custom_store = RunStore(base_dir=tmp_path / "runs")
    monkeypatch.setattr("src.service.runner.run_store", custom_store)

    captured_requests: List[CollectionRequest] = []

    class MockCaptureConnector(BaseConnector):
        method: ClassVar[Method] = Method.api
        name: ClassVar[str] = "capture"
        platforms: ClassVar[List[Platform]] = [Platform.reddit]

        def can_run(self, request: CollectionRequest) -> Tuple[bool, str]:
            captured_requests.append(request)
            return True, "OK"

        def estimate_cost(self, request: CollectionRequest) -> float:
            return 0.0

        def collect(self, request: CollectionRequest) -> Tuple[List[RawMention], CollectionAttempt]:
            now = datetime.now(timezone.utc)
            return [], CollectionAttempt(
                company=request.company,
                platform=Platform.reddit,
                method=self.method,
                status=AttemptStatus.success,
                started_at=now,
                finished_at=now,
            )

    test_runner = RunRunner(connector_classes=[MockCaptureConnector])

    req = CreateRunRequest(
        companies=[CompanyInput(name="Acme")],
        sources=SourcesInput(api=["reddit"]),
        # require_fresh is omitted (None)
    )
    test_runner.run("run_fresh_test", req)

    assert len(captured_requests) == 1
    assert captured_requests[0].require_fresh is False
    assert isinstance(captured_requests[0].require_fresh, bool)


def test_post_api_plan_returns_decisions_and_never_leaks_key(client, monkeypatch):
    """POST /api/plan returns valid/invalid companies and agent decisions without leaking secrets."""
    secret_token = "secret_x_token_999999"
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", secret_token)
    monkeypatch.setenv("REDDIT_CLIENT_ID", "reddit_client_id_12345")

    payload = {
        "companies": [{"name": "Zomato", "alt_spellings": ["Zomato Ltd"]}],
        "sources": {"api": ["reddit", "google"]},
        "budget_usd": 25.0,
    }

    # Test /api/plan endpoint
    resp = client.post("/api/plan", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["valid_companies"] == ["Zomato"]
    assert data["invalid_companies"] == []
    assert len(data["decisions"]) >= 2

    # Check decision shape: task, candidates, rejected, summary
    for dec in data["decisions"]:
        assert "task" in dec
        assert "candidates" in dec
        assert "rejected" in dec
        assert "summary" in dec
        assert isinstance(dec["candidates"], list)
        assert isinstance(dec["rejected"], list)

    # Verify secrets are NOT leaked in response body
    assert secret_token not in resp.text
    assert "reddit_client_id_12345" not in resp.text

    # Test /api/runs/plan alias
    alias_resp = client.post("/api/runs/plan", json=payload)
    assert alias_resp.status_code == 200
    assert alias_resp.json()["valid_companies"] == ["Zomato"]


def test_run_fallback_sets_fallback_from_on_mentions(client, monkeypatch, tmp_path):
    """When a primary candidate fails and fallback candidate succeeds, fallback_from is set on mentions."""
    custom_store = RunStore(base_dir=tmp_path / "runs")
    monkeypatch.setattr("src.service.runner.run_store", custom_store)
    monkeypatch.setattr("src.service.routes.runs.run_store", custom_store)

    class MockFailingFirstReddit(BaseConnector):
        method: ClassVar[Method] = Method.api
        name: ClassVar[str] = "reddit_api"
        platforms: ClassVar[List[Platform]] = [Platform.reddit]

        def can_run(self, request: CollectionRequest) -> Tuple[bool, str]:
            return True, "OK"

        def estimate_cost(self, request: CollectionRequest) -> float:
            return 0.0

        def collect(self, request: CollectionRequest) -> Tuple[List[RawMention], CollectionAttempt]:
            now = datetime.now(timezone.utc)
            return [], CollectionAttempt(
                company=request.company,
                platform=Platform.reddit,
                method=self.method,
                status=AttemptStatus.failed,
                reason="Primary Reddit API down",
                item_count=0,
                cost_usd=0.0,
                started_at=now,
                finished_at=now,
            )

    class MockBackupReddit(BaseConnector):
        method: ClassVar[Method] = Method.api
        name: ClassVar[str] = "third_party_reddit"
        platforms: ClassVar[List[Platform]] = [Platform.reddit]

        def can_run(self, request: CollectionRequest) -> Tuple[bool, str]:
            return True, "OK"

        def estimate_cost(self, request: CollectionRequest) -> float:
            return 0.0

        def collect(self, request: CollectionRequest) -> Tuple[List[RawMention], CollectionAttempt]:
            now = datetime.now(timezone.utc)
            m = make_mention(
                company=request.company,
                platform=Platform.reddit,
                item_id="mention_backup_1",
                raw_payload={"text": "Mention from backup provider", "created_utc": "2026-03-01"},
            )
            att = CollectionAttempt(
                company=request.company,
                platform=Platform.reddit,
                method=self.method,
                status=AttemptStatus.success,
                reason="Backup provider succeeded",
                item_count=1,
                cost_usd=0.0,
                started_at=now,
                finished_at=now,
            )
            return [m], att

    from src.collection.policy import PolicyCandidate, SourcePolicy

    custom_policy = SourcePolicy(
        platforms={
            "reddit": [
                PolicyCandidate(connector="reddit_api", method="api", cost_class="free", role="first_choice", available=True),
                PolicyCandidate(connector="third_party_reddit", method="api", cost_class="paid", role="backup", available=True),
            ]
        }
    )

    test_runner = RunRunner(
        connector_classes=[MockFailingFirstReddit, MockBackupReddit],
        policy=custom_policy,
    )
    req = CreateRunRequest(
        companies=[CompanyInput(name="Zomato")],
        sources=SourcesInput(api=["reddit"]),
    )
    summary = test_runner.run("run_fb_test", req)

    # Check task outcomes recorded the fallback path
    assert len(summary["task_outcomes"]) == 1
    outcome = summary["task_outcomes"][0]
    assert outcome["fallback_path"] == ["reddit_api", "third_party_reddit"]
    assert outcome["chosen_method"] == "third_party_reddit"

    # Query GET /api/runs/{id}/mentions compact view
    resp = client.get("/api/runs/run_fb_test/mentions")
    assert resp.status_code == 200
    mentions_data = resp.json()
    assert mentions_data["total"] == 1
    first_item = mentions_data["items"][0]
    assert first_item["fallback_from"] == "api"


def test_run_with_one_invalid_company_processes_valid_ones(client, monkeypatch, tmp_path):
    """A run with one invalid company still processes the valid companies, ending with status partial."""
    custom_store = RunStore(base_dir=tmp_path / "runs")
    monkeypatch.setattr("src.service.runner.run_store", custom_store)
    monkeypatch.setattr("src.service.routes.runs.run_store", custom_store)

    test_runner = RunRunner(connector_classes=[MockSuccessConnector])

    req = CreateRunRequest(
        companies=[
            CompanyInput(name="ValidCorp"),
            CompanyInput(name="InvalidCorp", platforms=["unknown_platform_xyz"]),
        ],
        sources=SourcesInput(api=["reddit"]),
    )
    summary = test_runner.run("run_partial_invalid_test", req)

    # Run should be partial because some succeeded and one was invalid
    assert summary["status"] == "partial"
    assert summary["counts"]["mentions_count"] >= 1
    assert len(summary["invalid_companies"]) == 1
    assert summary["invalid_companies"][0]["name"] == "InvalidCorp"

    # Verify GET /api/runs/{run_id} returns invalid_companies
    resp = client.get("/api/runs/run_partial_invalid_test")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["status"] == "partial"
    assert detail["invalid_companies"] is not None
    assert detail["invalid_companies"][0]["name"] == "InvalidCorp"


def test_run_statuses_completed_partial_failed(monkeypatch, tmp_path):
    """Run statuses accurately reflect outcomes: completed (all ok), partial (some ok/some failed or invalid), failed (none ok)."""
    custom_store = RunStore(base_dir=tmp_path / "runs")
    monkeypatch.setattr("src.service.runner.run_store", custom_store)

    # 1. Completed
    runner_ok = RunRunner(connector_classes=[MockSuccessConnector])
    req_ok = CreateRunRequest(
        companies=[CompanyInput(name="Acme")],
        sources=SourcesInput(api=["reddit"]),
    )
    s_ok = runner_ok.run("run_completed", req_ok)
    assert s_ok["status"] == "completed"

    # 2. Partial (one success, one fail)
    runner_partial = RunRunner(connector_classes=[MockSuccessConnector, MockFailConnector])
    req_partial = CreateRunRequest(
        companies=[CompanyInput(name="Acme")],
        sources=SourcesInput(api=["reddit", "google"]),
    )
    s_partial = runner_partial.run("run_partial", req_partial)
    assert s_partial["status"] == "partial"

    # 3. Failed (all tasks fail)
    runner_fail = RunRunner(connector_classes=[MockFailConnector])
    req_fail = CreateRunRequest(
        companies=[CompanyInput(name="Acme")],
        sources=SourcesInput(api=["google"]),
    )
    s_fail = runner_fail.run("run_fail", req_fail)
    assert s_fail["status"] == "failed"
    assert s_fail.get("error") is not None

    # 4. Failed when no valid companies
    runner_no_valid = RunRunner(connector_classes=[MockSuccessConnector])
    req_no_valid = CreateRunRequest(
        companies=[CompanyInput(name="BadCo", platforms=["invalid_plat"])],
        sources=SourcesInput(api=["reddit"]),
    )
    s_no_valid = runner_no_valid.run("run_no_valid", req_no_valid)
    assert s_no_valid["status"] == "failed"
    assert "No valid companies" in s_no_valid.get("error", "")


def test_budget_reaches_tracker(client, monkeypatch, tmp_path):
    """Budget passed in CreateRunRequest reaches the BudgetTracker and run summary."""
    custom_store = RunStore(base_dir=tmp_path / "runs")
    monkeypatch.setattr("src.service.runner.run_store", custom_store)
    monkeypatch.setattr("src.service.routes.runs.run_store", custom_store)

    test_runner = RunRunner(connector_classes=[MockSuccessConnector])
    req = CreateRunRequest(
        companies=[CompanyInput(name="Acme")],
        sources=SourcesInput(api=["reddit"]),
        budget_usd=77.50,
    )
    summary = test_runner.run("run_budget_limit", req)
    assert summary["budget_snapshot"]["limit_usd"] == 77.50

    resp = client.get("/api/runs/run_budget_limit")
    assert resp.status_code == 200
    assert resp.json()["budget_snapshot"]["limit_usd"] == 77.50


def test_older_run_summary_loads_without_new_fields(client, monkeypatch, tmp_path):
    """Older run_summary.json without task_outcomes, decisions, or invalid_companies loads cleanly."""
    custom_store = RunStore(base_dir=tmp_path / "runs")
    monkeypatch.setattr("src.service.routes.runs.run_store", custom_store)

    # Older summary missing task_outcomes, decisions, invalid_companies
    older_summary = {
        "run_id": "older_run_123",
        "status": "completed",
        "created_at": "2026-01-01T00:00:00Z",
        "started_at": "2026-01-01T00:00:01Z",
        "finished_at": "2026-01-01T00:00:05Z",
        "companies": ["OldCompany"],
        "counts": {"mentions_count": 5, "attempts_count": 1, "cost_usd": 0.0},
        "budget_snapshot": {"limit_usd": 10.0, "total_spent_usd": 0.0},
        "progress": {},
        "per_source_results": {},
    }
    custom_store.save_run_summary("older_run_123", older_summary)

    resp = client.get("/api/runs/older_run_123")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["id"] == "older_run_123"
    assert detail["status"] == "completed"
    assert detail["task_outcomes"] is None
    assert detail["decisions"] is None
    assert detail["invalid_companies"] is None

