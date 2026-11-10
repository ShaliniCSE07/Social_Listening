from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from checkpoint import compute_window, advance_checkpoint, get_checkpoint
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
    company_id_for = lambda name: f"c_{__import__('hashlib').sha256(name.encode()).hexdigest()[:10]}"

    # Compute a window per (company, platform) using FR-DLT-02/03 rules.
    windows: dict[tuple[str, str], dict] = {}
    for m in mentions:
        key = (m.company, m.platform.value)
        if key in windows:
            continue
        w = compute_window(company_id_for(m.company), m.platform.value, is_paid=False)
        windows[key] = w.model_dump()

    # Run is "full" if any (company, platform) is full; otherwise delta.
    overall_load_type = "full" if any(v["load_type"] == "full" for v in windows.values()) else "delta"

    result = process_mentions(
        mentions=mentions,
        attempts=attempts,
        run_id=run_id,
        company_industry=industry_map,
        load_type=overall_load_type,
        windows=windows,
    )

    # Advance checkpoints only for companies/platforms that completed successfully (FR-DLT-05)
    # Simplified here: advance checkpoint for each company/platform that had at least one successful attempt
    from datetime import datetime, timezone
        # FR-DLT-05 / GR-9: advance only for platforms whose records were saved.
    succeeded = set()
    for a in attempts:
        if a.status.value == "success":
            succeeded.add((a.company, a.platform.value))

    for (company, platform) in succeeded:
        window = windows.get((company, platform))
        if window is None:
            continue
        advance_checkpoint(
            company_id=company_id_for(company),
            platform=platform,
            window_to=window["window_to"],
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