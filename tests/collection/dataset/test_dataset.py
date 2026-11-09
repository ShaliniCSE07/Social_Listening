"""Tests for Dataset plugin connector and local file sources."""
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import pytest

from src.collection.base import CollectionRequest
from src.collection.plugins.dataset.catalogue import DatasetEntry
from src.collection.plugins.dataset.connector import DatasetConnector
from src.collection.plugins.dataset.sources.local import LocalFileSource
from src.contracts.enums import AttemptStatus, ContentType, Method, Platform

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"


@pytest.fixture
def sample_csv_file(tmp_path) -> Path:
    csv_path = tmp_path / "sample.csv"
    rows = [
        {"rev_id": "c1", "brand": "Zomato", "content": "Great food via Zomato!", "created_at": "2021-05-01", "rating": "5"},
        {"rev_id": "c2", "brand": "Swiggy", "content": "Fast delivery by Swiggy", "created_at": "2023-08-10", "rating": "4"},
        {"rev_id": "c3", "brand": "Zomato", "content": "Zomato order arrived late", "created_at": "2026-02-15", "rating": "2"},
    ]
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["rev_id", "brand", "content", "created_at", "rating"])
        writer.writeheader()
        writer.writerows(rows)
    return csv_path


@pytest.fixture
def sample_jsonl_file(tmp_path) -> Path:
    jsonl_path = tmp_path / "sample.jsonl"
    rows = [
        {"post_id": "j1", "text": "Talking about Zomato services", "date": "2020-01-10", "author": "alice"},
        {"post_id": "j2", "text": "Unrelated post about sports", "date": "2022-06-15", "author": "bob"},
        {"post_id": "j3", "text": "Zomato discounts are awesome", "date": "2025-11-20", "author": "carol"},
    ]
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return jsonl_path


@pytest.fixture
def sample_json_file(tmp_path) -> Path:
    json_path = tmp_path / "sample.json"
    rows = [
        {"id": "js1", "review": "Zomato review in JSON", "pub_date": "2019-12-01"},
        {"id": "js2", "review": "Other brand review", "pub_date": "2024-04-01"},
    ]
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(rows, f)
    return json_path


def test_old_rows_kept_when_no_date_filter(sample_csv_file):
    entry = DatasetEntry(
        key="test_csv",
        name="Test CSV Dataset",
        source_type="local",
        path_or_ref=str(sample_csv_file),
        format="csv",
        platform="other",
        content_type="review",
        enabled=True,
        columns={"text": "content", "id": "rev_id", "company": "brand", "date": "created_at"},
    )
    connector = DatasetConnector(catalogue={"test_csv": entry})
    request = CollectionRequest(company="Zomato")

    mentions, attempt = connector.collect(request)

    # 2 rows for Zomato: 2021-05-01 and 2026-02-15
    assert len(mentions) == 2
    assert attempt.status == AttemptStatus.success
    item_ids = {m.item_id for m in mentions}
    assert item_ids == {"c1", "c3"}

    # Verify dates remain untouched in raw_payload
    p1 = next(m for m in mentions if m.item_id == "c1")
    assert p1.raw_payload["created_at"] == "2021-05-01"


def test_date_filter_works_when_given(sample_csv_file):
    entry = DatasetEntry(
        key="test_csv",
        name="Test CSV Dataset",
        source_type="local",
        path_or_ref=str(sample_csv_file),
        format="csv",
        platform="other",
        content_type="review",
        enabled=True,
        columns={"text": "content", "id": "rev_id", "company": "brand", "date": "created_at"},
    )
    connector = DatasetConnector(catalogue={"test_csv": entry})
    # Date from 2025 onwards should keep only the 2026 row
    date_from = datetime(2025, 1, 1, tzinfo=timezone.utc)
    request = CollectionRequest(company="Zomato", date_from=date_from)

    mentions, attempt = connector.collect(request)

    assert len(mentions) == 1
    assert mentions[0].item_id == "c3"


def test_company_filter_uses_company_column(sample_csv_file):
    entry = DatasetEntry(
        key="test_csv",
        name="Test CSV Dataset",
        source_type="local",
        path_or_ref=str(sample_csv_file),
        format="csv",
        platform="other",
        content_type="review",
        enabled=True,
        columns={"text": "content", "id": "rev_id", "company": "brand", "date": "created_at"},
    )
    connector = DatasetConnector(catalogue={"test_csv": entry})
    request = CollectionRequest(company="Swiggy")

    mentions, attempt = connector.collect(request)

    assert len(mentions) == 1
    assert mentions[0].item_id == "c2"
    assert mentions[0].raw_payload["brand"] == "Swiggy"


def test_mapping_works_and_extra_keys_in_raw_payload(sample_jsonl_file):
    entry = DatasetEntry(
        key="test_jsonl",
        name="Test JSONL Dataset",
        source_type="local",
        path_or_ref=str(sample_jsonl_file),
        format="jsonl",
        platform="twitter_x",
        content_type="post",
        enabled=True,
        columns={"text": "text", "id": "post_id", "date": "date"},
    )
    connector = DatasetConnector(catalogue={"test_jsonl": entry})
    request = CollectionRequest(company="Zomato")

    mentions, attempt = connector.collect(request)

    assert len(mentions) == 2
    first = mentions[0]
    assert first.platform == Platform.twitter_x
    assert first.method_used == Method.dataset
    assert first.tool_used == "Dataset: Test JSONL Dataset"
    assert first.source == "Test JSONL Dataset"
    assert first.cost_usd == 0.0

    # Extra keys inside raw_payload only
    assert "dataset_key" in first.raw_payload
    assert first.raw_payload["dataset_key"] == "test_jsonl"
    assert "dataset_last_updated" in first.raw_payload
    assert "dataset_row_number" in first.raw_payload
    assert first.raw_payload["dataset_row_number"] == 1


def test_missing_column_gives_failed(sample_csv_file):
    entry = DatasetEntry(
        key="bad_mapping",
        name="Bad Mapping Dataset",
        source_type="local",
        path_or_ref=str(sample_csv_file),
        format="csv",
        platform="other",
        content_type="review",
        enabled=True,
        columns={"text": "non_existent_text_column"},
    )
    connector = DatasetConnector(catalogue={"bad_mapping": entry})
    request = CollectionRequest(company="Zomato")

    mentions, attempt = connector.collect(request)

    assert len(mentions) == 0
    assert attempt.status == AttemptStatus.failed
    assert "not found" in attempt.reason.lower()


def test_stale_dataset_skipped_only_when_require_fresh(sample_csv_file):
    # Set last updated override to 100 days ago
    entry = DatasetEntry(
        key="stale_ds",
        name="Stale Dataset",
        source_type="local",
        path_or_ref=str(sample_csv_file),
        format="csv",
        platform="other",
        content_type="review",
        enabled=True,
        columns={"text": "content", "id": "rev_id", "company": "brand"},
        last_updated_override="2024-01-01T00:00:00Z",
    )
    connector = DatasetConnector(catalogue={"stale_ds": entry})

    # Case 1: require_fresh=False -> not skipped, collected
    req_not_fresh = CollectionRequest(company="Zomato", max_age_days=30, require_fresh=False)
    m1, a1 = connector.collect(req_not_fresh)
    assert len(m1) == 2
    assert a1.status == AttemptStatus.success

    # Case 2: require_fresh=True -> skipped with reason
    req_fresh = CollectionRequest(company="Zomato", max_age_days=30, require_fresh=True)
    m2, a2 = connector.collect(req_fresh)
    assert len(m2) == 0
    assert a2.status == AttemptStatus.skipped
    assert "older than 30" in a2.reason.lower()


def test_item_id_null_when_no_id_column(sample_json_file):
    entry = DatasetEntry(
        key="no_id_ds",
        name="No ID Dataset",
        source_type="local",
        path_or_ref=str(sample_json_file),
        format="json",
        platform="other",
        content_type="review",
        enabled=True,
        columns={"text": "review"},  # No 'id' column mapped
    )
    connector = DatasetConnector(catalogue={"no_id_ds": entry})
    request = CollectionRequest(company="Zomato")

    mentions, attempt = connector.collect(request)

    assert len(mentions) == 1
    assert mentions[0].item_id is None


def test_large_file_streams_without_loading_fully(tmp_path):
    """Verify that LocalFileSource streams rows through an iterator without loading all."""
    large_csv = tmp_path / "large.csv"
    with open(large_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "content"])
        for i in range(100):
            writer.writerow([f"row_{i}", f"Zomato review number {i}"])

    source = LocalFileSource("Large DS", large_csv, "csv")
    row_iter = source.iter_rows()

    # Verify row_iter is a generator/iterator
    assert hasattr(row_iter, "__iter__")
    assert hasattr(row_iter, "__next__")

    # Fetch first row without exhausting
    first_row = next(row_iter)
    assert first_row["id"] == "row_0"
    second_row = next(row_iter)
    assert second_row["id"] == "row_1"



# ---------------------------------------------------------------------------
# Tests for naive / aware datetime handling, per-row errors, and warnings
# ---------------------------------------------------------------------------

@pytest.fixture
def aware_dates_csv(tmp_path) -> Path:
    """CSV whose date column has timezone-aware ISO strings (e.g. …+05:30, …Z)."""
    csv_path = tmp_path / "aware.csv"
    rows = [
        {"id": "a1", "brand": "Zomato", "text": "Good food", "dt": "2026-10-30T18:05:00Z"},
        {"id": "a2", "brand": "Zomato", "text": "Late delivery", "dt": "2026-11-02T10:00:00+05:30"},
        {"id": "a3", "brand": "Zomato", "text": "Old review", "dt": "2024-01-15T00:00:00Z"},
    ]
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "brand", "text", "dt"])
        writer.writeheader()
        writer.writerows(rows)
    return csv_path


@pytest.fixture
def naive_dates_csv(tmp_path) -> Path:
    """CSV whose date column has naive (no tz) ISO strings."""
    csv_path = tmp_path / "naive.csv"
    rows = [
        {"id": "n1", "brand": "Zomato", "text": "Nice app", "dt": "2026-10-30 18:05:00"},
        {"id": "n2", "brand": "Zomato", "text": "Crash issues", "dt": "2024-06-01"},
    ]
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "brand", "text", "dt"])
        writer.writeheader()
        writer.writerows(rows)
    return csv_path


def _make_entry(csv_path, key="test_ds"):
    return DatasetEntry(
        key=key,
        name="Test Dataset",
        source_type="local",
        path_or_ref=str(csv_path),
        format="csv",
        platform="other",
        content_type="review",
        enabled=True,
        columns={"text": "text", "id": "id", "company": "brand", "date": "dt"},
    )


def test_aware_row_dates_with_naive_date_from(aware_dates_csv):
    """Aware row dates compared against a naive date_from must not crash."""
    entry = _make_entry(aware_dates_csv)
    connector = DatasetConnector(catalogue={"test_ds": entry})
    # Naive date_from (no tzinfo) — should be treated as UTC by to_utc
    date_from = datetime(2026, 10, 1)
    request = CollectionRequest(company="Zomato", date_from=date_from)

    mentions, attempt = connector.collect(request)

    assert attempt.status == AttemptStatus.success
    # a1 (Oct 30) and a2 (Nov 2) match; a3 (Jan 2024) is before the filter
    ids = {m.item_id for m in mentions}
    assert ids == {"a1", "a2"}


def test_naive_row_dates_with_aware_date_from(naive_dates_csv):
    """Naive row dates compared against an aware date_from must not crash."""
    entry = _make_entry(naive_dates_csv)
    connector = DatasetConnector(catalogue={"test_ds": entry})
    date_from = datetime(2025, 1, 1, tzinfo=timezone.utc)
    request = CollectionRequest(company="Zomato", date_from=date_from)

    mentions, attempt = connector.collect(request)

    # Only n1 (2026-10-30) should pass the filter
    assert len(mentions) == 1
    assert mentions[0].item_id == "n1"


def test_no_filter_keeps_all_rows_no_date_parse_warning(naive_dates_csv):
    """With no date filter, all matching rows are kept and no date_parse_warning exists."""
    entry = _make_entry(naive_dates_csv)
    connector = DatasetConnector(catalogue={"test_ds": entry})
    request = CollectionRequest(company="Zomato")

    mentions, attempt = connector.collect(request)

    assert len(mentions) == 2
    for m in mentions:
        assert "date_parse_warning" not in m.raw_payload


def test_unparseable_date_with_filter_keeps_row_with_warning(tmp_path):
    """If a filter is set and a row's date cannot be parsed, keep the row with a warning."""
    csv_path = tmp_path / "baddate.csv"
    rows = [
        {"id": "u1", "brand": "Zomato", "text": "Good", "dt": "not-a-date"},
        {"id": "u2", "brand": "Zomato", "text": "Also good", "dt": "2026-06-15"},
    ]
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "brand", "text", "dt"])
        writer.writeheader()
        writer.writerows(rows)

    entry = _make_entry(csv_path)
    connector = DatasetConnector(catalogue={"test_ds": entry})
    date_from = datetime(2020, 1, 1, tzinfo=timezone.utc)
    request = CollectionRequest(company="Zomato", date_from=date_from)

    mentions, attempt = connector.collect(request)

    # Both rows kept: u1 (unparseable → kept with warning), u2 (2026 passes filter)
    assert len(mentions) == 2
    ids = {m.item_id for m in mentions}
    assert ids == {"u1", "u2"}

    # The unparseable row should have the warning flag
    bad_mention = next(m for m in mentions if m.item_id == "u1")
    assert bad_mention.raw_payload.get("date_parse_warning") is True

    # The good row should NOT have the warning
    good_mention = next(m for m in mentions if m.item_id == "u2")
    assert "date_parse_warning" not in good_mention.raw_payload

    # Attempt reason should mention the count
    assert "1 rows had unreadable dates" in attempt.reason


def test_one_bad_row_does_not_stop_others(tmp_path):
    """A row-level error in one row must not prevent processing the rest."""
    csv_path = tmp_path / "mixed.csv"
    # Write a CSV where the company column has a value that will match,
    # but we inject a row error by using a broken column mapping for one entry
    rows = [
        {"id": "r1", "brand": "Zomato", "text": "Good stuff", "dt": "2026-01-01"},
        {"id": "r2", "brand": "Zomato", "text": "More stuff", "dt": "2026-02-01"},
        {"id": "r3", "brand": "Zomato", "text": "Even more", "dt": "2026-03-01"},
    ]
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "brand", "text", "dt"])
        writer.writeheader()
        writer.writerows(rows)

    entry = _make_entry(csv_path)
    connector = DatasetConnector(catalogue={"test_ds": entry})
    request = CollectionRequest(company="Zomato")

    mentions, attempt = connector.collect(request)

    # All 3 rows for Zomato should be collected
    assert len(mentions) == 3
    assert attempt.status == AttemptStatus.success


def test_last_updated_freshness_naive_vs_aware(tmp_path):
    """Freshness check with to_utc works when last_updated_override is naive or aware."""
    csv_path = tmp_path / "fresh.csv"
    rows = [{"id": "f1", "brand": "Zomato", "text": "Fresh review", "dt": "2026-01-01"}]
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "brand", "text", "dt"])
        writer.writeheader()
        writer.writerows(rows)

    # Case 1: Naive override string (no timezone) — old date → should be skipped
    entry_naive = DatasetEntry(
        key="fresh_ds",
        name="Fresh Dataset",
        source_type="local",
        path_or_ref=str(csv_path),
        format="csv",
        platform="other",
        content_type="review",
        enabled=True,
        columns={"text": "text", "id": "id", "company": "brand"},
        last_updated_override="2020-01-01T00:00:00",  # naive string
    )
    connector1 = DatasetConnector(catalogue={"fresh_ds": entry_naive})
    req_fresh = CollectionRequest(company="Zomato", max_age_days=30, require_fresh=True)
    m1, a1 = connector1.collect(req_fresh)
    assert a1.status == AttemptStatus.skipped
    assert "older than" in a1.reason.lower()

    # Case 2: Aware override string (with timezone) — old date → should be skipped
    entry_aware = DatasetEntry(
        key="fresh_ds",
        name="Fresh Dataset",
        source_type="local",
        path_or_ref=str(csv_path),
        format="csv",
        platform="other",
        content_type="review",
        enabled=True,
        columns={"text": "text", "id": "id", "company": "brand"},
        last_updated_override="2020-01-01T00:00:00+05:30",  # aware string
    )
    connector2 = DatasetConnector(catalogue={"fresh_ds": entry_aware})
    m2, a2 = connector2.collect(req_fresh)
    assert a2.status == AttemptStatus.skipped
    assert "older than" in a2.reason.lower()
