from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict

from storage import get_db


DEFAULT_LOOKBACK_DAYS = 90      # FR-DLT-02 / OQ-SOCL-09 proposal
OVERLAP_FREE_DAYS = 2           # FR-DLT-03
OVERLAP_PAID_DAYS = 1           # FR-DLT-03

def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)

class Checkpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_id: str
    platform: str
    loaded_up_to: datetime
    cursor: str | None = None
    last_run_id: str | None = None
    last_run_at: datetime | None = None
    method_used: str | None = None


class Window(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_from: datetime
    window_to: datetime
    load_type: Literal["full", "delta"]
    overlap_days: int
    reason: str


def get_checkpoint(company_id: str, platform: str) -> Checkpoint | None:
    doc = get_db().checkpoints.find_one({"companyId": company_id, "platform": platform})
    if not doc:
        return None
    return Checkpoint(
        company_id=doc["companyId"],
        platform=doc["platform"],
        loaded_up_to=_as_utc(doc["loadedUpTo"]),
        cursor=doc.get("cursor"),
        last_run_id=doc.get("lastRunId"),
        last_run_at=_as_utc(doc.get("lastRunAt")),
        method_used=doc.get("methodUsed"),
    )


def advance_checkpoint(
    company_id: str,
    platform: str,
    window_to: datetime,
    run_id: str,
    method: str,
    cursor: str | None = None,
) -> None:
    """Advance only after that platform's records are saved (FR-DLT-05)."""
    get_db().checkpoints.update_one(
        {"companyId": company_id, "platform": platform},
        {
            "$set": {
                "loadedUpTo": window_to,
                "lastRunId": run_id,
                "lastRunAt": datetime.now(timezone.utc),
                "methodUsed": method,
                **({"cursor": cursor} if cursor else {}),
            }
        },
        upsert=True,
    )


def compute_window(
    company_id: str,
    platform: str,
    is_paid: bool,
    now: datetime | None = None,
    manual_from: datetime | None = None,
    manual_to: datetime | None = None,
    user_start_date: datetime | None = None,
) -> Window:
    """
    Decide the window for this company x platform according to FR-DLT-02/03/04/07.
    """
    now = now or datetime.now(timezone.utc)
    overlap_days = OVERLAP_PAID_DAYS if is_paid else OVERLAP_FREE_DAYS

    # Manual override (FR-DLT-07)
    if manual_from and manual_to:
        return Window(
            window_from=manual_from,
            window_to=manual_to,
            load_type="delta",
            overlap_days=overlap_days,
            reason="manual_range",
        )

    cp = get_checkpoint(company_id, platform)

    # First load (FR-DLT-02)
    if cp is None:
        window_from = user_start_date or (now - timedelta(days=DEFAULT_LOOKBACK_DAYS))
        return Window(
            window_from=window_from,
            window_to=now,
            load_type="full",
            overlap_days=overlap_days,
            reason="first_load" if not user_start_date else "first_load_user_start",
        )

    # Delta (FR-DLT-02, 03)
    return Window(
        window_from=cp.loaded_up_to - timedelta(days=overlap_days),
        window_to=now,
        load_type="delta",
        overlap_days=overlap_days,
        reason="delta_with_overlap",
    )