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


def _map_from_payload(raw: RawMention) -> dict:
    """Map platform-specific fields to standard fields; return None-filled when missing"""
    p = raw.raw_payload
    platform = raw.platform.value

    # Extract common fields by platform (extend as needed)
    text = p.get("body") or p.get("selftext") or p.get("text") or p.get("content") or ""
    author_handle = p.get("author") or p.get("user") or p.get("username")
    posted_raw = p.get("updated") or p.get("created") or p.get("created_utc") or p.get("published")
    posted_at = None
    if posted_raw:
        try:
            posted_at = datetime.fromisoformat(posted_raw.replace("Z", "+00:00"))
        except Exception:
            posted_at = None

    likes = p.get("score") or p.get("likes") or p.get("ups")
    comments = p.get("num_comments") or p.get("comments_count")
    shares = p.get("shares") or p.get("share_count")
    views = p.get("views") or p.get("view_count")

    return {
        "text": text.strip() if text else "",
        "author_handle": author_handle,
        "posted_at": posted_at,
        "url": raw.url or p.get("url"),
        "branch": raw.branch or p.get("branch") or p.get("place"),
        "reactions": {
            "likes": int(likes) if likes is not None else None,
            "comments": int(comments) if comments is not None else None,
            "shares": int(shares) if shares is not None else None,
            "views": int(views) if views is not None else None,
        },
        "rating": float(p["rating"]) if p.get("rating") is not None else None,
        "language": p.get("language") or p.get("lang"),
        "place": p.get("place"),
    }


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
    Output: {"records": [...], "report": {...}, "counters": {...}}
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

            # ---- FR-PRC-06: company matching (simplified: if company name/alias in text, keep) ----
            name_hit = company.lower() in text.lower()
            if not name_hit:
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
            mention_type = "names company directly" if name_hit else "uncertain"

            # ---- FR-PRC-10: completeness ----
            incomplete = []
            if not mapped["url"]:
                incomplete.append("url")
            if not mapped["posted_at"]:
                incomplete.append("posted_at")
            if incomplete:
                counters["incomplete"] += 1

            # ---- Build record ----
            mid = _mention_id(raw.platform.value, raw.item_id, raw.raw_payload, "", mapped["posted_at"]) # Pass empty string instead of text
            rec = SoclRecord(
                record_id=f"{mid}:{company_id}",
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
                is_update=False,
                fingerprint=_fingerprint(raw.raw_payload.get("body", "") + raw.raw_payload.get("updated", ""), mapped.get("posted_at")),
                version=1,
                supersedes=None,
                incomplete=incomplete,
                company_match="confirmed",
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