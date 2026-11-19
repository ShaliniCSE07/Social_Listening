"""TripAdvisor reviews through RapidAPI ("Tripadvisor Reviews Scraper" listing).

The listing takes TripAdvisor page URLs (hotel, restaurant, attraction or
airline) and returns up to 20 reviews per URL, newest first, with full text,
rating, date, trip type, sub-ratings, owner response and reviewer.

Which pages to read comes from config/companies.yaml:

    <Company>:
      api:
        tripadvisor_urls:
          - "https://www.tripadvisor.com/Restaurant_Review-...html"

One RapidAPI request is made per URL, so a run costs at most
``max_places_per_run`` requests. The free Basic plan allows 10 requests a
month, so the default is small and results are cached for a day.

This is a third-party scraper sold through RapidAPI, not an official
TripAdvisor API; the source policy ranks it as a third-party source.
"""
from datetime import datetime, timezone
import logging
from typing import Any, ClassVar, Dict, List, Optional, Tuple

import requests

from config.settings import load_companies, load_plugin_config
from src.collection.base import BaseConnector, CollectionRequest
from src.collection.budget import BudgetExceeded, BudgetTracker
from src.collection.cache import ResultCache, compute_cache_key
from src.collection.common.rapidapi import RapidAPIClient, get_rapidapi_key
from src.contracts.enums import AttemptStatus, ContentType, Method, Platform
from src.contracts.schemas import CollectionAttempt, RawMention

logger = logging.getLogger(__name__)

TOOL_NAME = "RapidAPI: Tripadvisor Reviews Scraper"
SOURCE = "tripadvisor.com"
# Tells processing that a review belongs to the company because it was read
# from the company's own TripAdvisor page, even when the text never names it.
SOURCE_MATCH_BASIS = "place_page"


class TripadvisorReviewsConnector(BaseConnector):
    """Collects reviews for the TripAdvisor pages configured per company."""

    method: ClassVar[Method] = Method.api
    name: ClassVar[str] = "third_party_tripadvisor"
    platforms: ClassVar[List[Platform]] = [Platform.tripadvisor]

    def __init__(
        self,
        session: Optional[requests.Session] = None,
        budget_tracker: Optional[BudgetTracker] = None,
        cache: Optional[ResultCache] = None,
        companies: Optional[Dict[str, Any]] = None,
    ):
        cfg = load_plugin_config("api").get("tripadvisor_reviews", {}) or {}
        self.host: str = cfg.get("host", "tripadvisor-reviews-scraper1.p.rapidapi.com")
        self.path: str = cfg.get("path", "/")
        self.max_reviews_per_place: int = min(int(cfg.get("max_reviews_per_place", 20)), 20)
        self.max_places_per_run: int = int(cfg.get("max_places_per_run", 3))
        self.cost_per_request: float = float(cfg.get("cost_per_request", 0.0))
        self.min_quota_remaining: int = int(cfg.get("min_quota_remaining", 0))
        self.cache_ttl_days: float = float(cfg.get("cache_ttl_days", 1.0))

        self._client = RapidAPIClient(
            host=self.host,
            api_name="Tripadvisor Reviews Scraper",
            session=session,
            timeout=float(cfg.get("request_timeout", 70)),
            max_retries=int(cfg.get("max_retries", 0)),
        )
        self._budget_tracker = budget_tracker
        self._cache = cache or ResultCache()
        self._companies = companies

    # ---- configuration -------------------------------------------------

    def _all_companies(self) -> Dict[str, Any]:
        if self._companies is not None:
            return self._companies
        try:
            return load_companies() or {}
        except Exception:
            return {}

    def _company_cfg(self, company: str) -> Optional[Dict[str, Any]]:
        """The company's companies.yaml entry (case-insensitive), or None if absent."""
        target = company.strip().lower()
        for name, cfg in self._all_companies().items():
            if str(name).strip().lower() == target and isinstance(cfg, dict):
                return cfg
        return None

    @staticmethod
    def _urls_in(cfg: Optional[Dict[str, Any]]) -> List[str]:
        urls = ((cfg or {}).get("api") or {}).get("tripadvisor_urls") or []
        if isinstance(urls, str):
            urls = [urls]
        return [str(u).strip() for u in urls if str(u).strip()]

    def _place_urls(self, company: str) -> List[str]:
        """TripAdvisor URLs configured for the company."""
        return self._urls_in(self._company_cfg(company))

    def _planned_urls(self, request: CollectionRequest) -> List[str]:
        return self._place_urls(request.company)[: max(self.max_places_per_run, 0)]

    # ---- BaseConnector -------------------------------------------------

    def can_run(self, request: CollectionRequest) -> Tuple[bool, str]:
        if not request.company or not request.company.strip():
            return False, "Target company name is required"
        if request.platforms and Platform.tripadvisor not in request.platforms:
            return False, f"TripAdvisor platform not requested in {request.platforms}"
        if not get_rapidapi_key():
            return False, "RAPIDAPI_KEY missing"
        # A company listed in companies.yaml without TripAdvisor pages is
        # skipped here. A company not listed at all (an ad-hoc run, or the
        # sources page's probe) passes as long as some company has pages;
        # collect() then reports the missing URLs for it.
        cfg = self._company_cfg(request.company)
        if cfg is not None and not self._urls_in(cfg):
            return False, self._no_urls_reason(request.company)
        if cfg is None and not any(self._urls_in(c) for c in self._all_companies().values() if isinstance(c, dict)):
            return False, "No TripAdvisor URLs configured in companies.yaml (api.tripadvisor_urls)"
        if self.max_places_per_run <= 0:
            return False, "max_places_per_run is 0 in api.yaml (tripadvisor_reviews)"
        return True, "OK"

    def estimate_cost(self, request: CollectionRequest) -> float:
        return float(len(self._planned_urls(request)) * self.cost_per_request)

    def _request_body(self, url: str, request: CollectionRequest) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "places": [url],
            "maxReviewsPerPlace": self.max_reviews_per_place,
        }
        if request.date_from:
            body["reviewsSince"] = request.date_from.astimezone(timezone.utc).strftime("%Y-%m-%d")
        return body

    def collect(
        self, request: CollectionRequest
    ) -> Tuple[List[RawMention], CollectionAttempt]:
        started_at = datetime.now(timezone.utc)

        can_run, reason = self.can_run(request)
        if can_run and not self._place_urls(request.company):
            can_run, reason = False, self._no_urls_reason(request.company)
        if not can_run:
            return [], self._attempt(request, started_at, AttemptStatus.failed, reason, [], 0.0, 0, 0)

        budget_tracker = self._budget_tracker or BudgetTracker(limit_usd=request.budget_usd)
        urls = self._planned_urls(request)
        skipped_urls = len(self._place_urls(request.company)) - len(urls)

        mentions: List[RawMention] = []
        total_spent = 0.0
        pages_fetched = 0
        pages_from_cache = 0
        error: Optional[Tuple[AttemptStatus, str]] = None
        quota_note: Optional[str] = None

        for url in urls:
            body = self._request_body(url, request)
            cache_key = compute_cache_key(self.name, url, {k: v for k, v in body.items() if k != "places"})

            reviews: Optional[List[Dict[str, Any]]] = None
            from_cache = False
            if self.cache_ttl_days > 0.0 and not request.refresh:
                reviews = self._cache.get(cache_key, max_age_days=self.cache_ttl_days)
                from_cache = reviews is not None

            if reviews is None:
                try:
                    token = budget_tracker.reserve(Platform.tripadvisor, self.cost_per_request)
                except BudgetExceeded:
                    error = (AttemptStatus.budget_exhausted, "Budget exhausted before TripAdvisor request")
                    break

                result = self._client.post(self.path, body)
                budget_tracker.commit(token, actual_amount=self.cost_per_request)
                total_spent += self.cost_per_request
                pages_fetched += 1

                if not result.ok:
                    error = result.error
                    break
                if not isinstance(result.data, list):
                    error = (AttemptStatus.failed, "Tripadvisor Reviews Scraper: expected a JSON array of reviews")
                    break

                reviews = [r for r in result.data if isinstance(r, dict)]
                if self.cache_ttl_days > 0.0:
                    self._cache.put(cache_key, reviews)

                if result.quota_remaining is not None and result.quota_remaining <= self.min_quota_remaining:
                    quota_note = f"RapidAPI quota left: {result.quota_remaining}; stopped early"
                    mentions.extend(self._to_mentions(reviews, request, url, cost=self.cost_per_request))
                    break
            else:
                pages_from_cache += 1

            cost = 0.0 if from_cache else self.cost_per_request
            mentions.extend(self._to_mentions(reviews, request, url, cost=cost))

        status, reason = self._resolve_status(mentions, error, urls, skipped_urls, quota_note)
        return mentions, self._attempt(
            request, started_at, status, reason, mentions, total_spent, pages_fetched, pages_from_cache
        )

    # ---- helpers -------------------------------------------------------

    @staticmethod
    def _no_urls_reason(company: str) -> str:
        return (
            f"No TripAdvisor URLs configured for '{company}' "
            "(companies.yaml: api.tripadvisor_urls)"
        )

    def _to_mentions(
        self,
        reviews: List[Dict[str, Any]],
        request: CollectionRequest,
        page_url: str,
        cost: float,
    ) -> List[RawMention]:
        kept = [r for r in reviews if self._within_dates(r, request)]
        share = round(cost / len(kept), 6) if kept else 0.0
        now_utc = datetime.now(timezone.utc)

        out: List[RawMention] = []
        for review in kept:
            payload = dict(review)
            payload["source_match_basis"] = SOURCE_MATCH_BASIS
            payload.setdefault("placeUrl", page_url)
            out.append(
                RawMention(
                    company=request.company,
                    run_id=request.run_id,
                    platform=Platform.tripadvisor,
                    item_id=_str_or_none(review.get("reviewId")),
                    url=_str_or_none(review.get("url")),
                    branch=_str_or_none(review.get("placeName")),
                    content_type_hint=ContentType.review,
                    raw_payload=payload,
                    source=SOURCE,
                    method_used=self.method,
                    tool_used=TOOL_NAME,
                    cost_usd=share,
                    collected_at=now_utc,
                )
            )
        return out

    @staticmethod
    def _within_dates(review: Dict[str, Any], request: CollectionRequest) -> bool:
        """Drop reviews outside date_from/date_to; keep reviews whose date cannot be read."""
        if not request.date_from and not request.date_to:
            return True
        published = _parse_iso(review.get("publishedAt"))
        if published is None:
            return True
        if request.date_from and published < request.date_from.astimezone(timezone.utc):
            return False
        if request.date_to and published > request.date_to.astimezone(timezone.utc):
            return False
        return True

    @staticmethod
    def _resolve_status(
        mentions: List[RawMention],
        error: Optional[Tuple[AttemptStatus, str]],
        urls: List[str],
        skipped_urls: int,
        quota_note: Optional[str],
    ) -> Tuple[AttemptStatus, str]:
        notes: List[str] = []
        if skipped_urls > 0:
            notes.append(f"{skipped_urls} more URL(s) skipped by max_places_per_run")
        if quota_note:
            notes.append(quota_note)

        if error and error[0] == AttemptStatus.budget_exhausted:
            parts = [error[1]]
            if mentions:
                parts.append(f"collected {len(mentions)} reviews before that")
            return AttemptStatus.budget_exhausted, "; ".join(parts + notes)
        if error and not mentions:
            return error[0], "; ".join([error[1]] + notes)
        if not mentions:
            return AttemptStatus.empty, "; ".join([f"No reviews returned for {len(urls)} TripAdvisor page(s)"] + notes)

        parts = [f"Collected {len(mentions)} TripAdvisor reviews from {len(urls)} page(s)"]
        if error:
            parts.append(f"stopped early: {error[1]}")
        return AttemptStatus.success, "; ".join(parts + notes)

    def _attempt(
        self,
        request: CollectionRequest,
        started_at: datetime,
        status: AttemptStatus,
        reason: str,
        mentions: List[RawMention],
        cost: float,
        pages_fetched: int,
        pages_from_cache: int,
    ) -> CollectionAttempt:
        return CollectionAttempt(
            company=request.company,
            platform=Platform.tripadvisor,
            method=self.method,
            status=status,
            reason=reason,
            item_count=len(mentions),
            cost_usd=round(cost, 4),
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            pages_fetched=pages_fetched,
            pages_from_cache=pages_from_cache,
        )


def _str_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
