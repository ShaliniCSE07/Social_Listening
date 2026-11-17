"""Gateway from collection (Member 1) to processing (Member 2).

Collection runs write ``data/runs/<run_id>/mentions.jsonl`` and
``attempts.jsonl``. Once a run has finished, this gateway hands those two
files to Member 2's processing pipeline (the same code behind
``POST /process`` in the root ``main.py``), in the same backend process.

Nothing in the collection or processing code paths changes: the gateway only
reads the collection output files and calls ``main.process_handoff``.

Processing state for a run is kept beside the collection files in
``data/runs/<run_id>/processing.json`` so it survives restarts and never
touches ``run_summary.json``.

Member 2's code is imported lazily, because it needs MongoDB, Presidio and
the ``SOCL_AUTHOR_PEPPER`` environment variable. When any of these is
missing the collection service keeps working and the gateway reports
"processing unavailable" with the reason.
"""
from __future__ import annotations

import importlib
import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config.settings import load_companies
from src.service.run_store import run_store

logger = logging.getLogger(__name__)

PROCESSING_FILE = "processing.json"
# Collection statuses whose output may be processed.
PROCESSABLE_RUN_STATUSES = {"completed", "partial"}

_lock = threading.Lock()
_active: set[str] = set()


class GatewayError(Exception):
    """Raised for gateway failures that map to an HTTP status code."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


# ── Member 2 module loading ────────────────────────────────────────────────


def load_processing_modules() -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Import Member 2's processing modules.

    Returns ``(modules, None)`` on success, or ``(None, reason)`` when the
    processing side cannot be loaded in this environment.
    """
    try:
        m2_main = importlib.import_module("main")
        m2_models = importlib.import_module("models")
        m2_storage = importlib.import_module("storage")
    except RuntimeError as exc:  # e.g. SOCL_AUTHOR_PEPPER missing
        return None, str(exc)
    except ImportError as exc:
        return None, f"processing dependencies are not installed ({exc.name or exc})"
    except Exception as exc:  # pragma: no cover - defensive
        return None, f"processing module failed to load: {type(exc).__name__}: {exc}"

    if not hasattr(m2_main, "process_handoff"):
        return None, "main.process_handoff not found in the processing module"

    return {"main": m2_main, "models": m2_models, "storage": m2_storage}, None


def check_mongo(timeout_ms: int = 2000) -> Optional[str]:
    """Return ``None`` when MongoDB answers a ping, otherwise the reason."""
    try:
        from pymongo import MongoClient
    except ImportError:
        return "pymongo is not installed"

    uri = os.environ.get("SOCL_MONGO_URI", "mongodb://localhost:27017")
    client = None
    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=timeout_ms)
        client.admin.command("ping")
        return None
    except Exception:
        return "MongoDB is not reachable (check that it is running and SOCL_MONGO_URI)"
    finally:
        if client is not None:
            client.close()


def processing_availability() -> Dict[str, Any]:
    """Whether processing can run here, and why not when it cannot."""
    modules, reason = load_processing_modules()
    if modules is None:
        return {"available": False, "reason": reason}
    mongo_reason = check_mongo()
    if mongo_reason:
        return {"available": False, "reason": mongo_reason}
    return {"available": True, "reason": None}


# ── Processing state file ──────────────────────────────────────────────────


def _state_path(run_id: str) -> Path:
    return run_store.base_dir / run_id / PROCESSING_FILE


def read_state(run_id: str) -> Optional[Dict[str, Any]]:
    path = _state_path(run_id)
    if not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_state(run_id: str, state: Dict[str, Any]) -> None:
    path = _state_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, default=str)
    os.replace(tmp, path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_processing_state(run_id: str) -> Dict[str, Any]:
    """Return the processing state for a collection run."""
    run = run_store.get_run(run_id)
    if run is None:
        raise GatewayError(404, f"Run '{run_id}' not found")

    state = read_state(run_id) or {"status": "not_started"}
    # A thread that died with the process (restart mid-run) leaves "running"
    # behind; report it as failed so the user can retry.
    if state.get("status") in ("queued", "running") and run_id not in _active:
        state = {
            **state,
            "status": "failed",
            "error": "Processing was interrupted (the backend restarted). Start it again.",
        }
        _write_state(run_id, state)

    return {
        "run_id": run_id,
        "collection_status": run.get("status"),
        "can_process": run.get("status") in PROCESSABLE_RUN_STATUSES,
        **state,
    }


# ── Handoff conversion ─────────────────────────────────────────────────────


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.is_file():
        return rows
    with open(path, "r", encoding="utf-8-sig") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path.name} line {line_no}: invalid JSON ({exc.msg})") from exc
    return rows


def _only_known_fields(row: Dict[str, Any], model: Any) -> Dict[str, Any]:
    """Keep only the fields the processing model declares.

    Collection attempts carry extra scraping diagnostics (pages_fetched,
    pages_from_cache, delay_used) that the processing ``CollectionAttempt``
    model does not declare; with ``extra='forbid'`` they would be rejected.
    They are only used by the collection dashboard, so they are dropped here.
    """
    allowed = set(model.model_fields)
    return {k: v for k, v in row.items() if k in allowed}


def load_handoff(run_id: str, models: Any) -> Tuple[list, list]:
    """Read a collection run's output and validate it with the processing models."""
    run_dir = run_store.base_dir / run_id
    mention_rows = _read_jsonl(run_dir / "mentions.jsonl")
    attempt_rows = _read_jsonl(run_dir / "attempts.jsonl")

    mentions = []
    for idx, row in enumerate(mention_rows, start=1):
        try:
            mentions.append(models.RawMention(**_only_known_fields(row, models.RawMention)))
        except Exception as exc:
            raise ValueError(f"mentions.jsonl line {idx}: {exc}") from exc

    attempts = []
    for idx, row in enumerate(attempt_rows, start=1):
        try:
            attempts.append(
                models.CollectionAttempt(**_only_known_fields(row, models.CollectionAttempt))
            )
        except Exception as exc:
            raise ValueError(f"attempts.jsonl line {idx}: {exc}") from exc

    return mentions, attempts


def industry_map_for(companies: List[str]) -> Dict[str, Optional[str]]:
    """Industry per company, from config/companies.yaml (case-insensitive)."""
    configured = {name.lower(): (cfg or {}).get("industry") for name, cfg in load_companies().items()}
    return {name: configured.get(name.lower()) for name in companies}


def _summarise(result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "record_count": result.get("record_count", 0),
        "counters": result.get("counters", {}),
        "total_cost_usd": (result.get("report") or {}).get("total_cost_usd", 0.0),
    }


# ── Running ────────────────────────────────────────────────────────────────


def _process(run_id: str, modules: Dict[str, Any]) -> None:
    started_at = _now()
    _write_state(run_id, {"status": "running", "started_at": started_at})
    try:
        try:
            modules["storage"].ensure_indexes()
        except Exception as exc:  # indexes are an optimisation; don't block
            logger.warning("processing: ensure_indexes failed: %s", exc)

        mentions, attempts = load_handoff(run_id, modules["models"])
        run = run_store.get_run(run_id) or {}
        companies = run.get("companies") or sorted({m.company for m in mentions})

        result = modules["main"].process_handoff(
            mentions,
            attempts,
            industry_map_for(companies),
            run_id=run_id,
            run_extra={"source": "collection_gateway", "collection_run_id": run_id},
        )
        _write_state(
            run_id,
            {
                "status": "completed",
                "started_at": started_at,
                "finished_at": _now(),
                "mentions_in": len(mentions),
                "attempts_in": len(attempts),
                **_summarise(result),
            },
        )
    except Exception as exc:
        logger.exception("processing failed for run %s", run_id)
        _write_state(
            run_id,
            {
                "status": "failed",
                "started_at": started_at,
                "finished_at": _now(),
                "error": f"{type(exc).__name__}: {exc}"[:1000],
            },
        )
    finally:
        with _lock:
            _active.discard(run_id)


def start_processing(run_id: str, background: bool = True) -> Dict[str, Any]:
    """Validate and start processing a finished collection run.

    Raises ``GatewayError`` for: unknown run (404), run not finished or
    already processing/processed (409), processing unavailable (503).
    """
    run = run_store.get_run(run_id)
    if run is None:
        raise GatewayError(404, f"Run '{run_id}' not found")

    status = run.get("status")
    if status not in PROCESSABLE_RUN_STATUSES:
        if status in ("queued", "running"):
            msg = "Collection is still running. Process the run after it finishes."
        else:
            msg = f"Collection run is '{status}'; only completed or partial runs can be processed."
        raise GatewayError(409, msg)

    if not (run.get("counts") or {}).get("mentions_count"):
        raise GatewayError(409, "This run collected no mentions, so there is nothing to process.")

    with _lock:
        if run_id in _active:
            raise GatewayError(409, "Processing is already running for this run.")
        existing = read_state(run_id) or {}
        if existing.get("status") == "completed":
            raise GatewayError(409, "This run has already been processed.")

        modules, reason = load_processing_modules()
        if modules is None:
            raise GatewayError(503, f"Processing is unavailable: {reason}")
        mongo_reason = check_mongo()
        if mongo_reason:
            raise GatewayError(503, f"Processing is unavailable: {mongo_reason}")

        _active.add(run_id)
        _write_state(run_id, {"status": "queued", "queued_at": _now()})

    if background:
        threading.Thread(target=_process, args=(run_id, modules), daemon=True).start()
    else:
        _process(run_id, modules)

    return get_processing_state(run_id)


# ── Sharing the processing routes with the processing dashboard ────────────


def mount_processing_routes(app: Any) -> Optional[str]:
    """Serve Member 2's API routes (``/process``, ``/runs/{id}/records``,
    ``/api/v1/runs/{id}/rerun``) from this backend.

    The processing dashboard (Streamlit, ``app_ui.py``) calls these routes on
    ``http://localhost:8000``, the same port as this service, so both
    dashboards share one backend. Returns ``None`` on success or the reason
    the routes could not be mounted. Member 2's startup hook is not copied;
    MongoDB indexes are created in the background instead so a missing
    MongoDB never blocks the collection service from starting.
    """
    from fastapi.routing import APIRoute

    modules, reason = load_processing_modules()
    if modules is None:
        logger.warning("processing routes not mounted: %s", reason)
        return reason

    existing = {
        (route.path, tuple(sorted(route.methods or [])))
        for route in app.router.routes
        if isinstance(route, APIRoute)
    }
    for route in modules["main"].app.router.routes:
        if not isinstance(route, APIRoute):
            continue
        key = (route.path, tuple(sorted(route.methods or [])))
        if key in existing:
            continue
        app.router.routes.append(route)

    def _ensure_indexes() -> None:
        try:
            modules["storage"].ensure_indexes()
        except Exception as exc:
            logger.warning("processing: could not create MongoDB indexes: %s", exc)

    @app.on_event("startup")
    def _start_index_thread() -> None:  # pragma: no cover - trivial
        threading.Thread(target=_ensure_indexes, daemon=True).start()

    return None
