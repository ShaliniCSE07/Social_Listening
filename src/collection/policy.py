"""Source policy model and loader.

Loads and validates data-driven source selection rules from config/plugins/source_policy.yaml.
Also provides helpers to load per-site scraping permissions from config/plugins/scraping_sites.yaml.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import yaml

from config.settings import CONFIG_DIR

_SCRAPING_SITES_PATH = CONFIG_DIR / "plugins" / "scraping_sites.yaml"

VALID_METHODS = {"api", "dataset", "scraping"}
VALID_COST_CLASSES = {"free", "paid", "approval"}
VALID_ROLES = {"first_choice", "backup"}
VALID_CANDIDATE_KEYS = {"connector", "method", "cost_class", "role", "available", "notes"}
VALID_TOP_LEVEL_KEYS = {"platforms", "scraping"}


@dataclass
class PolicyCandidate:
    """A configured candidate connector for a platform."""

    connector: str
    method: str
    cost_class: str
    role: str
    available: bool = True
    notes: Optional[str] = None


@dataclass
class ScrapingPolicy:
    """Scraping configuration rules and thresholds."""

    allows_scraping: bool = False
    allowed_sites: List[str] = field(default_factory=list)
    min_results_threshold: int = 5


@dataclass
class SourcePolicy:
    """Complete source policy configuration."""

    platforms: Dict[str, List[PolicyCandidate]] = field(default_factory=dict)
    scraping: ScrapingPolicy = field(default_factory=ScrapingPolicy)

    def get_candidates(self, platform: str) -> List[PolicyCandidate]:
        """Return candidate list for a given platform name, or empty list."""
        key = str(platform).lower()
        if key in self.platforms:
            return self.platforms[key]
        if key == "dataset" and "history_baseline" in self.platforms:
            return self.platforms["history_baseline"]
        if "other" in self.platforms:
            return self.platforms["other"]
        return []


def load_source_policy(path: Optional[Union[str, Path]] = None) -> SourcePolicy:
    """Load and strictly validate source policy configuration."""
    if path is not None:
        policy_file = Path(path)
    else:
        policy_file = CONFIG_DIR / "plugins" / "source_policy.yaml"

    if not policy_file.is_file():
        raise FileNotFoundError(f"Source policy file not found: {policy_file}")

    with open(policy_file, "r", encoding="utf-8-sig") as f:
        data = yaml.safe_load(f) or {}

    if not isinstance(data, dict):
        raise ValueError("Source policy root must be a dictionary")

    # Validate top-level keys
    for k in data.keys():
        if k not in VALID_TOP_LEVEL_KEYS:
            raise ValueError(f"Unknown top-level key '{k}' in source policy file")

    raw_platforms = data.get("platforms", {})
    if not isinstance(raw_platforms, dict):
        raise ValueError("'platforms' section must be a dictionary of platform candidate lists")

    parsed_platforms: Dict[str, List[PolicyCandidate]] = {}

    for plat_name, candidates in raw_platforms.items():
        if not isinstance(candidates, list):
            raise ValueError(f"Candidates for platform '{plat_name}' must be a list")

        plat_candidates: List[PolicyCandidate] = []
        for idx, item in enumerate(candidates):
            if not isinstance(item, dict):
                raise ValueError(
                    f"Candidate {idx} for platform '{plat_name}' must be a dictionary"
                )

            # Check unknown keys in candidate
            for c_key in item.keys():
                if c_key not in VALID_CANDIDATE_KEYS:
                    raise ValueError(
                        f"Unknown key '{c_key}' in candidate {idx} for platform '{plat_name}'"
                    )

            # Required fields
            for req in ("connector", "method", "cost_class", "role"):
                if req not in item:
                    raise ValueError(
                        f"Missing required field '{req}' in candidate {idx} for platform '{plat_name}'"
                    )

            method = str(item["method"]).lower().strip()
            if method not in VALID_METHODS:
                raise ValueError(
                    f"Unknown method '{item['method']}' in candidate for platform '{plat_name}'. "
                    f"Expected one of {sorted(VALID_METHODS)}"
                )

            cost_class = str(item["cost_class"]).lower().strip()
            if cost_class not in VALID_COST_CLASSES:
                raise ValueError(
                    f"Unknown cost_class '{item['cost_class']}' in candidate for platform '{plat_name}'. "
                    f"Expected one of {sorted(VALID_COST_CLASSES)}"
                )

            role = str(item["role"]).lower().strip()
            if role not in VALID_ROLES:
                raise ValueError(
                    f"Unknown role '{item['role']}' in candidate for platform '{plat_name}'. "
                    f"Expected one of {sorted(VALID_ROLES)}"
                )

            candidate_obj = PolicyCandidate(
                connector=str(item["connector"]).strip(),
                method=method,
                cost_class=cost_class,
                role=role,
                available=bool(item.get("available", True)),
                notes=item.get("notes"),
            )
            plat_candidates.append(candidate_obj)

        parsed_platforms[str(plat_name).lower()] = plat_candidates

    # Parse scraping section
    raw_scraping = data.get("scraping", {})
    if not isinstance(raw_scraping, dict):
        raise ValueError("'scraping' section must be a dictionary")

    for s_key in raw_scraping.keys():
        if s_key not in ("allows_scraping", "allowed_sites", "min_results_threshold"):
            raise ValueError(f"Unknown key '{s_key}' in scraping policy section")

    scraping_obj = ScrapingPolicy(
        allows_scraping=bool(raw_scraping.get("allows_scraping", False)),
        allowed_sites=list(raw_scraping.get("allowed_sites", [])),
        min_results_threshold=int(raw_scraping.get("min_results_threshold", 5)),
    )

    return SourcePolicy(platforms=parsed_platforms, scraping=scraping_obj)


def load_scraping_sites_cfg(path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """Load the scraping sites YAML config and return it as a dict keyed by site key.

    Each value is a dict with at minimum 'platform' and 'allows_scraping' fields.
    Returns an empty dict if the file is missing (graceful degradation).
    """
    sites_file = Path(path) if path is not None else _SCRAPING_SITES_PATH
    if not sites_file.is_file():
        return {}
    with open(sites_file, "r", encoding="utf-8-sig") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        return {}
    return data


def platform_has_scrapable_site(platform_str: str, sites_cfg: Dict[str, Any]) -> bool:
    """Return True if any site in sites_cfg has the given platform and allows_scraping=True.

    Args:
        platform_str: Platform name string (e.g. 'news_blog', 'reddit').
        sites_cfg: Dict returned by load_scraping_sites_cfg().
    """
    for _key, site in sites_cfg.items():
        if not isinstance(site, dict):
            continue
        if str(site.get("platform", "")).lower() == platform_str.lower():
            if bool(site.get("allows_scraping", False)):
                return True
    return False

