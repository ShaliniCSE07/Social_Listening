"""Collection Planner module.

Turns supported company inputs into CollectionRequest objects and executable tasks.
"""
import argparse
from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import yaml

from config.settings import load_companies
from src.collection.base import CollectionRequest
from src.collection.common.dates import to_utc
from src.collection.plugins.dataset.catalogue import load_dataset_catalogue
from src.collection.registry import get_all_connectors
from src.contracts.enums import Platform


@dataclass(frozen=True)
class Task:
    """Represents an atomic collection task for a company and platform/dataset."""

    company: str
    platform: Union[Platform, str]
    dataset_key: Optional[str] = field(default=None, compare=False)


@dataclass
class InvalidCompany:
    """Represents a company input record that failed validation."""

    name: str
    reasons: List[str] = field(default_factory=list)

    def __getitem__(self, item: str) -> Any:
        if item == "name":
            return self.name
        if item == "reasons":
            return self.reasons
        raise KeyError(item)

    def get(self, item: str, default: Any = None) -> Any:
        if item == "name":
            return self.name
        if item == "reasons":
            return self.reasons
        return default

    def keys(self) -> List[str]:
        return ["name", "reasons"]

    def __contains__(self, item: str) -> bool:
        return item in ("name", "reasons")


@dataclass
class Plan:
    """Complete collection plan containing requests, invalid items, notes, and tasks."""

    requests: List[CollectionRequest] = field(default_factory=list)
    invalid: List[InvalidCompany] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    tasks: List[Task] = field(default_factory=list)


REAL_PLATFORMS: Set[Platform] = {
    Platform.reddit,
    Platform.google,
    Platform.twitter_x,
    Platform.instagram,
    Platform.linkedin,
    Platform.facebook,
    Platform.news_blog,
}


def get_supported_platforms() -> List[Platform]:
    """Return real platforms supported by the registry's registered connectors."""
    platforms: List[Platform] = []
    seen: Set[Platform] = set()
    for conn in get_all_connectors():
        for p in getattr(conn, "platforms", []):
            if isinstance(p, Platform) and p in REAL_PLATFORMS and p != Platform.other and p not in seen:
                seen.add(p)
                platforms.append(p)
    return platforms


SHARED_FIELDS = (
    "platforms",
    "dataset_keys",
    "date_from",
    "date_to",
    "budget_usd",
    "scraping_allowed",
    "max_age_days",
    "require_fresh",
    "refresh",
    "run_id",
)


class Planner:
    """Transforms raw input configurations into structured collection plans."""

    def __init__(
        self,
        companies_path: Optional[Union[str, Path]] = None,
        catalogue: Optional[Dict[str, Any]] = None,
        supported_platforms: Optional[List[Platform]] = None,
    ):
        self.companies_path = Path(companies_path) if companies_path else None
        self._catalogue = catalogue
        self._supported_platforms = supported_platforms

    def _get_companies_config(self) -> Dict[str, Any]:
        if self.companies_path is not None:
            if not self.companies_path.is_file():
                return {}
            with open(self.companies_path, "r", encoding="utf-8-sig") as f:
                data = yaml.safe_load(f) or {}
            return data.get("companies", {})
        try:
            return load_companies()
        except Exception:
            return {}

    def _get_catalogue(self) -> Dict[str, Any]:
        if self._catalogue is not None:
            return self._catalogue
        try:
            return load_dataset_catalogue()
        except Exception:
            return {}

    def _get_default_platforms(self) -> List[Platform]:
        if self._supported_platforms is not None:
            return [p for p in self._supported_platforms if p in REAL_PLATFORMS and p != Platform.other]
        return get_supported_platforms()

    def plan(self, input_data: Union[str, Path, Dict[str, Any], List[Any]]) -> Plan:
        raw_data = self._load_raw_data(input_data)
        raw_companies, top_level_shared = self._extract_raw_companies(raw_data)

        companies_cfg = self._get_companies_config()
        catalogue = self._get_catalogue()
        default_platforms = self._get_default_platforms()

        valid_map: Dict[str, Dict[str, Any]] = {}
        invalid_list: List[InvalidCompany] = []
        notes: List[str] = []

        for raw in raw_companies:
            merged_raw = self._apply_top_level_defaults(raw, top_level_shared)
            is_valid, reasons, normalized = self._validate_and_normalize(
                merged_raw, catalogue, default_platforms
            )

            if not is_valid:
                raw_name = raw.get("company") if isinstance(raw, dict) else (raw if isinstance(raw, str) else "")
                if not raw_name and isinstance(raw, dict):
                    raw_name = raw.get("name", "")
                invalid_list.append(InvalidCompany(name=str(raw_name or "").strip(), reasons=reasons))
                continue

            # Fill missing attributes from companies.yaml if present
            self._fill_from_companies_yaml(normalized, companies_cfg)

            # Check duplicate merge (case-insensitive)
            key = normalized["company"].lower()
            if key in valid_map:
                existing = valid_map[key]
                self._merge_company_records(existing, normalized)
                notes.append(f"Merged duplicate company: {normalized['company']}")
            else:
                valid_map[key] = normalized

        # Construct final CollectionRequest and Task objects
        requests: List[CollectionRequest] = []
        tasks: List[Task] = []

        for comp_dict in valid_map.values():
            req = CollectionRequest(
                company=comp_dict["company"],
                alt_spellings=comp_dict.get("alt_spellings", []),
                handles=comp_dict.get("handles", []),
                branches=comp_dict.get("branches", []),
                platforms=comp_dict.get("platforms", []),
                date_from=comp_dict.get("date_from"),
                date_to=comp_dict.get("date_to"),
                run_id=comp_dict.get("run_id"),
                industry=comp_dict.get("industry"),
                scraping_allowed=comp_dict.get("scraping_allowed", False),
                budget_usd=comp_dict.get("budget_usd"),
                dataset_keys=comp_dict.get("dataset_keys"),
                max_age_days=comp_dict.get("max_age_days"),
                require_fresh=comp_dict.get("require_fresh", False),
                refresh=comp_dict.get("refresh", False),
            )
            requests.append(req)

            # Generate tasks: one Task(company, platform) per platform
            for p in req.platforms:
                tasks.append(Task(company=req.company, platform=p))

            # One Task(company, "dataset") for each selected dataset key
            if req.dataset_keys:
                seen_dkeys: Set[str] = set()
                for dkey in req.dataset_keys:
                    if dkey not in seen_dkeys:
                        seen_dkeys.add(dkey)
                        tasks.append(Task(company=req.company, platform="dataset", dataset_key=dkey))

        return Plan(
            requests=requests,
            invalid=invalid_list,
            notes=notes,
            tasks=tasks,
        )

    def _load_raw_data(self, input_data: Union[str, Path, Dict[str, Any], List[Any]]) -> Any:
        if isinstance(input_data, (str, Path)):
            path = Path(input_data)
            if path.is_file():
                content = path.read_text(encoding="utf-8-sig")
                if path.suffix.lower() == ".json":
                    return json.loads(content)
                elif path.suffix.lower() in (".yaml", ".yml"):
                    return yaml.safe_load(content)
                else:
                    try:
                        return json.loads(content)
                    except Exception:
                        return yaml.safe_load(content)
            elif isinstance(input_data, str):
                cleaned_str = input_data.lstrip("\ufeff")
                try:
                    return json.loads(cleaned_str)
                except Exception:
                    return yaml.safe_load(cleaned_str)

        return input_data

    def _extract_raw_companies(self, raw_data: Any) -> Tuple[List[Any], Dict[str, Any]]:
        top_level_shared: Dict[str, Any] = {}
        raw_list: List[Any] = []

        if isinstance(raw_data, list):
            return list(raw_data), top_level_shared

        if not isinstance(raw_data, dict):
            return [], top_level_shared

        for k in SHARED_FIELDS:
            if k in raw_data and raw_data[k] is not None:
                top_level_shared[k] = raw_data[k]

        # Shape c: industry-grouped list
        if "industries" in raw_data and isinstance(raw_data["industries"], dict):
            for industry_name, comp_items in raw_data["industries"].items():
                if isinstance(comp_items, list):
                    for item in comp_items:
                        if isinstance(item, str):
                            raw_list.append({"company": item, "industry": industry_name})
                        elif isinstance(item, dict):
                            record = dict(item)
                            record["industry"] = industry_name
                            raw_list.append(record)
            return raw_list, top_level_shared

        # Shape b: plain list under "companies"
        if "companies" in raw_data and isinstance(raw_data["companies"], list):
            for item in raw_data["companies"]:
                if isinstance(item, str):
                    raw_list.append({"company": item})
                elif isinstance(item, dict):
                    raw_list.append(dict(item))
            return raw_list, top_level_shared

        # Shape a: single company
        if "company" in raw_data or "name" in raw_data:
            return [dict(raw_data)], top_level_shared

        return raw_list, top_level_shared

    def _apply_top_level_defaults(self, raw: Any, top_level_shared: Dict[str, Any]) -> Dict[str, Any]:
        if isinstance(raw, str):
            res = {"company": raw}
        elif isinstance(raw, dict):
            res = dict(raw)
        else:
            return {"company": ""}

        for k, v in top_level_shared.items():
            if res.get(k) is None:
                res[k] = v

        return res

    def _validate_and_normalize(
        self,
        raw: Dict[str, Any],
        catalogue: Dict[str, Any],
        default_platforms: List[Platform],
    ) -> Tuple[bool, List[str], Dict[str, Any]]:
        reasons: List[str] = []
        normalized: Dict[str, Any] = {}

        # 1. Company Name validation
        raw_name = raw.get("company")
        if raw_name is None:
            raw_name = raw.get("name")

        if not raw_name or not str(raw_name).strip():
            reasons.append("Company name is missing or blank")
            name = ""
        else:
            name = str(raw_name).strip()

        normalized["company"] = name

        # 2. Industry
        ind = raw.get("industry")
        normalized["industry"] = str(ind).strip() if ind is not None and str(ind).strip() else None

        # 3. String list normalization: alt_spellings, handles, branches
        def _clean_str_list(val: Any) -> List[str]:
            if not val:
                return []
            if isinstance(val, str):
                val = [val]
            cleaned: List[str] = []
            seen: Set[str] = set()
            for item in val:
                if item and str(item).strip():
                    c = str(item).strip()
                    lower_c = c.lower()
                    if lower_c not in seen:
                        seen.add(lower_c)
                        cleaned.append(c)
            return cleaned

        normalized["alt_spellings"] = _clean_str_list(raw.get("alt_spellings"))
        normalized["handles"] = _clean_str_list(raw.get("handles"))
        normalized["branches"] = _clean_str_list(raw.get("branches"))

        # 4. Platforms validation and normalization
        raw_platforms = raw.get("platforms")
        valid_platforms: List[Platform] = []
        if raw_platforms is not None:
            if not isinstance(raw_platforms, (list, tuple)):
                raw_platforms = [raw_platforms]
            for p in raw_platforms:
                if isinstance(p, Platform):
                    valid_platforms.append(p)
                elif isinstance(p, str):
                    p_str = p.strip()
                    matched = None
                    for member in Platform:
                        if member.value == p_str.lower() or member.name == p_str.lower():
                            matched = member
                            break
                    if matched:
                        valid_platforms.append(matched)
                    else:
                        reasons.append(f"Unknown platform: '{p}'")
                else:
                    reasons.append(f"Unknown platform: '{p}'")

            # Deduplicate platforms
            dedup_platforms: List[Platform] = []
            seen_p: Set[Platform] = set()
            for p in valid_platforms:
                if p not in seen_p:
                    seen_p.add(p)
                    dedup_platforms.append(p)
            normalized["platforms"] = dedup_platforms if dedup_platforms else default_platforms
        else:
            normalized["platforms"] = default_platforms

        # 5. Dataset keys validation
        raw_dataset_keys = raw.get("dataset_keys")
        if raw_dataset_keys is not None:
            if not isinstance(raw_dataset_keys, (list, tuple)):
                raw_dataset_keys = [raw_dataset_keys]
            clean_dkeys: List[str] = []
            seen_dkeys: Set[str] = set()
            known_cat_keys = set(catalogue.keys())
            for dkey in raw_dataset_keys:
                d_str = str(dkey).strip()
                if d_str not in known_cat_keys:
                    reasons.append(f"Unknown dataset key: '{dkey}'")
                elif d_str not in seen_dkeys:
                    seen_dkeys.add(d_str)
                    clean_dkeys.append(d_str)
            normalized["dataset_keys"] = clean_dkeys
        else:
            normalized["dataset_keys"] = None

        # 6. Dates validation: date_from, date_to
        raw_date_from = raw.get("date_from")
        raw_date_to = raw.get("date_to")
        dt_from: Optional[datetime] = None
        dt_to: Optional[datetime] = None

        if raw_date_from is not None:
            dt_from = to_utc(raw_date_from)
            if dt_from is None:
                reasons.append(f"Invalid date_from: '{raw_date_from}'")
        if raw_date_to is not None:
            dt_to = to_utc(raw_date_to)
            if dt_to is None:
                reasons.append(f"Invalid date_to: '{raw_date_to}'")

        if dt_from and dt_to and dt_from > dt_to:
            reasons.append("date_from must not be after date_to")

        normalized["date_from"] = dt_from
        normalized["date_to"] = dt_to

        # 7. Budget validation
        raw_budget = raw.get("budget_usd")
        if raw_budget is not None:
            try:
                b_val = float(raw_budget)
                if b_val < 0:
                    reasons.append("Budget cannot be negative")
                normalized["budget_usd"] = b_val
            except (ValueError, TypeError):
                reasons.append(f"Invalid budget: '{raw_budget}'")
                normalized["budget_usd"] = None
        else:
            normalized["budget_usd"] = None

        # 8. Remaining flags and settings
        normalized["scraping_allowed"] = bool(raw.get("scraping_allowed", False))
        normalized["run_id"] = str(raw["run_id"]).strip() if raw.get("run_id") else None

        raw_max_age = raw.get("max_age_days")
        normalized["max_age_days"] = float(raw_max_age) if raw_max_age is not None else None
        normalized["require_fresh"] = bool(raw.get("require_fresh", False))
        normalized["refresh"] = bool(raw.get("refresh", False))

        is_valid = len(reasons) == 0
        return is_valid, reasons, normalized

    def _fill_from_companies_yaml(
        self, record: Dict[str, Any], companies_cfg: Dict[str, Any]
    ) -> None:
        if not companies_cfg:
            return

        target_name = record["company"].lower()
        matched_cfg: Optional[Dict[str, Any]] = None
        for name, cfg in companies_cfg.items():
            if name.strip().lower() == target_name and isinstance(cfg, dict):
                matched_cfg = cfg
                break

        if not matched_cfg:
            return

        # alt_spellings: fill only if missing/empty in record
        if not record.get("alt_spellings") and matched_cfg.get("alt_spellings"):
            record["alt_spellings"] = [
                str(s).strip() for s in matched_cfg["alt_spellings"] if str(s).strip()
            ]

        # handles: fill only if missing/empty in record
        if not record.get("handles") and matched_cfg.get("handles"):
            record["handles"] = [
                str(h).strip() for h in matched_cfg["handles"] if str(h).strip()
            ]

        # branches: fill only if missing/empty in record
        if not record.get("branches") and matched_cfg.get("branches"):
            record["branches"] = [
                str(b).strip() for b in matched_cfg["branches"] if str(b).strip()
            ]

        # industry: fill only if missing in record
        if not record.get("industry") and matched_cfg.get("industry"):
            record["industry"] = str(matched_cfg["industry"]).strip()

    def _merge_company_records(
        self, existing: Dict[str, Any], new: Dict[str, Any]
    ) -> None:
        # Merge alt_spellings
        seen_alt = {s.lower() for s in existing.get("alt_spellings", [])}
        for s in new.get("alt_spellings", []):
            if s.lower() not in seen_alt:
                seen_alt.add(s.lower())
                existing.setdefault("alt_spellings", []).append(s)

        # Merge handles
        seen_h = {h.lower() for h in existing.get("handles", [])}
        for h in new.get("handles", []):
            if h.lower() not in seen_h:
                seen_h.add(h.lower())
                existing.setdefault("handles", []).append(h)

        # Merge branches
        seen_b = {b.lower() for b in existing.get("branches", [])}
        for b in new.get("branches", []):
            if b.lower() not in seen_b:
                seen_b.add(b.lower())
                existing.setdefault("branches", []).append(b)

        # Merge platforms
        seen_p = set(existing.get("platforms", []))
        for p in new.get("platforms", []):
            if p not in seen_p:
                seen_p.add(p)
                existing.setdefault("platforms", []).append(p)

        # Merge dataset_keys
        if new.get("dataset_keys"):
            existing_dkeys = existing.get("dataset_keys") or []
            seen_d = set(existing_dkeys)
            for dk in new["dataset_keys"]:
                if dk not in seen_d:
                    seen_d.add(dk)
                    existing_dkeys.append(dk)
            existing["dataset_keys"] = existing_dkeys

        # Flags and optional fields: new values fill gaps or extend permissions
        if not existing.get("industry") and new.get("industry"):
            existing["industry"] = new["industry"]

        if existing.get("budget_usd") is None and new.get("budget_usd") is not None:
            existing["budget_usd"] = new["budget_usd"]

        if not existing.get("date_from") and new.get("date_from"):
            existing["date_from"] = new["date_from"]

        if not existing.get("date_to") and new.get("date_to"):
            existing["date_to"] = new["date_to"]

        if not existing.get("run_id") and new.get("run_id"):
            existing["run_id"] = new["run_id"]

        existing["scraping_allowed"] = existing.get("scraping_allowed", False) or new.get("scraping_allowed", False)
        existing["require_fresh"] = existing.get("require_fresh", False) or new.get("require_fresh", False)
        existing["refresh"] = existing.get("refresh", False) or new.get("refresh", False)


def plan(
    input_data: Union[str, Path, Dict[str, Any], List[Any]],
    companies_path: Optional[Union[str, Path]] = None,
    catalogue: Optional[Dict[str, Any]] = None,
    supported_platforms: Optional[List[Platform]] = None,
) -> Plan:
    """Convenience functional wrapper around Planner.plan."""
    planner = Planner(
        companies_path=companies_path,
        catalogue=catalogue,
        supported_platforms=supported_platforms,
    )
    return planner.plan(input_data)


create_plan = plan


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Social Listening Collection Planner CLI")
    parser.add_argument(
        "--input",
        "-i",
        required=True,
        help="Path to JSON or YAML input file describing targets and options",
    )
    args = parser.parse_args(argv)

    plan_obj = plan(args.input)

    print("=== Collection Plan ===")
    print(f"Valid Requests: {len(plan_obj.requests)}")
    for r in plan_obj.requests:
        ind_str = f" ({r.industry})" if r.industry else ""
        print(f"  * Company: {r.company}{ind_str}")
        plat_names = [p.value for p in r.platforms]
        print(f"    Platforms: {', '.join(plat_names)}")
        if r.dataset_keys:
            print(f"    Datasets: {', '.join(r.dataset_keys)}")
        if r.budget_usd is not None:
            print(f"    Budget: ${r.budget_usd:.2f}")
        if r.date_from or r.date_to:
            print(f"    Date Range: {r.date_from} to {r.date_to}")

    if plan_obj.invalid:
        print(f"\nInvalid Companies: {len(plan_obj.invalid)}")
        for inv in plan_obj.invalid:
            name_str = inv.name if inv.name else "<blank>"
            print(f"  * {name_str}:")
            for reason in inv.reasons:
                print(f"      - {reason}")

    if plan_obj.notes:
        print(f"\nNotes: {len(plan_obj.notes)}")
        for note in plan_obj.notes:
            print(f"  - {note}")

    print(f"\nTasks ({len(plan_obj.tasks)}):")
    for t in plan_obj.tasks:
        p_val = t.platform.value if isinstance(t.platform, Platform) else t.platform
        print(f"  - {t.company} -> {p_val}")

    if not plan_obj.requests:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
