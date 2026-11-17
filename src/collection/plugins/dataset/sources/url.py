"""URL dataset source reader with download, caching, extraction, and HF support."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import logging
import os
from pathlib import Path
import time
from typing import Any, Dict, Iterator, Optional, Tuple
import zipfile

import requests

from config.settings import load_plugin_config
from src.collection.common.dates import to_utc
from src.collection.common.http import get_session
from src.collection.plugins.dataset.sources.base import DatasetInfo, DatasetSource
from src.collection.plugins.dataset.sources.local import LocalFileSource

logger = logging.getLogger(__name__)


def resolve_url(path_or_ref: str) -> str:
    """Resolve URL or Hugging Face ref (hf://dataset_id/filename.ext)."""
    ref = path_or_ref.strip()
    if ref.startswith("hf://"):
        # Format: hf://<dataset_id>/<filename> e.g. hf://username/dataset/data.csv
        parts = ref[5:].split("/", 2)
        if len(parts) == 3:
            repo_owner, repo_name, filename = parts
            repo_id = f"{repo_owner}/{repo_name}"
            return f"https://huggingface.co/datasets/{repo_id}/resolve/main/{filename}"
        elif len(parts) == 2:
            repo_id, filename = parts
            return f"https://huggingface.co/datasets/{repo_id}/resolve/main/{filename}"
        else:
            raise ValueError(f"Invalid Hugging Face reference: {ref}")
    return ref


class UrlSource(DatasetSource):
    """Downloads dataset files over HTTPS into a local directory and reads them."""

    def __init__(
        self,
        name: str,
        key: str,
        url_or_ref: str,
        file_format: str,
        license_note: Optional[str] = None,
        last_updated_override: Optional[datetime] = None,
        refresh: bool = False,
        session: Optional[requests.Session] = None,
        download_dir: Optional[Path] = None,
    ):
        self.name = name
        self.key = key
        self.raw_ref = url_or_ref
        self.resolved_url = resolve_url(url_or_ref)
        self.file_format = file_format.lower()
        self.license_note = license_note
        self.last_updated_override = last_updated_override
        self.refresh = refresh

        cfg = load_plugin_config("dataset")
        self.max_download_mb: float = float(cfg.get("max_download_mb", 200.0))
        self.max_unpacked_mb: float = float(cfg.get("max_unpacked_mb", 400.0))
        self.request_timeout: int = int(cfg.get("request_timeout", 30))
        self.max_retries: int = int(cfg.get("max_retries", 2))

        base_dl_dir = download_dir or Path(cfg.get("download_dir", "data/datasets/_downloads"))
        self.target_dir = Path(base_dl_dir) / key
        self.target_dir.mkdir(parents=True, exist_ok=True)

        self._session = session or get_session(max_retries=0)
        self._download_performed: bool = False
        self._last_modified_header_dt: Optional[datetime] = None
        self._download_time: Optional[datetime] = None
        self._local_file_path: Optional[Path] = None
        self._local_source: Optional[LocalFileSource] = None

    def _get_hf_token(self) -> Optional[str]:
        tok = os.environ.get("HUGGINGFACE_TOKEN", "").strip()
        return tok or None

    def _find_cached_file(self) -> Optional[Path]:
        """Find non-meta downloaded file in target_dir."""
        for p in self.target_dir.glob("*"):
            if p.is_file() and not p.name.endswith(".meta") and not p.name.endswith(".tmp"):
                return p
        return None

    def download_if_needed(self) -> Tuple[Path, bool]:
        """Download file if not present or refresh is True."""
        cached = self._find_cached_file()
        meta_file = self.target_dir / "_download.meta"

        if cached and not self.refresh:
            self._local_file_path = cached
            if meta_file.is_file():
                try:
                    with open(meta_file, "r", encoding="utf-8") as f:
                        lines = f.read().splitlines()
                        for line in lines:
                            if line.startswith("last_modified="):
                                lm_str = line.split("=", 1)[1].strip()
                                if lm_str:
                                    self._last_modified_header_dt = to_utc(lm_str)
                            elif line.startswith("download_time="):
                                dt_str = line.split("=", 1)[1].strip()
                                if dt_str:
                                    self._download_time = to_utc(dt_str)
                except Exception:
                    pass
            return cached, False

        # Download with retry
        headers = {}
        token = self._get_hf_token()
        if token and ("huggingface.co" in self.resolved_url or self.raw_ref.startswith("hf://")):
            headers["Authorization"] = f"Bearer {token}"

        resp: Optional[requests.Response] = None
        for attempt_idx in range(self.max_retries + 1):
            try:
                resp = self._session.get(
                    self.resolved_url,
                    headers=headers,
                    stream=True,
                    timeout=self.request_timeout,
                )

                if resp.status_code in (403, 404):
                    raise requests.HTTPError(
                        f"HTTP {resp.status_code} client error downloading dataset: {self.name}"
                    )

                if resp.status_code >= 500:
                    if attempt_idx < self.max_retries:
                        time.sleep(0.5 * (2**attempt_idx))
                        continue
                    raise requests.HTTPError(
                        f"HTTP {resp.status_code} server error downloading dataset: {self.name}"
                    )

                resp.raise_for_status()
                break
            except (requests.Timeout, requests.ConnectionError) as net_err:
                if attempt_idx < self.max_retries:
                    time.sleep(0.5 * (2**attempt_idx))
                    continue
                raise TimeoutError(f"Network error downloading dataset: {net_err.__class__.__name__}")

        if resp is None:
            raise requests.RequestException("No response received")

        # Check Last-Modified header
        lm_header = resp.headers.get("Last-Modified")
        if lm_header:
            try:
                self._last_modified_header_dt = parsedate_to_datetime(lm_header).astimezone(timezone.utc)
            except Exception:
                self._last_modified_header_dt = None

        self._download_time = datetime.now(timezone.utc)

        # Stream download & enforce max_download_mb
        max_bytes = self.max_download_mb * 1024 * 1024
        downloaded_bytes = 0

        # Determine target filename
        filename = self.resolved_url.rstrip("/").split("/")[-1].split("?")[0]
        if not filename:
            filename = f"dataset.{self.file_format}"

        download_target = self.target_dir / filename
        temp_target = self.target_dir / f"{filename}.tmp"

        try:
            with open(temp_target, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    if chunk:
                        downloaded_bytes += len(chunk)
                        if downloaded_bytes > max_bytes:
                            raise ValueError(
                                f"Dataset file size exceeded maximum limit of {self.max_download_mb} MB"
                            )
                        f.write(chunk)
        except Exception:
            temp_target.unlink(missing_ok=True)
            raise

        if download_target.exists():
            download_target.unlink()
        temp_target.replace(download_target)

        # Handle zip extraction if applicable
        final_path = download_target
        max_unpacked_bytes = self.max_unpacked_mb * 1024 * 1024
        if self.file_format == "zip" or download_target.suffix.lower() == ".zip":
            oversized = False
            with zipfile.ZipFile(download_target, "r") as zf:
                total_uncompressed = sum(info.file_size for info in zf.infolist())
                if total_uncompressed > max_unpacked_bytes:
                    oversized = True
                else:
                    zf.extractall(self.target_dir)

            if oversized:
                download_target.unlink(missing_ok=True)
                raise ValueError(
                    f"Unpacked dataset size exceeded maximum limit of {self.max_unpacked_mb} MB"
                )

            # Find extracted data file
            extracted_files = [
                p
                for p in self.target_dir.glob("*")
                if p.is_file() and p.suffix.lower() in (".csv", ".json", ".jsonl")
            ]
            if not extracted_files:
                raise ValueError("Zip archive did not contain any CSV, JSON, or JSONL files")
            final_path = extracted_files[0]
        else:
            if download_target.stat().st_size > max_unpacked_bytes:
                download_target.unlink(missing_ok=True)
                raise ValueError(
                    f"Unpacked dataset size exceeded maximum limit of {self.max_unpacked_mb} MB"
                )

        # Write metadata
        with open(meta_file, "w", encoding="utf-8") as f:
            if self._last_modified_header_dt:
                f.write(f"last_modified={self._last_modified_header_dt.isoformat()}\n")
            if self._download_time:
                f.write(f"download_time={self._download_time.isoformat()}\n")

        self._download_performed = True
        self._local_file_path = final_path
        return final_path, True

    def get_last_updated_and_basis(self) -> Tuple[datetime, str]:
        """Determine last_updated timestamp and its basis."""
        if self._last_modified_header_dt:
            return self._last_modified_header_dt, "http_last_modified"
        if self.last_updated_override:
            return self.last_updated_override, "catalogue_override"
        if self._download_time:
            return self._download_time, "unknown source date"
        return datetime.now(timezone.utc), "unknown source date"

    def describe(self) -> DatasetInfo:
        last_updated, _ = self.get_last_updated_and_basis()
        return DatasetInfo(
            name=self.name,
            source_type="url",
            last_updated=last_updated,
            row_count=None,
            license=self.license_note,
        )

    def iter_rows(self) -> Iterator[Dict[str, Any]]:
        path, _ = self.download_if_needed()

        ext = path.suffix.lstrip(".").lower()
        effective_format = ext if ext in ("csv", "json", "jsonl") else self.file_format
        if effective_format == "zip":
            effective_format = "csv"

        self._local_source = LocalFileSource(
            name=self.name,
            path=path,
            file_format=effective_format,
            license_note=self.license_note,
        )
        yield from self._local_source.iter_rows()

    @property
    def decode_errors(self) -> int:
        if self._local_source is not None:
            return self._local_source.decode_errors
        return 0

