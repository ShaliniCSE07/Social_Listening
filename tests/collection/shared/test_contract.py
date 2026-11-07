"""Tests for shared contracts: schemas, enums, and JSONL I/O."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest
from pydantic import ValidationError

from src.contracts.enums import AttemptStatus, ContentType, Method, Platform
from src.contracts.schemas import CollectionAttempt, RawMention
from src.contracts.io import (
    read_attempts_jsonl,
    read_mentions_jsonl,
    write_attempts_jsonl,
    write_mentions_jsonl,
)

FIXTURES_MOCK_DIR = Path(__file__).resolve().parents[3] / "data" / "mock"


def test_round_trip_write_then_read_mentions(tmp_path):
    now = datetime.now(timezone.utc)
    mentions = [
        RawMention(
            company="Zomato",
            platform=Platform.reddit,
            raw_payload={"title": "Test 1"},
            source="reddit_api",
            method_used=Method.api,
            tool_used="Reddit Client",
            cost_usd=0.01,
            collected_at=now,
        ),
        RawMention(
            company="Swiggy",
            platform=Platform.google,
            raw_payload={"rating": 5},
            source="google_places_api",
            method_used=Method.api,
            tool_used="Google Places Client",
            cost_usd=0.02,
            collected_at=now,
        ),
    ]

    target = tmp_path / "mentions.jsonl"
    write_mentions_jsonl(target, mentions)
    grouped = read_mentions_jsonl(target)

    assert "Zomato" in grouped
    assert "Swiggy" in grouped
    assert len(grouped["Zomato"]) == 1
    assert len(grouped["Swiggy"]) == 1
    assert grouped["Zomato"][0].platform == Platform.reddit
    assert grouped["Swiggy"][0].platform == Platform.google


def test_round_trip_write_then_read_attempts(tmp_path):
    now = datetime.now(timezone.utc)
    attempts = [
        CollectionAttempt(
            company="Zomato",
            platform=Platform.reddit,
            method=Method.api,
            status=AttemptStatus.success,
            reason="Retrieved 1 item",
            item_count=1,
            cost_usd=0.01,
            started_at=now,
            finished_at=now,
        )
    ]

    target = tmp_path / "attempts.jsonl"
    write_attempts_jsonl(target, attempts)
    read_back = read_attempts_jsonl(target)

    assert len(read_back) == 1
    assert read_back[0].company == "Zomato"
    assert read_back[0].status == AttemptStatus.success


def test_naive_datetime_rejected():
    naive_dt = datetime(2026, 11, 7, 8, 0, 0)
    with pytest.raises(ValidationError) as exc_info:
        RawMention(
            company="Zomato",
            platform=Platform.reddit,
            raw_payload={},
            source="test",
            method_used=Method.api,
            tool_used="test",
            collected_at=naive_dt,
        )
    assert "timezone-aware" in str(exc_info.value)


def test_non_utc_rejected():
    est_tz = timezone(timedelta(hours=-5))
    non_utc_dt = datetime(2026, 11, 7, 8, 0, 0, tzinfo=est_tz)
    with pytest.raises(ValidationError) as exc_info:
        RawMention(
            company="Zomato",
            platform=Platform.reddit,
            raw_payload={},
            source="test",
            method_used=Method.api,
            tool_used="test",
            collected_at=non_utc_dt,
        )
    assert "UTC" in str(exc_info.value)


def test_unknown_field_rejected():
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError) as exc_info:
        RawMention(
            company="Zomato",
            platform=Platform.reddit,
            raw_payload={},
            source="test",
            method_used=Method.api,
            tool_used="test",
            collected_at=now,
            unexpected_field="disallowed",
        )
    assert "extra_forbidden" in str(exc_info.value) or "Extra inputs are not permitted" in str(exc_info.value)


def test_rss_rejected_as_method_value():
    with pytest.raises(ValueError):
        Method("rss")


def test_grouping_by_company(tmp_path):
    now = datetime.now(timezone.utc)
    mentions = [
        RawMention(
            company="Zomato",
            platform=Platform.reddit,
            raw_payload={"id": "1"},
            source="api",
            method_used=Method.api,
            tool_used="test",
            collected_at=now,
        ),
        RawMention(
            company="Zomato",
            platform=Platform.twitter_x,
            raw_payload={"id": "2"},
            source="api",
            method_used=Method.api,
            tool_used="test",
            collected_at=now,
        ),
        RawMention(
            company="Swiggy",
            platform=Platform.google,
            raw_payload={"id": "3"},
            source="api",
            method_used=Method.api,
            tool_used="test",
            collected_at=now,
        ),
    ]

    target = tmp_path / "grouped_mentions.jsonl"
    write_mentions_jsonl(target, mentions)
    grouped = read_mentions_jsonl(target)

    assert len(grouped["Zomato"]) == 2
    assert len(grouped["Swiggy"]) == 1


def test_bad_line_gives_line_number(tmp_path):
    target = tmp_path / "corrupted_mentions.jsonl"
    with open(target, "w", encoding="utf-8") as f:
        f.write('{"company": "ValidCompany", "schema_version": "1.0", "platform": "reddit", "raw_payload": {}, "source": "s", "method_used": "api", "tool_used": "t", "collected_at": "2026-11-07T08:00:00Z"}\n')
        f.write('{"company": "BadCompany", "invalid_json_missing_fields": true}\n')

    with pytest.raises(ValueError) as exc_info:
        read_mentions_jsonl(target)
    assert "line 2" in str(exc_info.value)


def test_mock_files_load_without_errors():
    mentions_file = FIXTURES_MOCK_DIR / "mentions_sample.jsonl"
    attempts_file = FIXTURES_MOCK_DIR / "attempts_sample.jsonl"

    assert mentions_file.is_file()
    assert attempts_file.is_file()

    mentions = read_mentions_jsonl(mentions_file)
    assert len(mentions) >= 2  # contains Zomato and Swiggy
    assert "Zomato" in mentions
    assert "Swiggy" in mentions

    attempts = read_attempts_jsonl(attempts_file)
    assert len(attempts) >= 5
    statuses = {a.status for a in attempts}
    assert AttemptStatus.success in statuses
    assert AttemptStatus.failed in statuses
    assert AttemptStatus.rate_limited in statuses
    assert AttemptStatus.empty in statuses
    assert AttemptStatus.skipped in statuses

    # Verify scraping checks presence
    scraping_attempts = [a for a in attempts if a.scraping_checks is not None]
    assert len(scraping_attempts) > 0

