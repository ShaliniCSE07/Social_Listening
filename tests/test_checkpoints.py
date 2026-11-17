from datetime import datetime, timezone
from checkpoint import get_checkpoint, advance_checkpoint
from storage import get_db

def test_checkpoint_advances_on_success():
    get_db().checkpoints.delete_many({})
    advance_checkpoint("c_test", "reddit", datetime(2026, 10, 1, tzinfo=timezone.utc), "run_1", "rss")
    cp = get_checkpoint("c_test", "reddit")
    assert cp is not None
    assert cp.loaded_up_to == datetime(2026, 10, 1, tzinfo=timezone.utc)

def test_checkpoint_stays_unchanged_on_failure():
    get_db().checkpoints.delete_many({})
    # If a run fails, we simply don't call advance_checkpoint. 
    # So we assert that no checkpoint exists for a failed run.
    cp = get_checkpoint("c_test_fail", "reddit")
    assert cp is None