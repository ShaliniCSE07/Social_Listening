from datetime import datetime, timezone

from storage import get_db


def get_checkpoint(company_id: str, platform: str) -> dict | None:
    return get_db().checkpoints.find_one(
        {"companyId": company_id, "platform": platform}
    )


def advance_checkpoint(
    company_id: str,
    platform: str,
    window_to: datetime,
    run_id: str,
    method: str,
) -> None:
    """Advance only after platform data collected, cleaned and saved (FR-DLT-05)"""
    get_db().checkpoints.update_one(
        {"companyId": company_id, "platform": platform},
        {
            "$set": {
                "loadedUpTo": window_to,
                "lastRunId": run_id,
                "lastRunAt": datetime.now(timezone.utc),
                "methodUsed": method,
            }
        },
        upsert=True,
    )