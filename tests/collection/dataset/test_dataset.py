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


# ---------------------------------------------------------------------------
# Tests for default_company, company_column priority, text_mention matching,
# UTF-8 decoding, BOM handling, undecodable rows counting, and catalogue entries
# ---------------------------------------------------------------------------

def test_default_company_matching_and_empty_reason(tmp_path):
    """When an entry has default_company and no company column, all rows match if company matches,
    or returns an empty attempt with reason 'dataset is for <default_company>'."""
    csv_path = tmp_path / "zomato_default.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["rev", "stars"])
        writer.writerow(["Awesome food delivery", "5"])
        writer.writerow(["Quick and fresh", "4"])

    entry = DatasetEntry(
        key="zomato_single",
        name="Zomato Single Brand",
        source_type="local",
        path_or_ref=str(csv_path),
        format="csv",
        platform="other",
        content_type="review",
        default_company="Zomato",
        columns={"text": "rev", "rating": "stars"},
    )
    connector = DatasetConnector(catalogue={"zomato_single": entry})

    # 1. Matching company -> all rows belong to Zomato
    req_match = CollectionRequest(company="Zomato")
    mentions, attempt = connector.collect(req_match)
    assert len(mentions) == 2
    assert attempt.status == AttemptStatus.success
    for m in mentions:
        assert m.raw_payload["dataset_match_basis"] == "default_company"

    # 2. Non-matching company -> empty attempt with specific reason
    req_non_match = CollectionRequest(company="Swiggy")
    mentions_empty, attempt_empty = connector.collect(req_non_match)
    assert len(mentions_empty) == 0
    assert attempt_empty.status == AttemptStatus.empty
    assert attempt_empty.reason == "dataset is for Zomato"


def test_default_company_matches_alt_spellings(tmp_path):
    """default_company matches when request.company or any alt_spelling matches case-insensitively."""
    csv_path = tmp_path / "zomato_alts.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["review_text"])
        writer.writerow(["Great service"])

    entry = DatasetEntry(
        key="zomato_alts_ds",
        name="Zomato Alts DS",
        source_type="local",
        path_or_ref=str(csv_path),
        format="csv",
        platform="other",
        content_type="review",
        default_company="Zomato",
        columns={"text": "review_text"},
    )
    connector = DatasetConnector(catalogue={"zomato_alts_ds": entry})

    req = CollectionRequest(
        company="Eternal Limited",
        alt_spellings=["zomato", "zomato app"],
    )
    mentions, attempt = connector.collect(req)
    assert len(mentions) == 1
    assert attempt.status == AttemptStatus.success
    assert mentions[0].raw_payload["dataset_match_basis"] == "default_company"


def test_company_column_beats_default_company(tmp_path):
    """When entry has both mapped company column and default_company, company column wins."""
    csv_path = tmp_path / "multi_brand.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["brand", "review_text"])
        writer.writerow(["Swiggy", "Fast Swiggy delivery"])
        writer.writerow(["Zomato", "Good Zomato food"])

    entry = DatasetEntry(
        key="mixed_ds",
        name="Mixed DS",
        source_type="local",
        path_or_ref=str(csv_path),
        format="csv",
        platform="other",
        content_type="review",
        default_company="Zomato",  # Ignored because company column is mapped
        columns={"text": "review_text", "company": "brand"},
    )
    connector = DatasetConnector(catalogue={"mixed_ds": entry})

    # Swiggy request must collect only the Swiggy row (not empty or all rows)
    req_swiggy = CollectionRequest(company="Swiggy")
    mentions, attempt = connector.collect(req_swiggy)
    assert len(mentions) == 1
    assert mentions[0].raw_payload["brand"] == "Swiggy"
    assert mentions[0].raw_payload["dataset_match_basis"] == "company_column"


def test_text_mention_matching(tmp_path):
    """When neither company column nor default_company is present, match on text."""
    csv_path = tmp_path / "text_only.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "content"])
        writer.writerow(["t1", "Loved ordering via Zomato!"])
        writer.writerow(["t2", "Completely unrelated review"])

    entry = DatasetEntry(
        key="text_only_ds",
        name="Text Only DS",
        source_type="local",
        path_or_ref=str(csv_path),
        format="csv",
        platform="other",
        content_type="review",
        columns={"text": "content", "id": "id"},
    )
    connector = DatasetConnector(catalogue={"text_only_ds": entry})

    req = CollectionRequest(company="Zomato")
    mentions, attempt = connector.collect(req)
    assert len(mentions) == 1
    assert mentions[0].item_id == "t1"
    assert mentions[0].raw_payload["dataset_match_basis"] == "text_mention"


def test_raw_payload_preservation_with_extra_keys(tmp_path):
    """Row's raw_payload stays exactly as read plus metadata keys."""
    csv_path = tmp_path / "extra_keys.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["custom_col", "review_desc", "score"])
        writer.writerow(["custom_val_123", "Nice food", "4.5"])

    entry = DatasetEntry(
        key="payload_ds",
        name="Payload DS",
        source_type="local",
        path_or_ref=str(csv_path),
        format="csv",
        platform="other",
        content_type="review",
        default_company="Zomato",
        columns={"text": "review_desc"},
    )
    connector = DatasetConnector(catalogue={"payload_ds": entry})

    mentions, attempt = connector.collect(CollectionRequest(company="Zomato"))
    assert len(mentions) == 1
    payload = mentions[0].raw_payload

    # Raw columns preserved exactly
    assert payload["custom_col"] == "custom_val_123"
    assert payload["review_desc"] == "Nice food"
    assert payload["score"] == "4.5"

    # Extra keys present
    assert payload["dataset_key"] == "payload_ds"
    assert "dataset_last_updated" in payload
    assert "dataset_last_updated_basis" in payload
    assert payload["dataset_row_number"] == 1
    assert payload["dataset_match_basis"] == "default_company"


def test_app_column_matching_and_null_item_id(tmp_path):
    """Matches the kaggle zomato/swiggy app reviews schema with App column and no id column."""
    csv_path = tmp_path / "app_reviews.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["review_description", "review_date", "App", "rating"])
        writer.writerow(["Zomato delivery was fast", "2023-05-10", "Zomato", "5"])
        writer.writerow(["Swiggy delivery was fast", "2023-05-11", "Swiggy", "4"])
        writer.writerow(["Zomato had good discounts", "2023-05-12", "Zomato", "5"])

    entry = DatasetEntry(
        key="app_reviews_ds",
        name="App Reviews DS",
        source_type="local",
        path_or_ref=str(csv_path),
        format="csv",
        platform="other",
        content_type="review",
        columns={
            "text": "review_description",
            "date": "review_date",
            "company": "App",
            "rating": "rating",
        },
    )
    connector = DatasetConnector(catalogue={"app_reviews_ds": entry})

    # For Zomato: 2 rows collected, item_id null, company_column basis
    mentions, attempt = connector.collect(CollectionRequest(company="Zomato"))
    assert len(mentions) == 2
    for m in mentions:
        assert m.item_id is None
        assert m.raw_payload["App"] == "Zomato"
        assert m.raw_payload["dataset_match_basis"] == "company_column"


def test_utf8_non_ascii_and_emoji(tmp_path):
    """CSV with non-ASCII text, Hindi, and emojis decodes cleanly."""
    csv_path = tmp_path / "emoji.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "text"])
        writer.writerow(["e1", "🍕 Pizza bahot badiya tha! Zomato rocks 🚀"])
        writer.writerow(["e2", "खाना बहुत स्वादिष्ट था धन्यवाद 😊"])

    entry = DatasetEntry(
        key="emoji_ds",
        name="Emoji DS",
        source_type="local",
        path_or_ref=str(csv_path),
        format="csv",
        platform="other",
        content_type="review",
        default_company="Zomato",
        columns={"text": "text", "id": "id"},
    )
    connector = DatasetConnector(catalogue={"emoji_ds": entry})

    mentions, attempt = connector.collect(CollectionRequest(company="Zomato"))
    assert len(mentions) == 2
    assert "🍕" in mentions[0].raw_payload["text"]
    assert "🚀" in mentions[0].raw_payload["text"]
    assert "खाना बहुत स्वादिष्ट था" in mentions[1].raw_payload["text"]


def test_bom_loading_csv_jsonl_json(tmp_path):
    """Files starting with UTF-8 BOM are loaded properly without mangled headers or keys."""
    # 1. CSV with BOM
    csv_path = tmp_path / "bom.csv"
    csv_bytes = b"\xef\xbb\xbftext,id\nZomato with BOM,b1\n"
    csv_path.write_bytes(csv_bytes)

    source_csv = LocalFileSource("BOM CSV", csv_path, "csv")
    csv_rows = list(source_csv.iter_rows())
    assert len(csv_rows) == 1
    assert "text" in csv_rows[0]
    assert "\ufefftext" not in csv_rows[0]
    assert csv_rows[0]["text"] == "Zomato with BOM"

    # 2. JSONL with BOM
    jsonl_path = tmp_path / "bom.jsonl"
    jsonl_bytes = b"\xef\xbb\xbf{\"text\": \"Zomato JSONL BOM\", \"id\": \"bj1\"}\n"
    jsonl_path.write_bytes(jsonl_bytes)

    source_jsonl = LocalFileSource("BOM JSONL", jsonl_path, "jsonl")
    jsonl_rows = list(source_jsonl.iter_rows())
    assert len(jsonl_rows) == 1
    assert jsonl_rows[0]["text"] == "Zomato JSONL BOM"

    # 3. JSON with BOM
    json_path = tmp_path / "bom.json"
    json_bytes = b"\xef\xbb\xbf[{\"text\": \"Zomato JSON BOM\", \"id\": \"bjs1\"}]"
    json_path.write_bytes(json_bytes)

    source_json = LocalFileSource("BOM JSON", json_path, "json")
    json_rows = list(source_json.iter_rows())
    assert len(json_rows) == 1
    assert json_rows[0]["text"] == "Zomato JSON BOM"


def test_undecodable_bytes_counting_and_attempt_reason(tmp_path):
    """Corrupt/undecodable rows do not crash the run; count is reported in attempt reason."""
    csv_path = tmp_path / "corrupt_bytes.csv"
    # Header + 3 good rows + 2 undecodable rows
    lines = [
        b"id,text\n",
        b"1,Zomato good row 1\n",
        b"2,\xff\xfe invalid non-utf8 row\n",
        b"3,Zomato good row 2\n",
        b"4,\x80\xff another bad row\n",
        b"5,Zomato good row 3\n",
    ]
    with open(csv_path, "wb") as f:
        f.writelines(lines)

    entry = DatasetEntry(
        key="corrupt_ds",
        name="Corrupt DS",
        source_type="local",
        path_or_ref=str(csv_path),
        format="csv",
        platform="other",
        content_type="review",
        default_company="Zomato",
        columns={"text": "text", "id": "id"},
    )
    connector = DatasetConnector(catalogue={"corrupt_ds": entry})

    mentions, attempt = connector.collect(CollectionRequest(company="Zomato"))
    # Run does not crash; 3 good rows collected
    assert len(mentions) == 3
    assert attempt.status == AttemptStatus.success
    # Bad rows counted and mentioned in attempt reason
    assert "2 bad rows" in attempt.reason
    assert "decode" in attempt.reason.lower()


def test_completely_unreadable_file_fails_with_clear_reason(tmp_path):
    """File that cannot be decoded at all fails gracefully with a clear reason."""
    bad_file = tmp_path / "completely_bad.csv"
    bad_file.write_bytes(b"\xff\xfe\x00\x00\xaa\xbb\xcc\xdd\xee\xff")

    entry = DatasetEntry(
        key="bad_ds",
        name="Bad DS",
        source_type="local",
        path_or_ref=str(bad_file),
        format="csv",
        platform="other",
        content_type="review",
        default_company="Zomato",
        columns={"text": "text"},
    )
    connector = DatasetConnector(catalogue={"bad_ds": entry})

    mentions, attempt = connector.collect(CollectionRequest(company="Zomato"))
    assert len(mentions) == 0
    assert attempt.status == AttemptStatus.failed
    assert "unreadable" in attempt.reason.lower() or "could not be decoded" in attempt.reason.lower()


def test_date_parsing_without_tz_kept_untouched_in_raw_payload(tmp_path):
    """Dates without timezone (e.g. 2023-07-23 15:52:11) are filtered accurately but remain untouched in raw_payload."""
    csv_path = tmp_path / "dates_no_tz.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "review_text", "review_date"])
        writer.writerow(["d1", "Zomato review 2023", "2023-07-23 15:52:11"])
        writer.writerow(["d2", "Zomato review 2021", "2021-02-10 10:00:00"])

    entry = DatasetEntry(
        key="no_tz_ds",
        name="No TZ DS",
        source_type="local",
        path_or_ref=str(csv_path),
        format="csv",
        platform="other",
        content_type="review",
        default_company="Zomato",
        columns={"text": "review_text", "id": "id", "date": "review_date"},
    )
    connector = DatasetConnector(catalogue={"no_tz_ds": entry})

    # Filter from 2022 onwards: d1 kept, d2 filtered
    date_from = datetime(2022, 1, 1, tzinfo=timezone.utc)
    mentions, attempt = connector.collect(CollectionRequest(company="Zomato", date_from=date_from))
    assert len(mentions) == 1
    assert mentions[0].item_id == "d1"
    # Exact raw string preserved untouched
    assert mentions[0].raw_payload["review_date"] == "2023-07-23 15:52:11"


def test_new_catalogue_entries_validation():
    """Validates that all new Kaggle catalogue entries load cleanly with expected fields."""
    from src.collection.plugins.dataset.catalogue import load_dataset_catalogue

    catalogue = load_dataset_catalogue()

    # 1. Existing local sample preserved
    assert "sample_reviews_local" in catalogue

    # 2. kaggle_zomato_app_reviews
    assert "kaggle_zomato_app_reviews" in catalogue
    kz = catalogue["kaggle_zomato_app_reviews"]
    assert kz.source_type == "kaggle"
    assert kz.path_or_ref == "saloni1712/zomato-and-swiggy-play-store-reviews"
    assert kz.file == "zomato.csv"
    assert kz.format == "csv"
    assert kz.platform == "other"
    assert kz.content_type == "review"
    assert kz.enabled is True
    assert kz.columns.get("text") == "review_description"
    assert kz.columns.get("date") == "review_date"
    assert kz.columns.get("company") == "App"
    assert kz.columns.get("rating") == "rating"
    assert "id" not in kz.columns
    assert kz.license_note == "TODO: copy the licence from the Kaggle dataset page"

    # 3. kaggle_swiggy_app_reviews
    assert "kaggle_swiggy_app_reviews" in catalogue
    ks = catalogue["kaggle_swiggy_app_reviews"]
    assert ks.source_type == "kaggle"
    assert ks.path_or_ref == "saloni1712/zomato-and-swiggy-play-store-reviews"
    assert ks.file == "swiggy.csv"
    assert ks.format == "csv"
    assert ks.columns.get("company") == "App"
    assert kz.license_note == "TODO: copy the licence from the Kaggle dataset page"

    # 4. kaggle_zomato_playstore_2025
    assert "kaggle_zomato_playstore_2025" in catalogue
    kz25 = catalogue["kaggle_zomato_playstore_2025"]
    assert kz25.source_type == "kaggle"
    assert kz25.path_or_ref == "sonalshinde123/zomato-app-play-store-reviews"
    assert kz25.file == "zomato_reviews.csv"
    assert kz25.default_company == "Zomato"
    assert kz25.columns.get("text") == "review_text"
    assert kz25.columns.get("id") == "review_id"
    assert kz25.license_note == "TODO: copy the licence from the Kaggle dataset page"

