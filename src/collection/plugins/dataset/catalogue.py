"""Dataset catalogue loader and model definitions."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional
import yaml

from config.settings import CONFIG_DIR


@dataclass
class DatasetEntry:
    key: str
    name: str
    source_type: str
    path_or_ref: str
    format: str
    platform: str
    content_type: str
    enabled: bool = True
    columns: Dict[str, str] = field(default_factory=dict)
    license_note: Optional[str] = None
    last_updated_override: Optional[str] = None


def load_dataset_catalogue(path: Optional[Path] = None) -> Dict[str, DatasetEntry]:
    """Load dataset catalogue entries from YAML configuration."""
    cat_path = path or (CONFIG_DIR / "plugins" / "dataset_catalogue.yaml")
    if not cat_path.is_file():
        return {}

    with open(cat_path, "r", encoding="utf-8-sig") as f:
        data = yaml.safe_load(f) or {}

    raw_datasets = data.get("datasets", {})
    catalogue: Dict[str, DatasetEntry] = {}

    for key, val in raw_datasets.items():
        if not isinstance(val, dict):
            continue
        catalogue[key] = DatasetEntry(
            key=key,
            name=val.get("name", key),
            source_type=val.get("source_type", "local"),
            path_or_ref=val.get("path_or_ref", ""),
            format=val.get("format", "csv").lower(),
            platform=val.get("platform", "other").lower(),
            content_type=val.get("content_type", "post").lower(),
            enabled=bool(val.get("enabled", True)),
            columns=val.get("columns", {}) or {},
            license_note=val.get("license_note"),
            last_updated_override=val.get("last_updated_override"),
        )

    return catalogue

