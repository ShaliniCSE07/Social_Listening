"""Collection -> processing gateway endpoints.

GET  /api/processing/status          can processing run in this environment?
GET  /api/runs/{run_id}/processing   processing state of one collection run
POST /api/runs/{run_id}/process      hand a finished run to processing (202)
"""
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, status

from src.service import processing_gateway as gateway

router = APIRouter(tags=["processing"])


def _raise(exc: gateway.GatewayError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("/api/processing/status")
def processing_status() -> Dict[str, Any]:
    """Whether the processing step (Member 2) can run here, and why not."""
    return gateway.processing_availability()


@router.get("/api/runs/{run_id}/processing")
def get_run_processing(run_id: str) -> Dict[str, Any]:
    """Processing state for a collection run (not_started, queued, running, completed, failed)."""
    try:
        return gateway.get_processing_state(run_id)
    except gateway.GatewayError as exc:
        _raise(exc)


@router.post("/api/runs/{run_id}/process", status_code=status.HTTP_202_ACCEPTED)
def process_run(run_id: str) -> Dict[str, Any]:
    """Send a completed or partial collection run to the processing pipeline."""
    try:
        return gateway.start_processing(run_id)
    except gateway.GatewayError as exc:
        _raise(exc)
