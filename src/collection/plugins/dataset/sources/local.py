"""Local file source reader for CSV, JSON, and JSONL formats."""
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

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
            last_updated = self.last_updated_override
        elif self.path.is_file():
            mtime = self.path.stat().st_mtime
            last_updated = datetime.fromtimestamp(mtime, tz=timezone.utc)
        else:
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
            with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    yield dict(row)

        elif self.file_format == "jsonl":
            with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line_str = line.strip()
                    if line_str:
                        yield json.loads(line_str)

        elif self.file_format == "json":
            with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                data = json.load(f)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            yield item
                elif isinstance(data, dict):
                    # Check common array wrappers or single record
                    records = data.get("rows") or data.get("data") or data.get("items")
                    if isinstance(records, list):
                        for item in records:
                            if isinstance(item, dict):
                                yield item
                    else:
                        yield data
        else:
            raise ValueError(f"Unsupported dataset format: {self.file_format}")

