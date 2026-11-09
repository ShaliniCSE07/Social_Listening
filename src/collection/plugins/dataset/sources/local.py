"""Local file source reader for CSV, JSON, and JSONL formats."""
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from src.collection.common.dates import to_utc
from src.collection.plugins.dataset.sources.base import DatasetInfo, DatasetSource


class LocalFileSource(DatasetSource):
    """Streams data rows from local files (CSV, JSON, JSONL)."""

    def __init__(
        self,
        name: str,
        path: Path,
        file_format: str,
        license_note: Optional[str] = None,
        last_updated_override: Optional[datetime] = None,
    ):
        self.name = name
        self.path = Path(path)
        self.file_format = file_format.lower()
        self.license_note = license_note
        self.last_updated_override = last_updated_override

    def describe(self) -> DatasetInfo:
        if self.last_updated_override:
            last_updated = to_utc(self.last_updated_override)
        elif self.path.is_file():
            mtime = self.path.stat().st_mtime
            last_updated = to_utc(mtime)
        else:
            last_updated = datetime.now(timezone.utc)

        if last_updated is None:
            last_updated = datetime.now(timezone.utc)

        return DatasetInfo(
            name=self.name,
            source_type="local",
            last_updated=last_updated,
            row_count=None,
            license=self.license_note,
        )

    def iter_rows(self) -> Iterator[Dict[str, Any]]:
        if not self.path.is_file():
            raise FileNotFoundError(f"Dataset file not found: {self.path}")

        if self.file_format == "csv":
            try:
                with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        yield dict(row)
            except Exception as e:
                if isinstance(e, FileNotFoundError):
                    raise
                raise ValueError(f"Failed to read CSV dataset: {e}") from e

        elif self.file_format == "jsonl":
            with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line_str = line.strip()
                    if line_str:
                        try:
                            item = json.loads(line_str)
                            if isinstance(item, dict):
                                yield item
                            else:
                                yield {"_error": f"JSONL row is not an object: {type(item)}"}
                        except Exception as e:
                            yield {"_error": f"Corrupt JSON line: {e}"}

        elif self.file_format == "json":
            try:
                with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                    data = json.load(f)
            except Exception as e:
                raise ValueError(f"Failed to parse JSON dataset: {e}") from e

            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        yield item
                    else:
                        yield {"_error": f"JSON array element is not an object: {type(item)}"}
            elif isinstance(data, dict):
                records = data.get("rows") or data.get("data") or data.get("items")
                if isinstance(records, list):
                    for item in records:
                        if isinstance(item, dict):
                            yield item
                        else:
                            yield {"_error": f"JSON array element is not an object: {type(item)}"}
                else:
                    yield data
            else:
                raise ValueError(f"JSON dataset root must be array or object, got {type(data)}")
        else:
            raise ValueError(f"Unsupported dataset format: {self.file_format}")
