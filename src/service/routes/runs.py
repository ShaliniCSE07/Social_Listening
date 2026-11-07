"""Pipeline run execution and inspection endpoints."""
from datetime import datetime, timezone
import secrets
import threading
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse

from src.collection.budget import BudgetTracker
from src.collection.plugins.dataset.catalogue import load_dataset_catalogue
from src.contracts.enums import Platform
from src.service.models import (
    CreateRunRequest,
    CreateRunResponse,
    PaginatedMentionsResponse,
    RunDetailResponse,
    RunListItem,
)
from src.service.run_store import run_store
from src.service.runner import default_runner

router = APIRouter(prefix="/api/runs", tags=["runs"])

VALID_PLATFORMS = {p.value for p in Platform}


def _validate_run_request(request: CreateRunRequest) -> None:
    """Validate platforms and dataset keys before launching a run."""
    if request.sources:
        if request.sources.api:
            for plat in request.sources.api:
                if plat.lower() not in VALID_PLATFORMS:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Unknown API platform: '{plat}'. Valid platforms: {sorted(VALID_PLATFORMS)}",
                    )
        if request.sources.dataset_keys:
            catalogue = load_dataset_catalogue()
            for key in request.sources.dataset_keys:
                if key not in catalogue:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Unknown dataset key: '{key}'. Dataset not found in catalogue.",
                    )


@router.post("", response_model=CreateRunResponse, status_code=status.HTTP_202_ACCEPTED)
def create_run(request: CreateRunRequest) -> CreateRunResponse:
    """Start a new social listening collection run in the background."""
    _validate_run_request(request)

    run_id = request.run_id or ("run_" + secrets.token_hex(4))

    now = datetime.now(timezone.utc)
    tracker = BudgetTracker(limit_usd=request.budget_usd)

    initial_summary = {
        "run_id": run_id,
        "status": "queued",
        "created_at": now.isoformat(),
        "started_at": None,
        "finished_at": None,
        "companies": [c.name for c in request.companies],
        "counts": {
            "mentions_count": 0,
            "attempts_count": 0,
            "cost_usd": 0.0,
        },
        "budget_snapshot": tracker.snapshot(),
        "progress": {},
        "per_source_results": {},
    }
    run_store.save_run_summary(run_id, initial_summary)

    # Launch background thread
    worker = threading.Thread(
        target=default_runner.run,
        args=(run_id, request),
        daemon=True,
    )
    worker.start()

    return CreateRunResponse(run_id=run_id, status="queued")


@router.get("", response_model=List[RunListItem])
def list_runs() -> List[RunListItem]:
    """List all pipeline runs with basic summary totals."""
    return run_store.list_runs()


@router.get("/{run_id}", response_model=RunDetailResponse)
def get_run(run_id: str) -> RunDetailResponse:
    """Fetch complete details, status, progress and budget snapshot for a run."""
    run_data = run_store.get_run(run_id)
    if not run_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' not found",
        )
    return RunDetailResponse(**run_data)


@router.get("/{run_id}/attempts", response_model=List[Dict[str, Any]])
def get_run_attempts(
    run_id: str,
    company: Optional[str] = Query(None, description="Filter attempts by company name"),
    status: Optional[str] = Query(None, description="Filter attempts by status"),
) -> List[Dict[str, Any]]:
    """Retrieve collection attempts for a run, with optional filtering."""
    if not run_store.get_run(run_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' not found",
        )
    return run_store.get_attempts(run_id, company=company, status=status)


@router.get("/{run_id}/mentions", response_model=PaginatedMentionsResponse)
def get_run_mentions(
    run_id: str,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Items per page (max 200)"),
    company: Optional[str] = Query(None, description="Filter mentions by company"),
    platform: Optional[str] = Query(None, description="Filter mentions by platform"),
    method: Optional[str] = Query(None, description="Filter mentions by collection method"),
    full: bool = Query(False, description="Return full RawMention payload instead of compact view"),
) -> PaginatedMentionsResponse:
    """Retrieve paginated mentions for a run with compact or full representation."""
    if not run_store.get_run(run_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' not found",
        )

    res = run_store.get_mentions(
        run_id=run_id,
        company=company,
        platform=platform,
        method=method,
        page=page,
        page_size=page_size,
        full=full,
    )
    if res is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' not found",
        )
    return PaginatedMentionsResponse(**res)


@router.get("/{run_id}/download")
def download_run_file(
    run_id: str,
    file: str = Query(..., description="File to download: 'mentions.jsonl' or 'attempts.jsonl'"),
) -> FileResponse:
    """Download raw JSONL artifact file from a run."""
    if file not in ("mentions.jsonl", "attempts.jsonl"):
        raise HTTPException(
            status_code=422,
            detail="Invalid file parameter. Must be 'mentions.jsonl' or 'attempts.jsonl'.",
        )

    file_path = run_store.get_download_path(run_id, file)
    if not file_path or not file_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File '{file}' not found for run '{run_id}'.",
        )

    return FileResponse(
        path=str(file_path),
        filename=f"{run_id}_{file}",
        media_type="application/x-ndjson",
    )

