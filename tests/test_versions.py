from datetime import datetime, timezone
from unittest.mock import patch
import pytest

from models import AttemptStatus, CollectionAttempt, ContentTypeHint, Method, Platform, RawMention
from processor import process_mentions
from storage import get_db

# Deterministic mention ID format: 'm_' followed by 12 hex characters
MOCK_DETERMINISTIC_ID = "m_619f7e51bad2"


def _raw(text: str, item_id: str = "t1_abc", posted: str = "2026-10-26T09:14:00Z") -> RawMention:
    return RawMention(
        company="Acme",
        platform=Platform.REDDIT,
        item_id=item_id,
        url="https://reddit.com/r/tech/comments/xyz/comment/abc123",
        content_type_hint=ContentTypeHint.COMMENT,
        raw_payload={
            "id": item_id,
            "author": "jane_doe",
            "body": text,
            "updated": posted,
        },
        source="reddit.com",
        method_used=Method.RSS,
        tool_used="Reddit RSS feed",
        collected_at=datetime(2026, 10, 27, 7, 10, 0, tzinfo=timezone.utc),
    )


def _attempt() -> CollectionAttempt:
    now = datetime(2026, 10, 27, 7, 10, 0, tzinfo=timezone.utc)
    return CollectionAttempt(
        company="Acme",
        platform=Platform.REDDIT,
        method=Method.RSS,
        status=AttemptStatus.SUCCESS,
        item_count=1,
        cost_usd=0.0,
        started_at=now,
        finished_at=now,
    )


@patch("processor._mention_id", return_value=MOCK_DETERMINISTIC_ID)
def test_edit_creates_new_version(mock_mid):
    db = get_db()
    db.records.delete_many({})

    # 1. First run: original text
    r1 = process_mentions([_raw("Acme original text")], [_attempt()], "run_1", {}, "full")
    assert r1["inserted"] == 1
    assert len(r1["records"]) == 1
    rec1 = r1["records"][0]
    assert rec1.version == 1
    assert rec1.is_update is False
    assert rec1.supersedes is None
    record_id = rec1.record_id

    # 2. Second run: same item_id, changed text
    r2 = process_mentions([_raw("Acme edited text")], [_attempt()], "run_2", {}, "delta")
    assert r2["inserted"] == 1
    assert r2["updated"] == 1
    assert r2["counters"]["updated"] == 1
    assert len(r2["records"]) == 1
    rec2 = r2["records"][0]
    assert rec2.is_update is True
    assert rec2.version == 2
    assert rec2.supersedes == f"{record_id}:v1"

    # 3. Verify in MongoDB that both versions exist and old version is retrievable
    versions = list(db.records.find({"record_id": record_id}).sort("version", 1))
    assert len(versions) == 2

    v1_doc = versions[0]
    assert v1_doc["version"] == 1
    assert v1_doc["is_update"] is False
    assert v1_doc["supersedes"] is None
    assert v1_doc["text"] == "Acme original text"

    v2_doc = versions[1]
    assert v2_doc["version"] == 2
    assert v2_doc["is_update"] is True
    assert v2_doc["supersedes"] == f"{record_id}:v1"
    assert v2_doc["text"] == "Acme edited text"


@patch("processor._mention_id", return_value=MOCK_DETERMINISTIC_ID)
def test_same_content_is_duplicate(mock_mid):
    db = get_db()
    db.records.delete_many({})

    # First run
    r1 = process_mentions([_raw("Acme same text")], [_attempt()], "run_1", {}, "full")
    assert r1["inserted"] == 1

    # Second run with identical content
    r2 = process_mentions([_raw("Acme same text")], [_attempt()], "run_2", {}, "delta")
    assert r2["inserted"] == 0
    assert r2["counters"]["duplicates"] >= 1
    assert r2["counters"]["updated"] == 0

    # DB still has only 1 record
    docs = list(db.records.find({"record_id": r1["records"][0].record_id}))
    assert len(docs) == 1
    assert docs[0]["version"] == 1


def test_version_without_mock():
    """Verify natural deterministic ID hashing also properly increments versions."""
    db = get_db()
    db.records.delete_many({})

    r1 = process_mentions([_raw("Acme original text")], [_attempt()], "run_1", {}, "full")
    rec1 = r1["records"][0]
    assert rec1.mention_id.startswith("m_")
    assert len(rec1.mention_id) == 14  # 'm_' + 12 hex chars

    r2 = process_mentions([_raw("Acme edited text")], [_attempt()], "run_2", {}, "delta")
    assert r2["inserted"] == 1
    assert r2["updated"] == 1
    rec2 = r2["records"][0]
    assert rec2.version == 2
    assert rec2.is_update is True
    assert rec2.supersedes == f"{rec1.record_id}:v1"

