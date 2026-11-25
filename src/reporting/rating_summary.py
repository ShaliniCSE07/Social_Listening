"""Star-rating summary (Amazon-style breakdown) for collected mentions.

Works on the output of any plugin: each plugin keeps its review's star rating
somewhere in ``raw_payload`` (TripAdvisor and Google Places use ``rating``; the
dataset plugin adds ``rating_mapped`` from the catalogue's column mapping).
Mentions without a usable 1-5 rating (Reddit posts, scraped pages, odd values)
are counted as "not rated" and left out of the percentages.
"""
import math
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional

STAR_LEVELS = (5, 4, 3, 2, 1)

# Checked in order; the first key holding a usable value wins.
RATING_KEYS = (
    "rating_mapped",  # dataset plugin: value of the column mapped to "rating"
    "rating",  # TripAdvisor, Google Places, most review datasets
    "stars",
    "star_rating",
    "review_rating",
    "overall_rating",
    "reviewRating",
)

_OUT_OF_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(?:/|out\s+of|of)\s*(\d+(?:\.\d+)?)\s*$", re.I)
_NUMBER_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(?:stars?|★)?\s*$", re.I)


def _to_number(value: Any) -> Optional[float]:
    """Turn 4, 4.5, "4", "4.0", "4/5", "4 out of 5", "4 stars" into a 0-5 number."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        num = float(value)
        return num if math.isfinite(num) else None
    if isinstance(value, Mapping):
        for key in ("value", "rating", "score"):
            if key in value:
                return _to_number(value[key])
        return None
    if isinstance(value, str):
        m = _OUT_OF_RE.match(value)
        if m:
            got, scale = float(m.group(1)), float(m.group(2))
            if scale <= 0:
                return None
            return got / scale * 5.0
        m = _NUMBER_RE.match(value)
        if m:
            return float(m.group(1))
    return None


def extract_rating(mention: Mapping[str, Any]) -> Optional[float]:
    """Return the mention's rating on a 1-5 scale (unrounded), or None."""
    payload = mention.get("raw_payload") or {}
    if not isinstance(payload, Mapping):
        return None
    for key in RATING_KEYS:
        if key in payload and payload[key] not in (None, ""):
            num = _to_number(payload[key])
            if num is not None and 1 <= num <= 5:
                return num
    return None


def _summarize(ratings: List[float], total: int) -> Dict[str, Any]:
    counts = {s: 0 for s in STAR_LEVELS}
    for r in ratings:
        counts[int(math.floor(r + 0.5))] += 1
    rated = len(ratings)
    return {
        "total_mentions": total,
        "rated_count": rated,
        "unrated_count": total - rated,
        "average": round(sum(ratings) / rated, 2) if rated else None,
        "distribution": [
            {
                "stars": s,
                "count": counts[s],
                "percent": round(counts[s] * 100.0 / rated, 1) if rated else 0.0,
            }
            for s in STAR_LEVELS
        ],
    }


def summarize_ratings(mentions: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    """Build the overall and per-platform star breakdown for a list of mentions."""
    overall: List[float] = []
    total = 0
    per_platform: Dict[str, Dict[str, Any]] = {}

    for m in mentions:
        total += 1
        platform = str(m.get("platform") or "other")
        bucket = per_platform.setdefault(platform, {"ratings": [], "total": 0})
        bucket["total"] += 1
        rating = extract_rating(m)
        if rating is not None:
            overall.append(rating)
            bucket["ratings"].append(rating)

    summary = _summarize(overall, total)
    summary["by_platform"] = {
        p: _summarize(b["ratings"], b["total"]) for p, b in sorted(per_platform.items())
    }
    return summary
