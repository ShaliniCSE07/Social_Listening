"""Configuration query endpoints for available sources and datasets."""
import os
from typing import List
from fastapi import APIRouter

from config.settings import load_plugin_config
from src.collection.base import CollectionRequest
from src.collection.plugins.dataset.catalogue import load_dataset_catalogue
from src.collection.registry import get_all_connectors
from src.contracts.enums import Method
from src.service.models import DatasetConfigItem, ScrapingSiteConfigItem, SourceConfigItem

router = APIRouter(prefix="/api/config", tags=["config"])


def _redact_secrets(text: str) -> str:
    """Extra guarantee that secret keys/tokens never appear in responses."""
    import os

    for env_var in (
        "REDDIT_CLIENT_SECRET",
        "GOOGLE_PLACES_API_KEY",
        "KAGGLE_KEY",
        "HUGGINGFACE_TOKEN",
    ):
        secret = os.environ.get(env_var, "").strip()
        if secret and secret in text:
            text = text.replace(secret, "[REDACTED]")
    return text


@router.get("/sources", response_model=List[SourceConfigItem])
def get_sources() -> List[SourceConfigItem]:
    """Return available methods and connectors with enabled and can_run statuses."""
    items: List[SourceConfigItem] = []
    dummy_request = CollectionRequest(company="ProbeCompany", scraping_allowed=True)

    for cls in get_all_connectors():
        try:
            conn = cls()
            conn_name = getattr(conn, "name", cls.__name__)
            conn_method = getattr(conn, "method", Method.api)
            conn_platforms = getattr(conn, "platforms", [])

            # Check configuration for enabled status
            method_str = conn_method.value if hasattr(conn_method, "value") else str(conn_method)
            cfg = load_plugin_config(method_str)
            enabled = bool(cfg.get("enabled", True))

            # Check can_run
            try:
                can_run, raw_reason = conn.can_run(dummy_request)
            except Exception as e:
                can_run, raw_reason = False, f"Check failed: {e}"

            sanitized_reason = _redact_secrets(raw_reason)

            items.append(
                SourceConfigItem(
                    name=conn_name,
                    method=method_str,
                    platforms=[p.value if hasattr(p, "value") else str(p) for p in conn_platforms],
                    enabled=enabled,
                    can_run=bool(can_run),
                    reason=sanitized_reason,
                )
            )
        except Exception:
            continue

    return items


@router.get("/datasets", response_model=List[DatasetConfigItem])
def get_datasets() -> List[DatasetConfigItem]:
    """Return all catalogue entries for historical/offline datasets."""
    catalogue = load_dataset_catalogue()
    items: List[DatasetConfigItem] = []

    for key, entry in catalogue.items():
        items.append(
            DatasetConfigItem(
                key=entry.key,
                name=entry.name,
                source_type=entry.source_type,
                enabled=entry.enabled,
                last_updated=entry.last_updated_override,
                license_note=entry.license_note,
            )
        )

    return items


@router.get("/scraping-sites", response_model=List[ScrapingSiteConfigItem])
def get_scraping_sites() -> List[ScrapingSiteConfigItem]:
    """Return per-site scraping configuration.

    Reads config/plugins/scraping_sites.yaml via the existing loader.
    Never returns secret values or start_urls or policy details.
    Returns an empty list when the file is missing or empty.
    """
    raw: dict = load_plugin_config("scraping_sites")
    if not raw:
        return []

    contact_set: bool = bool(os.environ.get("SCRAPER_CONTACT", "").strip())
    items: List[ScrapingSiteConfigItem] = []

    for key, site in raw.items():
        if not isinstance(site, dict):
            continue

        allows: bool = bool(site.get("allows_scraping", False))

        # Determine can_run and reason without exposing any secret value
        if not allows:
            can_run = False
            reason = "scraping not allowed for this site"
        elif not contact_set:
            can_run = False
            reason = "SCRAPER_CONTACT not set"
        else:
            can_run = True
            reason = ""

        items.append(
            ScrapingSiteConfigItem(
                key=str(site.get("key", key)),
                name=str(site.get("name", key)),
                platform=str(site.get("platform", "")),
                allows_scraping=allows,
                license_note=site.get("license_note") or None,
                attribution=site.get("attribution") or None,
                can_run=can_run,
                reason=reason,
            )
        )

    return items

