"""Dataset Collection Plugin connector implementation."""
from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional, Tuple, Union

import requests

from config.settings import load_plugin_config
from src.collection.base import BaseConnector, CollectionRequest
from src.collection.common.dates import to_utc
from src.collection.common.text import matches_company
from src.collection.plugins.dataset.catalogue import (
    DatasetEntry,
    load_dataset_catalogue,
)
from src.collection.plugins.dataset.mapping import map_row, validate_mapping
from src.collection.plugins.dataset.sources.local import LocalFileSource
from src.collection.plugins.dataset.sources.url import UrlSource
from src.collection.plugins.dataset.sources.kaggle import KaggleSource
from src.contracts.enums import AttemptStatus, ContentType, Method, Platform
from src.contracts.schemas import CollectionAttempt, RawMention

logger = logging.getLogger(__name__)


class DatasetConnector(BaseConnector):
    """Offline & historical dataset collection connector."""

    method: ClassVar[Method] = Method.dataset
    name: ClassVar[str] = "dataset"
    platforms: ClassVar[List[Platform]] = [Platform.other]

    def __init__(
        self,
        catalogue: Optional[Dict[str, DatasetEntry]] = None,
        session: Optional[requests.Session] = None,
        download_dir: Optional[Union[str, Path]] = None,
        kaggle_api: Optional[Any] = None,
    ):
        cfg = load_plugin_config("dataset")
        self.default_max_age_days: Optional[float] = cfg.get("max_age_days")
        self._catalogue = catalogue
        self._session = session
        self._download_dir = Path(download_dir) if download_dir else None
        self._kaggle_api = kaggle_api

    def _get_catalogue(self) -> Dict[str, DatasetEntry]:
        if self._catalogue is not None:
            return self._catalogue
        return load_dataset_catalogue()

    def can_run(self, request: CollectionRequest) -> Tuple[bool, str]:
        if not request.company or not request.company.strip():
            return False, "Target company name is required"

        catalogue = self._get_catalogue()
        if not catalogue:
            return False, "Dataset catalogue is empty or missing"

        if request.dataset_keys:
            missing = [k for k in request.dataset_keys if k not in catalogue]
            if missing:
                return False, f"Requested dataset keys not found in catalogue: {missing}"

        return True, "OK"

    def estimate_cost(self, request: CollectionRequest) -> float:
        """Dataset collection is free ($0.0)."""
        return 0.0

    def collect(
        self, request: CollectionRequest
    ) -> Tuple[List[RawMention], Union[CollectionAttempt, List[CollectionAttempt]]]:
        started_at = datetime.now(timezone.utc)

        can_run, reason = self.can_run(request)
        if not can_run:
            finished_at = datetime.now(timezone.utc)
            att = CollectionAttempt(
                company=request.company,
                platform=Platform.other,
                method=self.method,
                status=AttemptStatus.failed,
                reason=reason,
                item_count=0,
                cost_usd=0.0,
                started_at=started_at,
                finished_at=finished_at,
            )
            return [], att

        catalogue = self._get_catalogue()

        if request.dataset_keys:
            selected_entries = [catalogue[k] for k in request.dataset_keys if k in catalogue]
        else:
            selected_entries = [entry for entry in catalogue.values() if entry.enabled]

        all_mentions: List[RawMention] = []
        attempts: List[CollectionAttempt] = []
        now_utc = datetime.now(timezone.utc)

        for entry in selected_entries:
            ds_start = datetime.now(timezone.utc)

            has_company_col = bool(entry.columns.get("company"))
            if not has_company_col and entry.default_company:
                req_companies = [request.company] + (request.alt_spellings or [])
                matches_default = any(
                    c.strip().lower() == entry.default_company.strip().lower()
                    for c in req_companies
                    if c and isinstance(c, str)
                )
                if not matches_default:
                    ds_finish = datetime.now(timezone.utc)
                    attempts.append(
                        CollectionAttempt(
                            company=request.company,
                            platform=Platform(entry.platform) if entry.platform in Platform.__members__ else Platform.other,
                            method=self.method,
                            status=AttemptStatus.empty,
                            reason=f"dataset is for {entry.default_company}",
                            item_count=0,
                            cost_usd=0.0,
                            started_at=ds_start,
                            finished_at=ds_finish,
                        )
                    )
                    continue

            last_updated_override: Optional[datetime] = None
            if entry.last_updated_override:
                last_updated_override = to_utc(entry.last_updated_override)

            # Determine source: url, kaggle or local
            is_url_source = entry.source_type.lower() == "url"
            is_kaggle_source = entry.source_type.lower() == "kaggle"
            download_note = ""
            basis_str = "catalogue_override" if last_updated_override else "file_modified_time"
            dataset_license = entry.license_note

            if is_kaggle_source:
                can_run_kaggle, kaggle_reason = KaggleSource.can_run()
                if not can_run_kaggle:
                    ds_finish = datetime.now(timezone.utc)
                    attempts.append(
                        CollectionAttempt(
                            company=request.company,
                            platform=Platform(entry.platform) if entry.platform in Platform.__members__ else Platform.other,
                            method=self.method,
                            status=AttemptStatus.skipped,
                            reason="Kaggle credentials missing",
                            item_count=0,
                            cost_usd=0.0,
                            started_at=ds_start,
                            finished_at=ds_finish,
                        )
                    )
                    continue

                kaggle_src_kwargs = {
                    "name": entry.name,
                    "key": entry.key,
                    "ref": entry.path_or_ref,
                    "file_format": entry.format,
                    "file_name": entry.file,
                    "license_note": entry.license_note,
                    "last_updated_override": last_updated_override,
                    "refresh": getattr(request, "refresh", False),
                    "api": self._kaggle_api,
                }
                if self._download_dir is not None:
                    kaggle_src_kwargs["download_dir"] = self._download_dir
                kaggle_src = KaggleSource(**kaggle_src_kwargs)
                try:
                    _, was_downloaded = kaggle_src.download_if_needed()
                    download_note = "downloaded from Kaggle" if was_downloaded else "reused local copy"
                except Exception as dl_err:
                    ds_finish = datetime.now(timezone.utc)
                    reason_msg = kaggle_src.format_error_reason(dl_err)
                    if entry.license_note:
                        reason_msg += f" (License: {entry.license_note})"
                    attempts.append(
                        CollectionAttempt(
                            company=request.company,
                            platform=Platform(entry.platform) if entry.platform in Platform.__members__ else Platform.other,
                            method=self.method,
                            status=AttemptStatus.failed,
                            reason=reason_msg,
                            item_count=0,
                            cost_usd=0.0,
                            started_at=ds_start,
                            finished_at=ds_finish,
                        )
                    )
                    continue

                source = kaggle_src
                info = kaggle_src.describe()
                last_updated = info.last_updated
                if info.license:
                    dataset_license = info.license
                basis_str = "kaggle_metadata"
            elif is_url_source:
                url_src_kwargs = {
                    "name": entry.name,
                    "key": entry.key,
                    "url_or_ref": entry.path_or_ref,
                    "file_format": entry.format,
                    "license_note": entry.license_note,
                    "last_updated_override": last_updated_override,
                    "refresh": getattr(request, "refresh", False),
                    "session": self._session,
                }
                if self._download_dir is not None:
                    url_src_kwargs["download_dir"] = self._download_dir
                url_src = UrlSource(**url_src_kwargs)
                try:
                    _, was_downloaded = url_src.download_if_needed()
                    download_note = "downloaded from URL" if was_downloaded else "reused local copy"
                except Exception as dl_err:
                    ds_finish = datetime.now(timezone.utc)
                    reason_msg = f"Failed to download dataset {entry.name}: {dl_err}"
                    if entry.license_note:
                        reason_msg += f" (License: {entry.license_note})"
                    attempts.append(
                        CollectionAttempt(
                            company=request.company,
                            platform=Platform(entry.platform) if entry.platform in Platform.__members__ else Platform.other,
                            method=self.method,
                            status=AttemptStatus.failed,
                            reason=reason_msg,
                            item_count=0,
                            cost_usd=0.0,
                            started_at=ds_start,
                            finished_at=ds_finish,
                        )
                    )
                    continue

                source = url_src
                last_updated, basis_str = url_src.get_last_updated_and_basis()
            else:
                source = LocalFileSource(
                    name=entry.name,
                    path=Path(entry.path_or_ref),
                    file_format=entry.format,
                    license_note=entry.license_note,
                    last_updated_override=last_updated_override,
                )
                info = source.describe()
                last_updated = info.last_updated

            # Freshness check
            max_age_days = (
                request.max_age_days
                if request.max_age_days is not None
                else self.default_max_age_days
            )

            if request.require_fresh and max_age_days is not None and max_age_days > 0:
                last_updated_utc = to_utc(last_updated) or now_utc
                age_days = (now_utc - last_updated_utc).total_seconds() / 86400.0
                if age_days > max_age_days:
                    ds_finish = datetime.now(timezone.utc)
                    reason_msg = f"dataset older than {max_age_days} days"
                    if download_note:
                        reason_msg = f"{download_note}; {reason_msg}"
                    if entry.license_note:
                        reason_msg += f" (License: {entry.license_note})"

                    attempts.append(
                        CollectionAttempt(
                            company=request.company,
                            platform=Platform(entry.platform) if entry.platform in Platform.__members__ else Platform.other,
                            method=self.method,
                            status=AttemptStatus.skipped,
                            reason=reason_msg,
                            item_count=0,
                            cost_usd=0.0,
                            started_at=ds_start,
                            finished_at=ds_finish,
                        )
                    )
                    continue

            # Stream rows
            ds_mentions: List[RawMention] = []
            try:
                row_iterator = source.iter_rows()
            except Exception as e:
                ds_finish = datetime.now(timezone.utc)
                reason_msg = f"Failed to open dataset {entry.name}: {e}"
                if download_note:
                    reason_msg = f"{download_note}; {reason_msg}"
                if entry.license_note:
                    reason_msg += f" (License: {entry.license_note})"
                attempts.append(
                    CollectionAttempt(
                        company=request.company,
                        platform=Platform(entry.platform) if entry.platform in Platform.__members__ else Platform.other,
                        method=self.method,
                        status=AttemptStatus.failed,
                        reason=reason_msg,
                        item_count=0,
                        cost_usd=0.0,
                        started_at=ds_start,
                        finished_at=ds_finish,
                    )
                )
                continue

            first_row = True
            row_num = 0
            read_error: Optional[str] = None
            row_errors = 0
            date_parse_warnings = 0
            has_date_filter = bool(request.date_from or request.date_to)
            filter_date_from = to_utc(request.date_from) if request.date_from else None
            filter_date_to = to_utc(request.date_to) if request.date_to else None

            try:
                for raw_row in row_iterator:
                    if raw_row.get("_error"):
                        row_errors += 1
                        continue

                    row_num += 1
                    if first_row:
                        validation_err = validate_mapping(raw_row, entry.columns)
                        if validation_err:
                            read_error = validation_err
                            break
                        first_row = False

                    try:
                        mapped = map_row(raw_row, entry.columns)

                        # Match determination:
                        # 1. Mapped company column wins and default_company is ignored
                        # 2. default_company: all rows belong to default_company
                        # 3. Neither exists: match company name in text
                        if has_company_col:
                            company_val = mapped.get("company")
                            if not matches_company(
                                str(company_val) if company_val is not None else "",
                                request.company,
                                request.alt_spellings,
                                request.handles,
                            ):
                                continue
                            match_basis = "company_column"
                        elif entry.default_company:
                            match_basis = "default_company"
                        else:
                            text_val = mapped.get("text") or ""
                            if not matches_company(
                                str(text_val),
                                request.company,
                                request.alt_spellings,
                                request.handles,
                            ):
                                continue
                            match_basis = "text_mention"

                        payload = dict(raw_row)

                        if has_date_filter:
                            row_dt = to_utc(mapped.get("date"))
                            if row_dt:
                                if filter_date_from and row_dt < filter_date_from:
                                    continue
                                if filter_date_to and row_dt > filter_date_to:
                                    continue
                            else:
                                # Date could not be parsed — keep the row but warn
                                date_parse_warnings += 1
                                payload["date_parse_warning"] = True

                        payload["dataset_key"] = entry.key
                        payload["dataset_last_updated"] = last_updated.isoformat()
                        payload["dataset_last_updated_basis"] = basis_str
                        payload["dataset_row_number"] = row_num
                        payload["dataset_match_basis"] = match_basis
                        if dataset_license:
                            payload["dataset_license"] = dataset_license

                        item_id_val = mapped.get("id")
                        item_id = str(item_id_val).strip() if item_id_val is not None and str(item_id_val).strip() else None

                        url_val = mapped.get("url")
                        url = str(url_val) if url_val is not None else None

                        branch_val = mapped.get("branch")
                        branch = str(branch_val) if branch_val is not None else None

                        plat_enum = (
                            Platform(entry.platform)
                            if entry.platform in Platform.__members__
                            else Platform.other
                        )
                        content_type_enum = (
                            ContentType(entry.content_type)
                            if entry.content_type in ContentType.__members__
                            else ContentType.post
                        )

                        mention = RawMention(
                            schema_version="1.0",
                            company=request.company,
                            run_id=request.run_id,
                            platform=plat_enum,
                            item_id=item_id,
                            url=url,
                            branch=branch,
                            content_type_hint=content_type_enum,
                            raw_payload=payload,
                            source=entry.name,
                            method_used=self.method,
                            tool_used=f"Dataset: {entry.name}",
                            fallback_from=None,
                            cost_usd=0.0,
                            collected_at=now_utc,
                        )
                        ds_mentions.append(mention)

                    except Exception as row_err:
                        row_errors += 1
                        logger.debug("Row %d error in %s: %s", row_num, entry.name, row_err)

            except Exception as iter_err:
                read_error = f"Error reading dataset row {row_num}: {iter_err}"

            ds_finish = datetime.now(timezone.utc)
            status: AttemptStatus
            reason_parts: List[str] = []

            if download_note:
                reason_parts.append(download_note)

            decode_errors = getattr(source, "decode_errors", 0)

            if read_error:
                status = AttemptStatus.failed
                reason_parts.append(read_error)
            elif row_num == 0 and decode_errors > 0:
                status = AttemptStatus.failed
                reason_parts.append(f"Failed to read dataset {entry.name}: file is unreadable ({decode_errors} bad rows had decode errors)")
            elif not ds_mentions:
                status = AttemptStatus.empty
                reason_parts.append(f"No matching mentions in dataset {entry.name}")
            else:
                status = AttemptStatus.success
                reason_parts.append(f"Collected {len(ds_mentions)} mentions from dataset {entry.name}")

            if decode_errors > 0:
                reason_parts.append(f"{decode_errors} bad rows had decode errors")

            if row_errors > 0:
                reason_parts.append(f"{row_errors} rows had errors")

            if date_parse_warnings > 0:
                reason_parts.append(f"{date_parse_warnings} rows had unreadable dates")

            final_license = dataset_license or entry.license_note
            if final_license:
                reason_parts.append(f"License: {final_license}")

            final_reason = "; ".join(reason_parts)

            attempts.append(
                CollectionAttempt(
                    company=request.company,
                    platform=Platform(entry.platform) if entry.platform in Platform.__members__ else Platform.other,
                    method=self.method,
                    status=status,
                    reason=final_reason,
                    item_count=len(ds_mentions),
                    cost_usd=0.0,
                    started_at=ds_start,
                    finished_at=ds_finish,
                )
            )
            all_mentions.extend(ds_mentions)

        return all_mentions, (attempts[0] if len(attempts) == 1 else attempts)  # type: ignore[return-value]
