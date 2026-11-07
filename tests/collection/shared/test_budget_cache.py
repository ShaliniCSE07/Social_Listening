"""Tests for BudgetTracker and ResultCache."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
import json
import pytest

from src.collection.budget import BudgetExceeded, BudgetTracker
from src.collection.cache import ResultCache, compute_cache_key
from src.contracts.enums import AttemptStatus, Method, Platform


def test_reserve_then_commit():
    tracker = BudgetTracker(limit_usd=10.0)
    token = tracker.reserve(Platform.reddit, 2.50)
    assert token.reserved_amount == 2.50

    snap1 = tracker.snapshot()
    assert snap1["reserved_total"] == 2.50
    assert snap1["remaining_usd"] == 7.50

    # Commit actual amount (e.g. 2.20)
    tracker.commit(token, actual_amount=2.20)
    snap2 = tracker.snapshot()
    assert snap2["spent_total"] == 2.20
    assert snap2["reserved_total"] == 0.0
    assert snap2["remaining_usd"] == 7.80
    assert snap2["spent_by_platform"]["reddit"] == 2.20


def test_release_returns_funds():
    tracker = BudgetTracker(limit_usd=5.0)
    token = tracker.reserve(Platform.google, 3.0)
    assert tracker.can_afford(Platform.google, 3.0) is False

    tracker.release(token)
    snap = tracker.snapshot()
    assert snap["reserved_total"] == 0.0
    assert snap["remaining_usd"] == 5.0
    assert tracker.can_afford(Platform.google, 3.0) is True


def test_over_limit_raises():
    tracker = BudgetTracker(limit_usd=2.0)
    assert tracker.can_afford(Platform.reddit, 2.50) is False
    with pytest.raises(BudgetExceeded):
        tracker.reserve(Platform.reddit, 2.50)


def test_free_call_passes_at_zero_remaining():
    tracker = BudgetTracker(limit_usd=1.0)
    token1 = tracker.reserve(Platform.reddit, 1.0)
    tracker.commit(token1, actual_amount=1.0)

    snap = tracker.snapshot()
    assert snap["remaining_usd"] == 0.0
    assert tracker.can_afford(Platform.reddit, 0.0) is True

    # Free call reserve succeeds even with 0 remaining
    token2 = tracker.reserve(Platform.reddit, 0.0)
    assert token2.reserved_amount == 0.0
    tracker.commit(token2, actual_amount=0.0)
    assert tracker.snapshot()["spent_total"] == 1.0


def test_two_threads_cannot_overspend():
    tracker = BudgetTracker(limit_usd=10.0)
    successes = []
    failures = []

    def attempt_reserve():
        try:
            tok = tracker.reserve(Platform.reddit, 6.0)
            successes.append(tok)
        except BudgetExceeded:
            failures.append(True)

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(attempt_reserve)
        f2 = executor.submit(attempt_reserve)
        f1.result()
        f2.result()

    # One must succeed and one must fail since 6.0 + 6.0 > 10.0
    assert len(successes) == 1
    assert len(failures) == 1


def test_create_exhausted_attempt():
    tracker = BudgetTracker(limit_usd=5.0)
    attempt = tracker.create_exhausted_attempt("Tata Motors", Platform.reddit, Method.api)
    assert attempt.status == AttemptStatus.budget_exhausted
    assert attempt.company == "Tata Motors"
    assert "limit" in attempt.reason.lower()


def test_cache_hit_and_miss(tmp_path):
    cache = ResultCache(cache_dir=tmp_path)
    key = compute_cache_key("reddit_api", "Tata Motors", {"sort": "new"})

    # Cache miss
    assert cache.get(key) is None

    # Cache put & hit
    items = [{"id": "1", "title": "Tata post"}, {"id": "2", "title": "Second post"}]
    cache.put(key, items)

    retrieved = cache.get(key, max_age_days=7)
    assert retrieved == items


def test_expired_entry_ignored(tmp_path):
    cache = ResultCache(cache_dir=tmp_path)
    key = compute_cache_key("reddit_api", "Zomato", {})

    file_path = tmp_path / f"{key}.json"
    old_time = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    payload = {
        "key": key,
        "stored_at": old_time,
        "items": [{"id": "old_1"}],
    }
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(payload, f)

    # Max age 3 days, stored 10 days ago -> should return None
    assert cache.get(key, max_age_days=3) is None

    # Max age 15 days -> should return items
    assert cache.get(key, max_age_days=15) == [{"id": "old_1"}]

