from datetime import datetime, timedelta, timezone

from checkpoint import (
    DEFAULT_LOOKBACK_DAYS,
    OVERLAP_FREE_DAYS,
    OVERLAP_PAID_DAYS,
    Window,
    advance_checkpoint,
    compute_window,
)
from storage import get_db


def _clear():
    get_db().checkpoints.delete_many({})


def test_first_load_no_start_date():
    _clear()
    now = datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc)
    w = compute_window("c_x", "reddit", is_paid=False, now=now)
    assert w.load_type == "full"
    assert w.window_to == now
    assert (now - w.window_from).days == DEFAULT_LOOKBACK_DAYS
    assert w.reason == "first_load"


def test_first_load_with_user_start_date():
    _clear()
    now = datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    w = compute_window("c_x", "reddit", is_paid=False, now=now, user_start_date=start)
    assert w.load_type == "full"
    assert w.window_from == start
    assert w.reason == "first_load_user_start"


def test_delta_with_overlap():
    _clear()
    advance_checkpoint(
        "c_x", "reddit",
        window_to=datetime(2026, 9, 30, 23, 59, 59, tzinfo=timezone.utc),
        run_id="run_1", method="rss",
    )
    now = datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc)
    w = compute_window("c_x", "reddit", is_paid=False, now=now)
    assert w.load_type == "delta"
    expected_from = datetime(2026, 9, 28, 23, 59, 59, tzinfo=timezone.utc)
    assert w.window_from == expected_from
    assert w.window_to == now
    assert w.reason == "delta_with_overlap"


def test_manual_range_does_not_advance_backward():
    _clear()
    advance_checkpoint(
        "c_x", "reddit",
        window_to=datetime(2026, 10, 1, tzinfo=timezone.utc),
        run_id="run_1", method="rss",
    )
    w = compute_window(
        "c_x", "reddit",
        is_paid=False,
        manual_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        manual_to=datetime(2026, 2, 1, tzinfo=timezone.utc),
    )
    assert w.reason == "manual_range"
    assert w.load_type == "delta"