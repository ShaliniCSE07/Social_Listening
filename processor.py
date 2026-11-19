from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime, timezone

from masker import mask_text
from models import (
    CollectionAttempt,
    Method,
    Platform,
    RawMention,
    SoclRecord,
)
from pseudonym import pseudonymize_author
from storage import get_db


def _mention_id(platform: str, item_id: str | None, raw: dict, text: str, posted: datetime | None) -> str:
    if item_id:
        h = hashlib.sha256(f"{platform}:{item_id}".encode()).hexdigest()
    else:
        norm = f"{text}|{posted.isoformat() if posted else ''}|{platform}"
        h = hashlib.sha256(norm.encode()).hexdigest()
    return f"m_{h[:12]}"


def _fingerprint(text: str, posted: datetime | None) -> str:
    norm = f"{text}|{posted.isoformat() if posted else ''}"
    return hashlib.sha256(norm.encode()).hexdigest()


# ---- Payload field names per source ----------------------------------------
# Checked in order; the first non-empty value wins. The original keys come
# first so existing payloads map exactly as before.
_TEXT_KEYS = (
    "body", "selftext", "text", "content",          # reddit / generic
    "review_text", "review_description", "review",  # datasets
    "comment", "title",                              # titles: link posts, HN stories
)
_AUTHOR_KEYS = (
    "author", "user", "username", "userName", "authorAttribution",
    "reviewerName",                                  # TripAdvisor (RapidAPI)
)
_DATE_KEYS = (
    "updated", "created", "created_utc", "published",
    "publishTime",                                   # Google Places
    "publishedAt",                                   # TripAdvisor (RapidAPI)
    "review_date", "date", "at",                     # datasets
)
_LIKE_KEYS = ("score", "likes", "ups", "points")
_COMMENT_KEYS = ("num_comments", "comments_count", "comment_count")
_SHARE_KEYS = ("shares", "share_count")
_VIEW_KEYS = ("views", "view_count")

# Datasets whose rows were tied to the company by the dataset itself, not by
# the text (see Member 1's dataset connector, raw_payload.dataset_match_basis).
_SOURCE_MATCH_BASES = {"company_column", "default_company"}
# Reviews read from the company's own page on a review site (e.g. its
# TripAdvisor page) are about the company even when the text never names it.
_PAGE_MATCH_BASES = {"place_page"}

_catalogue_cache: dict | None = None
_aliases_cache: dict | None = None


def _dataset_columns(payload: dict) -> dict:
    """Column map for a dataset row, from config/plugins/dataset_catalogue.yaml."""
    global _catalogue_cache
    key = payload.get("dataset_key")
    if not key:
        return {}
    if _catalogue_cache is None:
        try:
            from config.settings import load_plugin_config
            _catalogue_cache = load_plugin_config("dataset_catalogue").get("datasets", {}) or {}
        except Exception:
            _catalogue_cache = {}
    entry = _catalogue_cache.get(key) or {}
    return entry.get("columns") or {}


def _company_aliases(company: str) -> tuple[list[str], list[str]]:
    """(names incl. alt spellings, handles) for a company, from config/companies.yaml."""
    global _aliases_cache
    if _aliases_cache is None:
        try:
            from config.settings import load_companies
            _aliases_cache = {k.lower(): (v or {}) for k, v in load_companies().items()}
        except Exception:
            _aliases_cache = {}
    cfg = _aliases_cache.get(company.lower(), {})
    names = [company] + [a for a in (cfg.get("alt_spellings") or []) if a]
    handles = [h for h in (cfg.get("handles") or []) if h]
    return names, handles


def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def _as_text(v) -> str | None:
    """Strings as-is; Google-style {"text": "..."} / {"displayName": "..."} unwrapped."""
    if isinstance(v, dict):
        v = v.get("text") or v.get("displayName")
    if _blank(v):
        return None
    return v if isinstance(v, str) else str(v)


def _first(p: dict, keys, column: str | None = None):
    if column and not _blank(p.get(column)):
        return p.get(column)
    for k in keys:
        if not _blank(p.get(k)):
            return p.get(k)
    return None


def _to_float(v) -> float | None:
    if _blank(v) or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_int(v) -> int | None:
    f = _to_float(v)
    return int(f) if f is not None else None


def _to_utc(v) -> datetime | None:
    """ISO strings, 'YYYY-MM-DD HH:MM:SS', epoch seconds; naive values are UTC."""
    if _blank(v):
        return None
    try:
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return datetime.fromtimestamp(float(v), tz=timezone.utc)
        if isinstance(v, datetime):
            dt = v
        else:
            dt = datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError, OSError):
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _map_from_payload(raw: RawMention) -> dict:
    """Map platform-specific fields to standard fields; return None-filled when missing.

    Values are read as received: empty strings count as missing, and numbers
    that arrive as strings ("5") are converted; unreadable values become None.
    """
    p = raw.raw_payload
    cols = _dataset_columns(p)

    text = _as_text(_first(p, _TEXT_KEYS, cols.get("text"))) or ""
    author_handle = _as_text(_first(p, _AUTHOR_KEYS, cols.get("author")))
    posted_at = _to_utc(_first(p, _DATE_KEYS, cols.get("date")))

    return {
        "text": text.strip(),
        "author_handle": author_handle,
        "posted_at": posted_at,
        "url": raw.url or _as_text(p.get(cols.get("url") or "url")),
        "branch": raw.branch or _as_text(_first(p, ("branch", "place"), cols.get("branch"))),
        "reactions": {
            "likes": _to_int(_first(p, _LIKE_KEYS)),
            "comments": _to_int(_first(p, _COMMENT_KEYS)),
            "shares": _to_int(_first(p, _SHARE_KEYS)),
            "views": _to_int(_first(p, _VIEW_KEYS)),
        },
        "rating": _to_float(_first(p, ("rating",), cols.get("rating"))),
        "language": _as_text(p.get("language") or p.get("lang")),
        "place": _as_text(p.get("place") or p.get("place_name")),
    }


def _company_match(company: str, text: str, payload: dict) -> tuple[str | None, str]:
    """Return (mention_type, company_match), or (None, "") when the text is not about the company.

    Text matches use the company name, its alt spellings and its handles from
    config/companies.yaml. Dataset rows that the dataset itself tied to the
    company (company column or default_company) are kept even when the text
    does not name it, e.g. app-store reviews ("Great app, fast delivery").
    """
    low = text.lower()
    names, handles = _company_aliases(company)
    if any(h.lower() in low for h in handles):
        return "tags the account", "confirmed"
    if any(n.lower() in low for n in names):
        return "names company directly", "confirmed"
    if payload.get("dataset_match_basis") in _SOURCE_MATCH_BASES:
        return "identified by source", "source"
    if payload.get("source_match_basis") in _PAGE_MATCH_BASES:
        return "identified by source", "source"
    return None, ""


def process_mentions(
    mentions: list[RawMention],
    attempts: list[CollectionAttempt],
    run_id: str,
    company_industry: dict[str, str | None],
    load_type: str,
    windows: dict[tuple[str, str], dict] | None = None,
) -> dict:
    """
    Input: Member 1 handoff files (parsed lists) + run_id + company industry mapping
    Output: {"records": [...], "inserted": ..., "updated": ..., "report": {...}, "counters": {...}}
    """
    db = get_db()
    grouped: dict[str, list[RawMention]] = defaultdict(list)
    for m in mentions:
        grouped[m.company].append(m)

    all_records: list[SoclRecord] = []
    counters = {
        "collected": 0,
        "duplicates": 0,
        "updated": 0,
        "wrong_company": 0,
        "suppressed": 0,
        "quarantined": 0,
        "incomplete": 0,
    }
    seen: set[str] = set()

    for company, raw_list in grouped.items():
        company_id = f"c_{hashlib.sha256(company.encode()).hexdigest()[:10]}"
        industry = company_industry.get(company)

        for raw in raw_list:
            counters["collected"] += 1
            mapped = _map_from_payload(raw)

            # ---- FR-PRC-03: clean ----
            text = mapped["text"]
            if not text:
                counters["quarantined"] += 1
                continue

            # ---- FR-PRC-05: deduplicate (platform item ID > URL > text+date) ----
            dedup_key = raw.item_id or mapped["url"] or _fingerprint(text, mapped["posted_at"])
            if dedup_key in seen:
                counters["duplicates"] += 1
                continue
            seen.add(dedup_key)

            # ---- FR-PRC-06: company matching (name, alt spellings, handles, or dataset tag) ----
            mention_type, company_match = _company_match(company, text, raw.raw_payload)
            if mention_type is None:
                # Here can further match with handles/aliases; example simplified: if no match,
                # count as wrong company and drop (production should use two thresholds)
                counters["wrong_company"] += 1
                continue

            # ---- FR-PRC-08: masking ----
            masked_text, mask_ok = mask_text(text)
            if not mask_ok:
                counters["quarantined"] += 1
                continue

            # ---- D9: author pseudonymization ----
            author_pseudo = pseudonymize_author(raw.platform.value, mapped["author_handle"])

            # ---- FR-PRC-09: labelling ----
            content_type = raw.content_type_hint.value if raw.content_type_hint else "post"

            # ---- FR-PRC-10: completeness ----
            incomplete = []
            if not mapped["url"]:
                incomplete.append("url")
            if not mapped["posted_at"]:
                incomplete.append("posted_at")
            if incomplete:
                counters["incomplete"] += 1

            # ---- Build record ----
            # Rows without a platform ID are identified by text + date; passing "" here
            # gave every same-day dataset review the same ID, so they overwrote each other.
            mid = _mention_id(raw.platform.value, raw.item_id, raw.raw_payload, text, mapped["posted_at"])
            record_id = f"{mid}:{company_id}"

            # Check existing record in DB for version history (FR-DLT-08)
            existing = db.records.find_one({"record_id": record_id}, sort=[("version", -1)])
            if existing:
                if existing.get("text") == masked_text:
                    counters["duplicates"] += 1
                    continue
                else:
                    is_update = True
                    version = existing.get("version", 1) + 1
                    supersedes = f"{record_id}:v{existing.get('version', 1)}"
                    counters["updated"] += 1
            else:
                is_update = False
                version = 1
                supersedes = None

            rec = SoclRecord(
                record_id=record_id,
                mention_id=mid,
                company=company,
                company_id=company_id,
                industry=industry,
                platform=raw.platform,
                content_type=content_type,
                mention_type=mention_type,
                branch=mapped["branch"],
                text=masked_text,
                url=mapped["url"],
                author=author_pseudo,
                posted_at=mapped["posted_at"],
                reactions=mapped["reactions"],
                rating=mapped["rating"],
                language=mapped["language"],
                place=mapped["place"],
                source=raw.source,
                method_used=raw.method_used,
                tool_used=raw.tool_used,
                fallback_from=raw.fallback_from,
                cost_usd=raw.cost_usd,
                collected_at=raw.collected_at,
                run_id=run_id,
                load_type=(windows or {}).get((company, raw.platform.value), {}).get("load_type", load_type),
                is_update=is_update,
                fingerprint=_fingerprint(str(raw.raw_payload.get("body") or "") + str(raw.raw_payload.get("updated") or ""), mapped.get("posted_at")),
                version=version,
                supersedes=supersedes,
                incomplete=incomplete,
                company_match=company_match,
            )
            all_records.append(rec)

    # ---- Save (FR-PRC-12) — idempotent per record (PRD NFR-IDM) ----
    inserted = 0
    if all_records:
        from pymongo.errors import DuplicateKeyError
        for r in all_records:
            try:
                db.records.insert_one(r.model_dump(mode="json"))
                inserted += 1
            except DuplicateKeyError:
                counters["duplicates"] += 1

    # ---- Run report (FR-RPT-01/02) ----
    report = _build_report(attempts, counters, all_records)

    return {
        "records": all_records,
        "inserted": inserted,
        "updated": counters["updated"],
        "report": report,
        "counters": counters,
    }


def _build_report(attempts: list[CollectionAttempt], counters: dict, records: list[SoclRecord]) -> dict:
    by_company_platform = defaultdict(lambda: {"attempts": [], "record_count": 0})
    for a in attempts:
        key = (a.company, a.platform.value)
        by_company_platform[key]["attempts"].append(
            {
                "method": a.method.value,
                "status": a.status.value,
                "reason": a.reason,
                "item_count": a.item_count,
                "cost_usd": a.cost_usd,
            }
        )
    for r in records:
        key = (r.company, r.platform.value)
        by_company_platform[key]["record_count"] += 1

    total_cost = sum(a.cost_usd for a in attempts)
    return {
        "counters": counters,
        "total_cost_usd": total_cost,
        "by_company_platform": [
            {"company": k[0], "platform": k[1], **v}
            for k, v in by_company_platform.items()
        ],
    }
