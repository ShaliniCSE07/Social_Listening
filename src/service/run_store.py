"""Run store persistence for run metadata, mentions, and attempts."""
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from src.contracts.io import write_attempts_jsonl, write_mentions_jsonl
from src.contracts.schemas import CollectionAttempt, RawMention

RUNS_DIR = Path("data/runs")


class RunStore:
    """Manages filesystem-backed storage for pipeline runs."""

    def __init__(self, base_dir: Path = RUNS_DIR):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _get_run_dir(self, run_id: str) -> Path:
        return self.base_dir / run_id

    def list_runs(self) -> List[Dict[str, Any]]:
        """Scan data/runs/*/run_summary.json and return summary list sorted newest first."""
        runs: List[Dict[str, Any]] = []
        if not self.base_dir.exists():
            return []

        for p in self.base_dir.glob("*/run_summary.json"):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    totals = data.get("counts")
                    if not isinstance(totals, dict):
                        totals = {
                            "mentions_count": data.get("mentions_count", 0),
                            "attempts_count": data.get("attempts_count", 0),
                            "cost_usd": data.get("cost_usd", 0.0),
                        }
                    runs.append(
                        {
                            "id": data.get("run_id") or data.get("id") or p.parent.name,
                            "status": data.get("status", "unknown"),
                            "created_at": data.get("created_at", ""),
                            "companies": data.get("companies", []),
                            "totals": totals,
                        }
                    )
            except Exception:
                continue

        # Sort descending by created_at
        runs.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        return runs

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Load run_summary.json for a specific run."""
        summary_path = self._get_run_dir(run_id) / "run_summary.json"
        if not summary_path.is_file():
            return None
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                counts = data.get("counts")
                if not isinstance(counts, dict):
                    counts = {
                        "mentions_count": data.get("mentions_count", 0),
                        "attempts_count": data.get("attempts_count", 0),
                        "cost_usd": data.get("cost_usd", 0.0),
                    }
                return {
                    "id": data.get("run_id") or data.get("id") or run_id,
                    "status": data.get("status", "unknown"),
                    "created_at": data.get("created_at", ""),
                    "started_at": data.get("started_at"),
                    "finished_at": data.get("finished_at"),
                    "error": data.get("error"),
                    "companies": data.get("companies") or [],
                    "progress": data.get("progress") or {},
                    "counts": counts,
                    "budget_snapshot": data.get("budget_snapshot") or {},
                    "per_source_results": data.get("per_source_results") or {},
                    "task_outcomes": data.get("task_outcomes"),
                    "decisions": data.get("decisions"),
                    "invalid_companies": data.get("invalid_companies"),
                }
        except Exception:
            return None

    def save_run_summary(self, run_id: str, summary: Dict[str, Any]) -> None:
        """Write run_summary.json for a run."""
        run_dir = self._get_run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        summary_path = run_dir / "run_summary.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, default=str)

    def save_artifacts(
        self,
        run_id: str,
        mentions: List[RawMention],
        attempts: List[CollectionAttempt],
    ) -> None:
        """Persist mentions.jsonl and attempts.jsonl using contract writers."""
        run_dir = self._get_run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        write_mentions_jsonl(run_dir / "mentions.jsonl", mentions)
        write_attempts_jsonl(run_dir / "attempts.jsonl", attempts)

    def get_attempts(
        self,
        run_id: str,
        company: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Read and filter attempts for a run."""
        attempts_path = self._get_run_dir(run_id) / "attempts.jsonl"
        if not attempts_path.is_file():
            return []

        results: List[Dict[str, Any]] = []
        with open(attempts_path, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if not line_str:
                    continue
                try:
                    att_dict = json.loads(line_str)
                    if company and att_dict.get("company", "").lower() != company.lower():
                        continue
                    if status and att_dict.get("status", "").lower() != status.lower():
                        continue
                    results.append(att_dict)
                except Exception:
                    continue
        return results

    def get_mentions(
        self,
        run_id: str,
        company: Optional[str] = None,
        platform: Optional[str] = None,
        method: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
        full: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Read, filter and paginate mentions for a run."""
        run_dir = self._get_run_dir(run_id)
        if not run_dir.exists():
            return None

        mentions_path = run_dir / "mentions.jsonl"
        raw_lines: List[Dict[str, Any]] = []
        if mentions_path.is_file():
            with open(mentions_path, "r", encoding="utf-8") as f:
                for line in f:
                    line_str = line.strip()
                    if not line_str:
                        continue
                    try:
                        raw_lines.append(json.loads(line_str))
                    except Exception:
                        continue

        # Filter
        filtered: List[Dict[str, Any]] = []
        for m in raw_lines:
            if company and m.get("company", "").lower() != company.lower():
                continue
            if platform and m.get("platform", "").lower() != platform.lower():
                continue
            if method and m.get("method_used", "").lower() != method.lower():
                continue
            filtered.append(m)

        total = len(filtered)
        pages = max(1, math.ceil(total / page_size)) if total > 0 else 1
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        sliced = filtered[start_idx:end_idx]

        if full:
            return {
                "items": sliced,
                "total": total,
                "page": page,
                "page_size": page_size,
                "pages": pages,
            }

        # Compact representation
        compact_items: List[Dict[str, Any]] = []
        for m in sliced:
            payload = m.get("raw_payload") or {}
            text = (
                payload.get("text")
                or payload.get("content")
                or payload.get("selftext")
                or payload.get("title")
                or ""
            )
            short_text = text[:150] + "..." if len(text) > 150 else text

            date_val = (
                payload.get("created_utc")
                or payload.get("date")
                or payload.get("pub_date")
                or payload.get("published")
                or m.get("collected_at")
            )

            fb = m.get("fallback_from")
            if hasattr(fb, "value"):
                fb_str = fb.value
            elif fb is not None:
                fb_str = str(fb)
            else:
                fb_str = None

            compact_items.append(
                {
                    "platform": m.get("platform", "other"),
                    "source": m.get("source", ""),
                    "date": str(date_val) if date_val is not None else None,
                    "short_text": short_text,
                    "url": m.get("url"),
                    "method": m.get("method_used", ""),
                    "cost": m.get("cost_usd", 0.0),
                    "fallback_from": fb_str,
                }
            )

        return {
            "items": compact_items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
        }

    def get_download_path(self, run_id: str, filename: str) -> Optional[Path]:
        """Return path to download file if valid."""
        if filename not in ("mentions.jsonl", "attempts.jsonl"):
            return None
        file_path = self._get_run_dir(run_id) / filename
        if file_path.is_file():
            return file_path
        return None


# Global singleton instance
run_store = RunStore()

