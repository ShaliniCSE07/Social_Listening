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

