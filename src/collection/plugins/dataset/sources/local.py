"""Local file source reader for CSV, JSON, and JSONL formats."""
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from src.collection.common.dates import to_utc
from src.collection.plugins.dataset.sources.base import DatasetInfo, DatasetSource


def get_file_encoding(path: Path) -> str:
    """Return 'utf-8-sig' if file starts with a UTF-8 BOM, otherwise 'utf-8'."""
    try:
        with open(path, "rb") as f:
            if f.read(3) == b"\xef\xbb\xbf":
                return "utf-8-sig"
    except Exception:
        pass
    return "utf-8"


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
        self.decode_errors: int = 0

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

        self.decode_errors = 0
        encoding = get_file_encoding(self.path)

        if self.file_format == "csv":
            try:
                with open(self.path, "rb") as f:
                    first_line = f.readline()
                    if not first_line:
                        return
                    try:
                        header_line = first_line.decode(encoding)
                    except UnicodeDecodeError as ude:
                        raise ValueError(f"Failed to read CSV dataset: file header could not be decoded as UTF-8 ({ude})") from ude

                    def _line_generator():
                        yield header_line
                        for raw_line in f:
                            try:
                                decoded_line = raw_line.decode(encoding)
                                yield decoded_line
                            except UnicodeDecodeError:
                                self.decode_errors += 1
                                continue

                    reader = csv.DictReader(_line_generator())
                    for row in reader:
                        yield dict(row)
            except Exception as e:
                if isinstance(e, FileNotFoundError):
                    raise
                if "could not be decoded" in str(e) or "Failed to read CSV dataset" in str(e):
                    raise
                raise ValueError(f"Failed to read CSV dataset: {e}") from e

        elif self.file_format == "jsonl":
            try:
                with open(self.path, "rb") as f:
                    first_line = True
                    for raw_line in f:
                        line_enc = encoding if first_line else "utf-8"
                        try:
                            line_str = raw_line.decode(line_enc).strip()
                        except UnicodeDecodeError:
                            self.decode_errors += 1
                            continue
                        finally:
                            first_line = False

                        if line_str:
                            try:
                                item = json.loads(line_str)
                                if isinstance(item, dict):
                                    yield item
                                else:
                                    yield {"_error": f"JSONL row is not an object: {type(item)}"}
                            except Exception as e:
                                yield {"_error": f"Corrupt JSON line: {e}"}
            except Exception as e:
                if isinstance(e, FileNotFoundError):
                    raise
                raise ValueError(f"Failed to read JSONL dataset: {e}") from e

        elif self.file_format == "json":
            try:
                with open(self.path, "r", encoding=encoding) as f:
                    data = json.load(f)
            except UnicodeDecodeError as ude:
                raise ValueError(f"Failed to decode JSON dataset {self.name}: file is unreadable ({ude})") from ude
            except Exception as e:
                if isinstance(e, FileNotFoundError):
                    raise
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
