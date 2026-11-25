"""Tests for the user-chosen platform filter (parsing, plan pruning, datasets, runs)."""
import csv
from datetime import datetime, timezone
from typing import ClassVar, List, Tuple

import pytest

from src.collection.base import BaseConnector, CollectionRequest
from src.collection.planner import Plan, Task
from src.collection.platform_filter import parse_platform_filter, prune_plan_tasks, resolve_platform
from src.collection.plugins.dataset.catalogue import DatasetEntry
from src.collection.plugins.dataset.connector import DatasetConnector
from src.contracts.enums import AttemptStatus, Method, Platform
from src.contracts.schemas import CollectionAttempt, RawMention
from src.service.models import CompanyInput, CreateRunRequest, SourcesInput
from src.service.run_store import RunStore
from src.service.runner import RunRunner


# ── parsing ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "text, expected",
    [
        ("Instagram", Platform.instagram), ("insta", Platform.instagram),
        ("FB", Platform.facebook), ("Linked In", Platform.linkedin), ("linked-in", Platform.linkedin),
        ("X", Platform.twitter_x), ("Trip Advisor", Platform.tripadvisor), ("google", Platform.google),
        ("play store", None),
    ],
)
def test_resolve_platform(text, expected):
    assert resolve_platform(text) == expected


def test_empty_filter_allows_everything():
    for value in (None, [], ["", "  "]):
        pf = parse_platform_filter(value)
        assert not pf.active
        assert pf.allows_platform(Platform.reddit)
        assert pf.allows_mention(Platform.other, "anything")


def test_parse_splits_commas_dedupes_and_keeps_free_text():
    pf = parse_platform_filter(["insta, Instagram", "Google", "Play Store"])
    assert pf.platforms == {Platform.instagram, Platform.google}
    assert pf.free_text == {"play store"}
    assert pf.requested == ["insta", "Google", "Play Store"]  # "Instagram" duplicates "insta"


def test_allows_mention_rules():
    pf = parse_platform_filter(["google", "play store"])
    assert pf.allows_mention(Platform.google)
    assert not pf.allows_mention(Platform.reddit, "reddit.com/r/food")
    assert pf.allows_mention(Platform.other, "Zomato Play Store Reviews")  # free text in source name
    assert pf.allows_mention(Platform.other, "Google")  # row-level label resolving to google
    assert not pf.allows_mention(Platform.other, "Instagram")


# ── plan pruning ─────────────────────────────────────────────────────────

def _entry(key, platform="other", columns=None, name="Some Dataset", path="x.csv"):
    return DatasetEntry(
        key=key, name=name, source_type="local", path_or_ref=str(path), format="csv",
        platform=platform, content_type="review",
        columns=columns or {"text": "text", "company": "brand"},
    )


def test_prune_plan_tasks():
    plan = Plan(tasks=[
        Task(company="Acme", platform=Platform.tripadvisor),
        Task(company="Acme", platform=Platform.reddit),
        Task(company="Acme", platform="dataset", dataset_key="ds_other"),
        Task(company="Acme", platform="dataset", dataset_key="ds_rowlevel"),
        Task(company="Acme", platform="dataset", dataset_key="ds_playstore"),
    ])
    catalogue = {
        "ds_other": _entry("ds_other"),
        "ds_rowlevel": _entry("ds_rowlevel", columns={"text": "t", "platform": "source"}),
        "ds_playstore": _entry("ds_playstore", name="Zomato Play Store Reviews"),
    }
    removed = prune_plan_tasks(plan, parse_platform_filter(["TripAdvisor", "play store"]), catalogue)

    kept = {(str(getattr(t.platform, "value", t.platform)), t.dataset_key) for t in plan.tasks}
    assert kept == {("tripadvisor", None), ("dataset", "ds_rowlevel"), ("dataset", "ds_playstore")}
    reasons = [r for _, r in removed]
    assert len(reasons) == 2
    assert any("reddit" in r and "not in platform filter" in r for r in reasons)
    assert any("ds_other" in r for r in reasons)


def test_prune_does_nothing_without_filter():
    plan = Plan(tasks=[Task(company="Acme", platform=Platform.reddit)])
    assert prune_plan_tasks(plan, parse_platform_filter(None)) == []
    assert len(plan.tasks) == 1


# ── dataset rows ─────────────────────────────────────────────────────────

def test_dataset_filters_rows_by_platform_column(tmp_path):
    path = tmp_path / "multi.csv"
    rows = [
        {"id": "1", "brand": "Acme", "text": "Love it", "source": "Instagram"},
        {"id": "2", "brand": "Acme", "text": "Meh", "source": "Facebook"},
        {"id": "3", "brand": "Acme", "text": "Nice", "source": "insta"},
        {"id": "4", "brand": "Acme", "text": "Ok", "source": "Google"},
    ]
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "brand", "text", "source"])
        w.writeheader()
        w.writerows(rows)
    entry = _entry("multi", path=path, columns={"text": "text", "id": "id", "company": "brand", "platform": "source"})
    conn = DatasetConnector(catalogue={"multi": entry})

    mentions, attempt = conn.collect(CollectionRequest(company="Acme", platform_filter=["instagram"]))
    assert {m.item_id for m in mentions} == {"1", "3"}
    assert all(m.platform == Platform.instagram for m in mentions)  # row platform becomes mention platform
    assert mentions[0].raw_payload["platform_mapped"] in ("Instagram", "insta")
    assert "2 rows skipped by platform filter (instagram)" in attempt.reason

    # No filter → every row, platform still taken from the row
    mentions_all, _ = conn.collect(CollectionRequest(company="Acme"))
    assert len(mentions_all) == 4
    assert {m.platform for m in mentions_all} == {Platform.instagram, Platform.facebook, Platform.google}


# ── whole run ────────────────────────────────────────────────────────────

def _mock(platform: Platform, name: str):
    class _Conn(BaseConnector):
        method: ClassVar[Method] = Method.api
        platforms: ClassVar[List[Platform]] = [platform]
        calls: ClassVar[int] = 0

        def can_run(self, request: CollectionRequest) -> Tuple[bool, str]:
            return True, "OK"

        def estimate_cost(self, request: CollectionRequest) -> float:
            return 0.0

        def collect(self, request: CollectionRequest):
            type(self).calls += 1
            now = datetime.now(timezone.utc)
            m = RawMention(
                company=request.company, run_id=request.run_id, platform=platform, item_id=f"{name}1",
                raw_payload={"text": "hi", "rating": 5}, source=name, method_used=Method.api,
                tool_used=name, collected_at=now,
            )
            att = CollectionAttempt(
                company=request.company, platform=platform, method=Method.api,
                status=AttemptStatus.success, item_count=1, started_at=now, finished_at=now,
            )
            return [m], att

    _Conn.name = name
    return _Conn


def test_run_skips_sources_outside_filter_without_calling_them(monkeypatch, tmp_path):
    monkeypatch.setattr("src.service.runner.run_store", RunStore(base_dir=tmp_path / "runs"))
    Reddit, TripAdvisor = _mock(Platform.reddit, "mock_reddit"), _mock(Platform.tripadvisor, "mock_ta")
    runner = RunRunner(connector_classes=[Reddit, TripAdvisor])

    req = CreateRunRequest(
        companies=[CompanyInput(name="Acme")],
        sources=SourcesInput(api=["reddit", "tripadvisor"]),
        platform_filter=["Trip Advisor"],
    )
    summary = runner.run("run_pf", req)

    assert Reddit.calls == 0 and TripAdvisor.calls == 1
    assert summary["status"] == "completed"
    assert summary["counts"]["mentions_count"] == 1
    assert summary["platform_filter"]["platforms"] == ["tripadvisor"]
    assert any("reddit" in s for s in summary["platform_filter"]["skipped_sources"])


def test_run_with_only_unavailable_platform_fails_clearly(monkeypatch, tmp_path):
    monkeypatch.setattr("src.service.runner.run_store", RunStore(base_dir=tmp_path / "runs"))
    Reddit = _mock(Platform.reddit, "mock_reddit2")
    runner = RunRunner(connector_classes=[Reddit])

    req = CreateRunRequest(
        companies=[CompanyInput(name="Acme")],
        sources=SourcesInput(api=["reddit"]),
        platform_filter=["instagram"],
    )
    summary = runner.run("run_pf_none", req)

    assert Reddit.calls == 0
    assert summary["status"] == "failed"
    assert "None of the selected sources collect from: instagram" in summary["error"]
