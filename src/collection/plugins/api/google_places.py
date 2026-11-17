"""Google Places API (New) connector for place review collection."""
from datetime import datetime, timezone
import logging
import os
import time
from typing import Any, ClassVar, Dict, List, Optional, Tuple

import requests

from config.settings import load_plugin_config
from src.collection.base import BaseConnector, CollectionRequest
from src.collection.budget import BudgetExceeded, BudgetTracker
from src.collection.cache import ResultCache, compute_cache_key
from src.collection.common.http import get_session
from src.contracts.enums import AttemptStatus, ContentType, Method, Platform
from src.contracts.schemas import CollectionAttempt, RawMention

logger = logging.getLogger(__name__)


class GooglePlacesConnector(BaseConnector):
    """Google Places API (New) connector.

    Performs text search for company/branch places, then fetches place details and reviews.
    """

    method: ClassVar[Method] = Method.api
    name: ClassVar[str] = "google_places"
    platforms: ClassVar[List[Platform]] = [Platform.google]

    def __init__(
        self,
        session: Optional[requests.Session] = None,
        budget_tracker: Optional[BudgetTracker] = None,
        cache: Optional[ResultCache] = None,
    ):
        cfg = load_plugin_config("api").get("google_places", {})
        self.search_url: str = cfg.get(
            "search_url", "https://places.googleapis.com/v1/places:searchText"
        )
        self.details_url_template: str = cfg.get(
            "details_url_template", "https://places.googleapis.com/v1/places/{place_id}"
        )
        self.search_field_mask: str = cfg.get(
            "search_field_mask", "places.id,places.displayName"
        )
        self.details_field_mask: str = cfg.get(
            "details_field_mask", "displayName,formattedAddress,reviews"
        )
        self.cost_per_search_call: float = float(cfg.get("cost_per_search_call", 0.032))
        self.cost_per_details_call: float = float(cfg.get("cost_per_details_call", 0.017))
        self.request_timeout: int = int(cfg.get("request_timeout", 15))
        self.max_retries: int = int(cfg.get("max_retries", 2))
        self.cache_ttl_days: float = float(cfg.get("cache_ttl_days", 0.0))

        self._session = session or get_session(max_retries=0)
        self._budget_tracker = budget_tracker
        self._cache = cache or ResultCache()

    def _get_api_key(self) -> Optional[str]:
        key = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()
        return key or None

    def can_run(self, request: CollectionRequest) -> Tuple[bool, str]:
        if not request.company or not request.company.strip():
            return False, "Target company name is required"

        if request.platforms and Platform.google not in request.platforms:
            return False, f"Google platform not requested in {request.platforms}"

        if not self._get_api_key():
            return False, "Google Places key missing"

        return True, "OK"

    def estimate_cost(self, request: CollectionRequest) -> float:
        """Estimate cost summing planned search and details calls."""
        targets = request.branches if request.branches else [request.company]
        count = len(targets)
        # Each target entails 1 search call + up to 1 details call
        return float(count * (self.cost_per_search_call + self.cost_per_details_call))

    def _execute_request_with_retry(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        json_data: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[requests.Response], Optional[Tuple[AttemptStatus, str]]]:
        """Execute HTTP request with 5xx/timeout backoff retries. Never retries 400/403."""
        resp: Optional[requests.Response] = None

        for attempt_idx in range(self.max_retries + 1):
            try:
                if method.upper() == "POST":
                    resp = self._session.post(
                        url, headers=headers, json=json_data, timeout=self.request_timeout
                    )
                else:
                    resp = self._session.get(
                        url, headers=headers, timeout=self.request_timeout
                    )

                if resp.status_code == 429:
                    retry_after = resp.headers.get("Retry-After", "unknown")
                    return resp, (
                        AttemptStatus.rate_limited,
                        f"Google Places API rate limited (HTTP 429, Retry-After: {retry_after})",
                    )

                if resp.status_code in (400, 403):
                    return resp, (
                        AttemptStatus.failed,
                        f"Google Places API authentication or client error (HTTP {resp.status_code})",
                    )

                if resp.status_code >= 500:
                    if attempt_idx < self.max_retries:
                        time.sleep(0.5 * (2**attempt_idx))
                        continue
                    return resp, (
                        AttemptStatus.failed,
                        f"Google Places API server error (HTTP {resp.status_code})",
                    )

                resp.raise_for_status()
                return resp, None

            except (requests.Timeout, requests.ConnectionError) as net_err:
                if attempt_idx < self.max_retries:
                    time.sleep(0.5 * (2**attempt_idx))
                    continue
                return None, (
                    AttemptStatus.failed,
                    f"Google Places network error: {net_err.__class__.__name__}",
                )
            except requests.RequestException as req_err:
                return None, (
                    AttemptStatus.failed,
                    f"Google Places request error: {req_err}",
                )

        return resp, (AttemptStatus.failed, "Failed after max retries")

    def collect(
        self, request: CollectionRequest
    ) -> Tuple[List[RawMention], CollectionAttempt]:
        started_at = datetime.now(timezone.utc)

        can_run, reason = self.can_run(request)
        if not can_run:
            finished_at = datetime.now(timezone.utc)
            return [], CollectionAttempt(
                company=request.company,
                platform=Platform.google,
                method=self.method,
                status=AttemptStatus.failed,
                reason=reason,
                item_count=0,
                cost_usd=0.0,
                started_at=started_at,
                finished_at=finished_at,
            )

        api_key = self._get_api_key()
        assert api_key

        budget_tracker = self._budget_tracker or BudgetTracker(limit_usd=request.budget_usd)

        targets = (
            [f"{request.company} {b}" for b in request.branches]
            if request.branches
            else [request.company]
        )

        all_mentions: List[RawMention] = []
        total_spent: float = 0.0
        capped_5_reviews: bool = False
        overall_error: Optional[Tuple[AttemptStatus, str]] = None
        places_found_count: int = 0

        for target_query in targets:
            # Check cache for target_query
            cache_key = compute_cache_key(self.name, target_query)
            cached_data = None
            if self.cache_ttl_days > 0.0:
                cached_data = self._cache.get(cache_key, max_age_days=self.cache_ttl_days)

            if cached_data is not None:
                # Cache hit: parse stored mentions without making network calls
                for item in cached_data:
                    raw_payload = item.get("raw_payload", {})
                    all_mentions.append(
                        RawMention(
                            schema_version="1.0",
                            company=request.company,
                            run_id=request.run_id,
                            platform=Platform.google,
                            item_id=item.get("item_id"),
                            url=item.get("url"),
                            branch=item.get("branch"),
                            content_type_hint=ContentType.review,
                            raw_payload=raw_payload,
                            source="google.com/maps",
                            method_used=self.method,
                            tool_used="Google Places API",
                            cost_usd=0.0,
                            collected_at=datetime.now(timezone.utc),
                        )
                    )
                places_found_count += 1
                continue

            # Step 1: Text Search
            # Reserve search cost
            try:
                search_token = budget_tracker.reserve(Platform.google, self.cost_per_search_call)
            except BudgetExceeded:
                overall_error = (
                    AttemptStatus.budget_exhausted,
                    "Budget exhausted before places search call",
                )
                break

            search_headers = {
                "Content-Type": "application/json",
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": self.search_field_mask,
            }
            search_body = {"textQuery": target_query}

            resp, err = self._execute_request_with_retry(
                "POST", self.search_url, search_headers, search_body
            )
            budget_tracker.commit(search_token, actual_amount=self.cost_per_search_call)
            total_spent += self.cost_per_search_call

            if err:
                overall_error = err
                break

            if not resp or resp.status_code != 200:
                overall_error = (
                    AttemptStatus.failed,
                    f"Search endpoint returned HTTP {resp.status_code if resp else 'None'}",
                )
                break

            places = resp.json().get("places", [])
            if not places:
                continue

            places_found_count += 1
            first_place = places[0]
            place_id = first_place.get("id")
            if not place_id:
                continue

            # Step 2: Place Details
            # Reserve details cost
            try:
                details_token = budget_tracker.reserve(Platform.google, self.cost_per_details_call)
            except BudgetExceeded:
                overall_error = (
                    AttemptStatus.budget_exhausted,
                    "Budget exhausted before place details call",
                )
                break

            details_url = self.details_url_template.format(place_id=place_id)
            details_headers = {
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": self.details_field_mask,
            }

            det_resp, det_err = self._execute_request_with_retry(
                "GET", details_url, details_headers
            )
            budget_tracker.commit(details_token, actual_amount=self.cost_per_details_call)
            total_spent += self.cost_per_details_call

            if det_err:
                overall_error = det_err
                break

            if not det_resp or det_resp.status_code != 200:
                overall_error = (
                    AttemptStatus.failed,
                    f"Details endpoint returned HTTP {det_resp.status_code if det_resp else 'None'}",
                )
                break

            details_data = det_resp.json()
            place_display_name_obj = details_data.get("displayName", {})
            place_display_name = (
                place_display_name_obj.get("text")
                if isinstance(place_display_name_obj, dict)
                else str(place_display_name_obj or "")
            )
            formatted_address = details_data.get("formattedAddress", "")
            branch_name = place_display_name or formatted_address or None

            reviews = details_data.get("reviews", [])
            if len(reviews) >= 5:
                capped_5_reviews = True

            target_mentions: List[Dict[str, Any]] = []
            call_cost_share = (
                (self.cost_per_search_call + self.cost_per_details_call) / len(reviews)
                if reviews
                else (self.cost_per_search_call + self.cost_per_details_call)
            )

            now_utc = datetime.now(timezone.utc)

            for review in reviews:
                raw_payload = dict(review)
                raw_payload["place_id"] = place_id
                raw_payload["place_name"] = place_display_name

                # Review author attribution or map uri
                author_attrib = review.get("authorAttribution", {})
                author_uri = author_attrib.get("uri") if isinstance(author_attrib, dict) else None

                item_id = review.get("name")
                url = author_uri or None

                mention = RawMention(
                    schema_version="1.0",
                    company=request.company,
                    run_id=request.run_id,
                    platform=Platform.google,
                    item_id=item_id,
                    url=url,
                    branch=branch_name,
                    content_type_hint=ContentType.review,
                    raw_payload=raw_payload,
                    source="google.com/maps",
                    method_used=self.method,
                    tool_used="Google Places API",
                    cost_usd=round(call_cost_share, 4),
                    collected_at=now_utc,
                )
                all_mentions.append(mention)
                target_mentions.append(
                    {
                        "item_id": item_id,
                        "url": url,
                        "branch": branch_name,
                        "raw_payload": raw_payload,
                    }
                )

            # Put in cache if TTL is configured
            if self.cache_ttl_days > 0.0:
                self._cache.put(cache_key, target_mentions)

        finished_at = datetime.now(timezone.utc)

        # Status & Reason Resolution
        if overall_error and overall_error[0] == AttemptStatus.budget_exhausted:
            status = AttemptStatus.budget_exhausted
            reason_parts = [overall_error[1]]
            if all_mentions:
                reason_parts.append(f"collected {len(all_mentions)} reviews prior to exhaustion")
            reason = "; ".join(reason_parts)
        elif overall_error and not all_mentions:
            status, reason = overall_error
        elif places_found_count == 0 and not all_mentions:
            status = AttemptStatus.empty
            reason = "No matching places found for queries"
        elif not all_mentions:
            status = AttemptStatus.empty
            reason = "Places found but returned 0 reviews"
        else:
            status = AttemptStatus.success
            reason_parts = [f"Collected {len(all_mentions)} Google Places reviews"]
            if capped_5_reviews:
                reason_parts.append("capped at Google Places limit of 5 reviews per place")
            reason = "; ".join(reason_parts)

        # Ensure API key never appears in reason
        if api_key in reason:
            reason = reason.replace(api_key, "[REDACTED]")

        attempt = CollectionAttempt(
            company=request.company,
            platform=Platform.google,
            method=self.method,
            status=status,
            reason=reason,
            item_count=len(all_mentions),
            cost_usd=round(total_spent, 4),
            started_at=started_at,
            finished_at=finished_at,
            scraping_checks=None,
        )

        return all_mentions, attempt
