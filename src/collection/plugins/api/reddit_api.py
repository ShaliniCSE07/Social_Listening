"""Reddit official API connector using client credentials OAuth flow."""
from datetime import datetime, timezone
import logging
import os
import time
from typing import Any, ClassVar, Dict, List, Optional, Tuple

import requests
from requests.auth import HTTPBasicAuth

from config.settings import load_plugin_config
from src.collection.base import BaseConnector, CollectionRequest
from src.collection.common.http import get_session
from src.collection.common.text import matches_company
from src.contracts.enums import AttemptStatus, ContentType, Method, Platform
from src.contracts.schemas import CollectionAttempt, RawMention

logger = logging.getLogger(__name__)


class RedditAPIConnector(BaseConnector):
    """Reddit Official API connector.

    Authenticates via app-only OAuth2 (client credentials grant) and searches
    reddit.com posts matching target company queries.
    """

    method: ClassVar[Method] = Method.api
    name: ClassVar[str] = "reddit_api"
    platforms: ClassVar[List[Platform]] = [Platform.reddit]

    def __init__(self, session: Optional[requests.Session] = None):
        cfg = load_plugin_config("api").get("reddit", {})
        self.max_items: int = cfg.get("max_items", 200)
        self.request_timeout: int = cfg.get("request_timeout", 15)
        self.max_retries: int = cfg.get("max_retries", 2)
        self.token_url: str = cfg.get("token_url", "https://www.reddit.com/api/v1/access_token")
        self.api_base_url: str = cfg.get("api_base_url", "https://oauth.reddit.com")

        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self._session = session or get_session(max_retries=0)

    def _get_credentials(self) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        client_id = os.environ.get("REDDIT_CLIENT_ID", "").strip()
        client_secret = os.environ.get("REDDIT_CLIENT_SECRET", "").strip()
        user_agent = os.environ.get("REDDIT_USER_AGENT", "").strip()
        return (
            client_id or None,
            client_secret or None,
            user_agent or None,
        )

    def can_run(self, request: CollectionRequest) -> Tuple[bool, str]:
        if not request.company or not request.company.strip():
            return False, "Target company name is required"

        if request.platforms and Platform.reddit not in request.platforms:
            return False, f"Reddit platform not requested in {request.platforms}"

        client_id, client_secret, user_agent = self._get_credentials()
        if not client_id or not client_secret or not user_agent:
            return False, "Reddit credentials missing"

        return True, "OK"

    def estimate_cost(self, request: CollectionRequest) -> float:
        return 0.0

    def _get_token(self, client_id: str, client_secret: str, user_agent: str) -> str:
        """Fetch or return cached OAuth2 bearer token."""
        now = time.time()
        if self._token and now < self._token_expires_at - 60:
            return self._token

        headers = {"User-Agent": user_agent}
        data = {"grant_type": "client_credentials"}
        auth = HTTPBasicAuth(client_id, client_secret)

        response = self._session.post(
            self.token_url,
            headers=headers,
            data=data,
            auth=auth,
            timeout=self.request_timeout,
        )

        if response.status_code in (401, 403):
            raise PermissionError("Reddit OAuth authentication failed (HTTP 401/403)")

        if response.status_code != 200:
            raise requests.HTTPError(
                f"Reddit OAuth token endpoint returned HTTP {response.status_code}"
            )

        token_data = response.json()
        token = token_data.get("access_token")
        expires_in = token_data.get("expires_in", 3600)
        if not token:
            raise ValueError("No access_token returned by Reddit token endpoint")

        self._token = token
        self._token_expires_at = now + float(expires_in)
        return self._token

    def _search_query(
        self,
        query: str,
        token: str,
        user_agent: str,
        remaining_budget: int,
    ) -> Tuple[List[Dict[str, Any]], Optional[Tuple[AttemptStatus, str]]]:
        """Query Reddit search endpoint with pagination up to remaining_budget."""
        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": user_agent,
        }

        items: List[Dict[str, Any]] = []
        after: Optional[str] = None
        search_url = f"{self.api_base_url.rstrip('/')}/search"

        while len(items) < remaining_budget:
            page_limit = min(100, remaining_budget - len(items))
            params: Dict[str, Any] = {
                "q": query,
                "sort": "new",
                "limit": page_limit,
                "type": "link",
            }
            if after:
                params["after"] = after

            resp: Optional[requests.Response] = None
            for attempt_idx in range(self.max_retries + 1):
                try:
                    resp = self._session.get(
                        search_url,
                        headers=headers,
                        params=params,
                        timeout=self.request_timeout,
                    )

                    if resp.status_code == 429:
                        retry_after = resp.headers.get("Retry-After", "unknown")
                        return items, (
                            AttemptStatus.rate_limited,
                            f"Reddit API rate limited (HTTP 429, Retry-After: {retry_after})",
                        )

                    if resp.status_code in (401, 403):
                        return items, (
                            AttemptStatus.failed,
                            "authentication or permission error",
                        )

                    if resp.status_code >= 500:
                        if attempt_idx < self.max_retries:
                            time.sleep(0.5 * (2**attempt_idx))
                            continue
                        return items, (
                            AttemptStatus.failed,
                            f"Reddit API server error: HTTP {resp.status_code}",
                        )

                    resp.raise_for_status()
                    break

                except (requests.Timeout, requests.ConnectionError) as net_err:
                    if attempt_idx < self.max_retries:
                        time.sleep(0.5 * (2**attempt_idx))
                        continue
                    return items, (
                        AttemptStatus.failed,
                        f"Reddit API network error: {net_err.__class__.__name__}",
                    )
                except requests.RequestException as req_err:
                    return items, (
                        AttemptStatus.failed,
                        f"Reddit API request error: {req_err}",
                    )

            if resp is None or resp.status_code != 200:
                return items, (
                    AttemptStatus.failed,
                    "Failed to retrieve data after retries",
                )

            data = resp.json().get("data", {})
            children = data.get("children", [])
            if not children:
                break

            for child in children:
                child_data = child.get("data", {})
                if child_data:
                    items.append(child_data)
                    if len(items) >= remaining_budget:
                        break

            after = data.get("after")
            if not after:
                break

        return items, None

    def collect(
        self, request: CollectionRequest
    ) -> Tuple[List[RawMention], CollectionAttempt]:
        started_at = datetime.now(timezone.utc)

        can_collect, reason = self.can_run(request)
        if not can_collect:
            finished_at = datetime.now(timezone.utc)
            return [], CollectionAttempt(
                company=request.company,
                platform=Platform.reddit,
                method=self.method,
                status=AttemptStatus.failed,
                reason=reason,
                item_count=0,
                cost_usd=0.0,
                started_at=started_at,
                finished_at=finished_at,
            )

        client_id, client_secret, user_agent = self._get_credentials()
        # Ensure credentials exist for typing
        assert client_id and client_secret and user_agent

        try:
            token = self._get_token(client_id, client_secret, user_agent)
        except PermissionError:
            finished_at = datetime.now(timezone.utc)
            return [], CollectionAttempt(
                company=request.company,
                platform=Platform.reddit,
                method=self.method,
                status=AttemptStatus.failed,
                reason="authentication or permission error",
                item_count=0,
                cost_usd=0.0,
                started_at=started_at,
                finished_at=finished_at,
            )
        except Exception as e:
            finished_at = datetime.now(timezone.utc)
            return [], CollectionAttempt(
                company=request.company,
                platform=Platform.reddit,
                method=self.method,
                status=AttemptStatus.failed,
                reason=f"Failed to acquire OAuth token: {e.__class__.__name__}",
                item_count=0,
                cost_usd=0.0,
                started_at=started_at,
                finished_at=finished_at,
            )

        queries = [request.company]
        for alt in request.alt_spellings:
            clean_alt = alt.strip()
            if clean_alt and clean_alt not in queries:
                queries.append(clean_alt)

        collected_children: List[Dict[str, Any]] = []
        seen_names = set()
        overall_error: Optional[Tuple[AttemptStatus, str]] = None

        for query in queries:
            remaining = self.max_items - len(collected_children)
            if remaining <= 0:
                break

            items, error = self._search_query(query, token, user_agent, remaining)
            if error:
                overall_error = error
                # If rate-limited or auth error, stop immediately
                if error[0] in (AttemptStatus.rate_limited, AttemptStatus.failed):
                    break

            for item in items:
                name = item.get("name") or item.get("id")
                if name and name not in seen_names:
                    seen_names.add(name)
                    collected_children.append(item)

        # Filter mentions
        filtered_mentions: List[RawMention] = []
        now_utc = datetime.now(timezone.utc)

        for child in collected_children:
            # Check company matching
            title = child.get("title", "")
            selftext = child.get("selftext", "")
            full_text = f"{title}\n{selftext}"
            if not matches_company(
                full_text,
                request.company,
                request.alt_spellings,
                request.handles,
            ):
                continue

            # Check date filtering
            created_utc = child.get("created_utc")
            if created_utc is not None:
                item_dt = datetime.fromtimestamp(created_utc, tz=timezone.utc)
                if request.date_from and item_dt < request.date_from:
                    continue
                if request.date_to and item_dt > request.date_to:
                    continue

            item_fullname = child.get("name") or (
                f"t3_{child.get('id')}" if child.get("id") else None
            )
            permalink = child.get("permalink", "")
            item_url = (
                f"https://reddit.com{permalink}"
                if permalink.startswith("/")
                else (permalink or None)
            )
            subreddit = child.get("subreddit", "unknown")

            filtered_mentions.append(
                RawMention(
                    schema_version="1.0",
                    company=request.company,
                    run_id=request.run_id,
                    platform=Platform.reddit,
                    item_id=item_fullname,
                    url=item_url,
                    branch=None,
                    content_type_hint=ContentType.post,
                    raw_payload=child,
                    source=f"reddit.com/r/{subreddit}",
                    method_used=Method.api,
                    tool_used="Reddit API",
                    fallback_from=None,
                    cost_usd=0.0,
                    collected_at=now_utc,
                )
            )

        finished_at = datetime.now(timezone.utc)

        # Determine attempt status
        if overall_error and not filtered_mentions:
            status, reason = overall_error
        elif not filtered_mentions:
            status = AttemptStatus.empty
            reason = (
                overall_error[1]
                if overall_error
                else "No matching Reddit posts found"
            )
        else:
            status = AttemptStatus.success
            reason = f"Collected {len(filtered_mentions)} Reddit posts"

        attempt = CollectionAttempt(
            company=request.company,
            platform=Platform.reddit,
            method=self.method,
            status=status,
            reason=reason,
            item_count=len(filtered_mentions),
            cost_usd=0.0,
            started_at=started_at,
            finished_at=finished_at,
            scraping_checks=None,
        )

        return filtered_mentions, attempt

