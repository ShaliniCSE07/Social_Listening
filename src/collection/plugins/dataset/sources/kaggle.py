"""Kaggle dataset source reader using the official Kaggle client."""
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import tempfile
from typing import Any, Dict, Iterator, Optional, Tuple, Union
import zipfile

from config.settings import load_plugin_config
from src.collection.plugins.dataset.sources.base import DatasetInfo, DatasetSource
from src.collection.plugins.dataset.sources.local import LocalFileSource

logger = logging.getLogger(__name__)


def parse_date_safely(date_val: Any) -> Optional[datetime]:
    """Parse date representations to a UTC timezone-aware datetime."""
    if date_val is None:
        return None
    if isinstance(date_val, (int, float)):
        try:
            return datetime.fromtimestamp(float(date_val), tz=timezone.utc)
        except Exception:
            return None
    date_str = str(date_val).strip()
    if not date_str:
        return None
    try:
        dt = datetime.fromisoformat(date_str)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        for fmt in (
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%d-%m-%Y",
            "%d/%m/%Y",
            "%Y-%m-%d %H:%M:%S",
        ):
            try:
                dt = datetime.strptime(date_str, fmt)
                return dt.replace(tzinfo=timezone.utc)
            except Exception:
                continue
    return None


def sanitize_text(text: str) -> str:
    """Ensure credentials never appear in messages or logs."""
    key = os.environ.get("KAGGLE_KEY", "").strip()
    if key and key in text:
        text = text.replace(key, "[REDACTED]")
    username = os.environ.get("KAGGLE_USERNAME", "").strip()
    if username and username in text:
        text = text.replace(username, "[REDACTED_USER]")
    return text


class KaggleSource(DatasetSource):
    """Downloads Kaggle datasets and streams data rows from them."""

    def __init__(
        self,
        name: str,
        key: str,
        ref: str,
        file_format: str,
        file_name: Optional[str] = None,
        license_note: Optional[str] = None,
        last_updated_override: Optional[datetime] = None,
        refresh: bool = False,
        download_dir: Optional[Union[str, Path]] = None,
        api: Optional[Any] = None,
    ):
        self.name = name
        self.key = key
        self.raw_ref = ref.strip()
        self.file_format = file_format.lower()
        self.license_note = license_note
        self.last_updated_override = last_updated_override
        self.refresh = refresh
        self._api = api

        # Parse dataset ref and optional file name from ref
        # e.g., "owner/dataset" or "owner/dataset/file.csv"
        parts = [p for p in self.raw_ref.strip("/").split("/") if p]
        if len(parts) >= 3:
            self.dataset_ref = f"{parts[0]}/{parts[1]}"
            self.file_name = file_name or "/".join(parts[2:])
        elif len(parts) == 2:
            self.dataset_ref = f"{parts[0]}/{parts[1]}"
            self.file_name = file_name
        else:
            self.dataset_ref = self.raw_ref
            self.file_name = file_name

        cfg = load_plugin_config("dataset")
        base_dl_dir = download_dir or Path(cfg.get("download_dir", "data/datasets/_downloads"))
        self.target_dir = Path(base_dl_dir) / key
        self.target_dir.mkdir(parents=True, exist_ok=True)

        self._meta_last_updated: Optional[datetime] = None
        self._meta_license: Optional[str] = None
        self._local_file_path: Optional[Path] = None

    @staticmethod
    def can_run() -> Tuple[bool, str]:
        """Check whether required Kaggle environment variables are present."""
        username = os.environ.get("KAGGLE_USERNAME", "").strip()
        key = os.environ.get("KAGGLE_KEY", "").strip()
        if not username or not key:
            return False, "Kaggle credentials missing"
        return True, "OK"

    def _get_api(self) -> Any:
        if self._api is not None:
            return self._api

        # Isolate config dir to avoid sandbox permission errors with ~/.kaggle
        if "KAGGLE_CONFIG_DIR" not in os.environ:
            cfg_dir = Path(tempfile.gettempdir()) / "kaggle_config"
            cfg_dir.mkdir(parents=True, exist_ok=True)
            os.environ["KAGGLE_CONFIG_DIR"] = str(cfg_dir)

        try:
            from kaggle.api.kaggle_api_extended import KaggleApi

            api = KaggleApi()
            api.authenticate()
            self._api = api
            return self._api
        except Exception as e:
            logger.error("Failed to authenticate Kaggle API: %s", sanitize_text(str(e)))
            raise

    def get_file_path(self) -> Optional[Path]:
        """Find local downloaded dataset file in target_dir."""
        if self._local_file_path and self._local_file_path.is_file():
            return self._local_file_path

        # If explicit file_name is configured
        if self.file_name:
            exact = self.target_dir / self.file_name
            if exact.is_file():
                self._local_file_path = exact
                return exact
            target_name = Path(self.file_name).name.lower()
            for p in self.target_dir.rglob("*"):
                if p.is_file() and p.name.lower() == target_name:
                    self._local_file_path = p
                    return p

        # Otherwise look for any matching data file
        fmt = self.file_format.lower()
        candidates = [
            p
            for p in self.target_dir.rglob("*")
            if p.is_file()
            and not p.name.endswith(".meta")
            and not p.name.endswith(".tmp")
            and not p.name.endswith(".zip")
            and p.name != "dataset-metadata.json"
        ]

        matching_fmt = [p for p in candidates if p.suffix.lower() == f".{fmt}"]
        if matching_fmt:
            self._local_file_path = matching_fmt[0]
            return matching_fmt[0]

        if candidates:
            self._local_file_path = candidates[0]
            return candidates[0]

        return None

    def fetch_metadata(self) -> Tuple[Optional[datetime], Optional[str]]:
        """Query dataset metadata from Kaggle client."""
        api = self._get_api()
        dt: Optional[datetime] = None
        lic: Optional[str] = None

        # 1. Try dataset_list(search=...)
        if hasattr(api, "dataset_list"):
            try:
                results = api.dataset_list(search=self.dataset_ref)
                if results:
                    target_ref = self.dataset_ref.lower()
                    match = next(
                        (d for d in results if getattr(d, "ref", "").lower() == target_ref),
                        results[0],
                    )
                    raw_dt = getattr(match, "last_updated", None) or getattr(match, "lastUpdated", None)
                    if raw_dt:
                        dt = raw_dt if isinstance(raw_dt, datetime) else parse_date_safely(raw_dt)
                    lic = getattr(match, "license_name", None) or getattr(match, "licenseName", None)
            except Exception as e:
                logger.debug("dataset_list error: %s", sanitize_text(str(e)))

        # 2. Try direct get_dataset or dataset_view if available
        if (not dt or not lic) and hasattr(api, "get_dataset"):
            try:
                ds = api.get_dataset(self.dataset_ref)
                if ds:
                    if not dt:
                        raw_dt = getattr(ds, "last_updated", None) or getattr(ds, "lastUpdated", None)
                        if raw_dt:
                            dt = raw_dt if isinstance(raw_dt, datetime) else parse_date_safely(raw_dt)
                    if not lic:
                        lic = getattr(ds, "license_name", None) or getattr(ds, "licenseName", None) or getattr(ds, "license", None)
            except Exception as e:
                logger.debug("get_dataset error: %s", sanitize_text(str(e)))

        # 3. Try dataset_metadata
        if (not dt or not lic) and hasattr(api, "dataset_metadata"):
            try:
                meta_path = api.dataset_metadata(self.dataset_ref, str(self.target_dir))
                if meta_path and Path(meta_path).is_file():
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta_data = json.load(f)
                        if not lic:
                            lics = meta_data.get("licenses", [])
                            if lics and isinstance(lics, list) and isinstance(lics[0], dict):
                                lic = lics[0].get("name")
                        if not dt:
                            raw_dt = meta_data.get("last_updated") or meta_data.get("lastUpdated")
                            if raw_dt:
                                dt = parse_date_safely(raw_dt)
            except Exception as e:
                logger.debug("dataset_metadata error: %s", sanitize_text(str(e)))

        if isinstance(dt, datetime):
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)

        return dt, lic

    def download_if_needed(self) -> Tuple[Path, bool]:
        """Download Kaggle dataset files if missing or refresh=True."""
        meta_file = self.target_dir / "_kaggle.meta"
        cached = self.get_file_path()

        if cached and not self.refresh:
            if meta_file.is_file():
                try:
                    with open(meta_file, "r", encoding="utf-8") as f:
                        for line in f.read().splitlines():
                            if line.startswith("last_updated="):
                                val = line.split("=", 1)[1].strip()
                                if val:
                                    self._meta_last_updated = datetime.fromisoformat(val)
                            elif line.startswith("license="):
                                val = line.split("=", 1)[1].strip()
                                if val:
                                    self._meta_license = val
                except Exception:
                    pass
            return cached, False

        api = self._get_api()
        try:
            meta_dt, meta_lic = self.fetch_metadata()
            if meta_dt:
                self._meta_last_updated = meta_dt
            if meta_lic:
                self._meta_license = meta_lic
        except Exception:
            pass

        try:
            if self.file_name and hasattr(api, "dataset_download_file"):
                api.dataset_download_file(
                    dataset=self.dataset_ref,
                    file_name=self.file_name,
                    path=str(self.target_dir),
                    force=self.refresh,
                    quiet=True,
                    unzip=True,
                )
            elif hasattr(api, "dataset_download_files"):
                api.dataset_download_files(
                    dataset=self.dataset_ref,
                    path=str(self.target_dir),
                    force=self.refresh,
                    quiet=True,
                    unzip=True,
                )
        except Exception as exc:
            raise exc

        # Unpack any downloaded zip files
        for zpath in list(self.target_dir.glob("*.zip")):
            try:
                with zipfile.ZipFile(zpath, "r") as zf:
                    zf.extractall(self.target_dir)
            except Exception:
                pass

        downloaded_file = self.get_file_path()
        if not downloaded_file or not downloaded_file.is_file():
            raise FileNotFoundError(
                f"Kaggle download did not produce expected file in {self.target_dir}"
            )

        try:
            with open(meta_file, "w", encoding="utf-8") as f:
                if self._meta_last_updated:
                    f.write(f"last_updated={self._meta_last_updated.isoformat()}\n")
                if self._meta_license:
                    f.write(f"license={self._meta_license}\n")
                f.write(f"download_time={datetime.now(timezone.utc).isoformat()}\n")
                if self.file_name:
                    f.write(f"file_name={self.file_name}\n")
        except Exception:
            pass

        return downloaded_file, True

    def get_last_updated_and_license(self) -> Tuple[datetime, Optional[str]]:
        if self._meta_last_updated:
            dt = self._meta_last_updated
        elif self.last_updated_override:
            dt = self.last_updated_override
        else:
            p = self.get_file_path()
            if p and p.is_file():
                dt = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
            else:
                dt = datetime.now(timezone.utc)

        lic = self._meta_license or self.license_note
        return dt, lic

    def describe(self) -> DatasetInfo:
        last_updated, lic = self.get_last_updated_and_license()
        return DatasetInfo(
            name=self.name,
            source_type="kaggle",
            last_updated=last_updated,
            row_count=None,
            license=lic,
        )

    def iter_rows(self) -> Iterator[Dict[str, Any]]:
        file_path = self.get_file_path()
        if not file_path or not file_path.is_file():
            raise FileNotFoundError(f"Kaggle dataset file not found in {self.target_dir}")
        local_src = LocalFileSource(
            name=self.name,
            path=file_path,
            file_format=self.file_format,
            license_note=self.license_note,
            last_updated_override=self.last_updated_override,
        )
        yield from local_src.iter_rows()

    def format_error_reason(self, exc: Exception) -> str:
        msg = str(exc)
        err_lower = msg.lower()
        if (
            "401" in err_lower
            or "403" in err_lower
            or "unauthorized" in err_lower
            or "forbidden" in err_lower
        ):
            reason = f"Kaggle authentication failed or access forbidden (401/403) for dataset: {self.dataset_ref}"
        elif "terms" in err_lower or "accept" in err_lower:
            reason = f"Kaggle terms of use not accepted for dataset: {self.dataset_ref}"
        elif "404" in err_lower or "not found" in err_lower:
            reason = f"Kaggle dataset not found: {self.dataset_ref}"
        elif "429" in err_lower or "rate limit" in err_lower:
            reason = "Kaggle rate limit exceeded (429)"
        elif "timeout" in err_lower or "timed out" in err_lower:
            reason = "Kaggle request timed out"
        else:
            reason = f"Failed to download Kaggle dataset {self.dataset_ref}: {msg}"
        return sanitize_text(reason)

