"""File-based cache for collection results."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


def normalize_query(query: str) -> str:
    """Normalize query text for cache key hashing."""
    return " ".join(query.strip().lower().split())


def compute_cache_key(
    connector_name: str,
    query: str,
    parameters: Optional[Dict[str, Any]] = None,
) -> str:
    """Generate SHA256 hex digest for (connector_name, normalized_query, parameters)."""
    norm_conn = connector_name.strip().lower()
    norm_q = normalize_query(query)
    params_repr = json.dumps(parameters or {}, sort_keys=True, default=str)
    raw = f"{norm_conn}::{norm_q}::{params_repr}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ResultCache:
    """File-based cache under data/cache/."""

    def __init__(self, cache_dir: Optional[Union[str, Path]] = None):
        if cache_dir is not None:
            self.cache_dir = Path(cache_dir)
        else:
            self.cache_dir = Path("data/cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _file_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def get(self, key: str, max_age_days: Optional[float] = None) -> Optional[List[Dict[str, Any]]]:
        """Retrieve items from cache if present and not expired."""
        path = self._file_path(key)
        if not path.is_file():
            return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            stored_at_str = data.get("stored_at")
            if not stored_at_str:
                return None

            stored_at = datetime.fromisoformat(stored_at_str)
            if stored_at.tzinfo is None:
                stored_at = stored_at.replace(tzinfo=timezone.utc)

            if max_age_days is not None and max_age_days > 0:
                now = datetime.now(timezone.utc)
                age = now - stored_at
                if age.total_seconds() > max_age_days * 86400:
                    return None

            items = data.get("items")
            if isinstance(items, list):
                return items
            return None
        except Exception:
            return None

    def put(self, key: str, items: List[Any]) -> None:
        """Store items in cache with stored_at UTC timestamp."""
        path = self._file_path(key)
        now_str = datetime.now(timezone.utc).isoformat()
        payload = {
            "key": key,
            "stored_at": now_str,
            "items": items,
        }
        temp_path = self.cache_dir / f"{key}.tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, default=str)
        temp_path.replace(path)

