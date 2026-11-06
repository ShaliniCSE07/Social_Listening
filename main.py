from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from checkpoint import advance_checkpoint, get_checkpoint
from models import CollectionAttempt, RawMention
from processor import process_mentions
from storage import ensure_indexes, get_db

app = FastAPI(title="SOCL Member 2 — Data Processing")


@app.on_event("startup")
def startup():
    ensure_indexes()


def _parse_jsonl(content: bytes) -> list[dict[str, Any]]:
    # utf-8-sig strips an optional UTF-8 BOM (EF BB BF) that Windows editors
    # and PowerShell's Set-Content -Encoding utf8 prepend. Without this,
    # json.loads rejects line 1 with "Unexpected UTF-8 BOM".
    text = content.decode("utf-8-sig")
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


@app.post("/process")
async def process_run(
    mentions_file: UploadFile = File(...),
    attempts_file: UploadFile = File(...),
    industry_json: str = Form(default="{}"),
):
    """
    industry_json example: {"Acme Insurance": "Insurance"}
    """
    mentions_raw = _parse_jsonl(await mentions_file.read())
    attempts_raw = _parse_jsonl(await attempts_file.read())

    # Pydantic validation (extra=forbid will reject unknown fields)
    mentions = [RawMention(**m) for m in mentions_raw]
    attempts = [CollectionAttempt(**a) for a in attempts_raw]

    run_id = f"run_{uuid.uuid4().hex[:12]}"
    try:
        industry_map = json.loads(industry_json) if industry_json else {}
        if not isinstance(industry_map, dict):
            raise ValueError("industry_json must be a JSON object")
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "SOCL-VAL-001", "message": f"Invalid industry_json: {exc}"},
        )

    # Determine load_type per company: no checkpoint -> full, else delta
    db = get_db()
    load_type_map: dict[str, str] = {}
    for m in mentions:
        company_id = f"c_{__import__('hashlib').sha256(m.company.encode()).hexdigest()[:10]}"
        cp = get_checkpoint(company_id, m.platform.value)
        load_type_map[m.company] = "full" if cp is None else "delta"

    # Use the strictest load_type across all companies as the run's default
    overall_load_type = "full" if any(v == "full" for v in load_type_map.values()) else "delta"

    result = process_mentions(
        mentions=mentions,
        attempts=attempts,
        run_id=run_id,
        company_industry=industry_map,
        load_type=overall_load_type,
    )

    # Advance checkpoints only for companies/platforms that completed successfully (FR-DLT-05)
    # Simplified here: advance checkpoint for each company/platform that had at least one successful attempt
    from datetime import datetime, timezone
    succeeded = set()
    for a in attempts:
        if a.status.value == "success":
            succeeded.add((a.company, a.platform.value))
    for company, platform in succeeded:
        company_id = f"c_{__import__('hashlib').sha256(company.encode()).hexdigest()[:10]}"
        advance_checkpoint(
            company_id=company_id,
            platform=platform,
            window_to=datetime.now(timezone.utc),
            run_id=run_id,
            method="api",
        )

    return {
        "run_id": run_id,
        "record_count": result["inserted"],
        "counters": result["counters"],
        "report": result["report"],
    }


@app.get("/runs/{run_id}/records")
def get_records(run_id: str) -> Iterable[str]:
    db = get_db()
    cursor = db.records.find({"run_id": run_id}, {"_id": 0})

    def generate():
        for doc in cursor:
            yield json.dumps(doc, ensure_ascii=False) + "\n"

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f"attachment; filename=records_{run_id}.jsonl"},
    )