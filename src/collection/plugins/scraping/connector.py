"""Scraping Collection Plugin connector.

Iterates over every site in ``scraping_sites.yaml``, fetches start URLs,
follows item links whose title mentions the company, and builds
``RawMention`` records.  One ``CollectionAttempt`` is emitted per site;
a failure in one site never stops another, and no exception escapes
``collect()``.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import ClassVar, Dict, List, Tuple, Union
from urllib.parse import urljoin

import requests as http_client
import yaml

from config.settings import load_plugin_config
from src.collection.base import BaseConnector, CollectionRequest
from src.collection.common.text import matches_company
from src.collection.plugins.scraping.parsers import get_parser
from src.contracts.enums import AttemptStatus, ContentType, Method, Platform
from src.contracts.schemas import CollectionAttempt, RawMention

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config loader (cached per-process)
# ---------------------------------------------------------------------------
_sites_cfg: Dict | None = None


def _load_sites_cfg() -> Dict:
    global _sites_cfg
    if _sites_cfg is None:
        _sites_cfg = load_plugin_config("scraping_sites") or {}
    return _sites_cfg


def _reset_sites_cfg() -> None:
    """Allow tests to clear the cache between runs."""
    global _sites_cfg
    _sites_cfg = None


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------
class ScrapingConnector(BaseConnector):
    """Scraping connector — one ``CollectionAttempt`` per configured site."""

    method: ClassVar[Method] = Method.scraping
    name: ClassVar[str] = "scraping"
    platforms: ClassVar[List[Platform]] = [Platform.other]

    # ------------------------------------------------------------------ #
    # can_run
    # ------------------------------------------------------------------ #
    def can_run(self, request: CollectionRequest) -> Tuple[bool, str]:
        if not os.getenv("SCRAPER_CONTACT"):
            return False, "SCRAPER_CONTACT env var is missing"
        if not request.scraping_allowed:
            return False, "scraping_allowed is False on the request"
        cfg = _load_sites_cfg()
        enabled = [k for k, v in cfg.items() if v.get("allows_scraping")]
        if not enabled:
            return False, "no site has allows_scraping=true in config"
        return True, "ready"

    # ------------------------------------------------------------------ #
    # estimate_cost
    # ------------------------------------------------------------------ #
    def estimate_cost(self, request: CollectionRequest) -> float:
        return 0.0

    # ------------------------------------------------------------------ #
    # collect — one attempt per site, never raises
    # ------------------------------------------------------------------ #
    def collect(
        self, request: CollectionRequest
    ) -> Tuple[List[RawMention], List[CollectionAttempt]]:
        all_mentions: List[RawMention] = []
        all_attempts: List[CollectionAttempt] = []
        cfg = _load_sites_cfg()

        for site_key, site_cfg in cfg.items():
            started_at = datetime.now(timezone.utc)
            allows = site_cfg.get("allows_scraping", False)
            scraping_checks = {"site_policy_allows": bool(allows)}

            # -- skipped: policy disallows -----------------------------------
            if not allows:
                all_attempts.append(self._make_attempt(
                    request, site_cfg, AttemptStatus.skipped,
                    reason=f"site policy disallows scraping for {site_key}",
                    scraping_checks=scraping_checks,
                    started_at=started_at,
                ))
                continue

            # -- attempt the site -------------------------------------------
            try:
                mentions, pages_fetched, delay_used = self._collect_site(
                    request, site_key, site_cfg
                )
            except Exception as exc:
                log.exception("scraping failed for site %s", site_key)
                all_attempts.append(self._make_attempt(
                    request, site_cfg, AttemptStatus.failed,
                    reason=f"error: {exc}",
                    scraping_checks=scraping_checks,
                    started_at=started_at,
                ))
                continue

            if mentions:
                status = AttemptStatus.success
                reason = f"collected {len(mentions)} items"
            else:
                status = AttemptStatus.empty
                reason = "no matching items found"

            all_mentions.extend(mentions)
            all_attempts.append(self._make_attempt(
                request, site_cfg, status,
                reason=reason,
                scraping_checks=scraping_checks,
                started_at=started_at,
                item_count=len(mentions),
                pages_fetched=pages_fetched,
                delay_used=delay_used,
            ))

        return all_mentions, all_attempts

    # ------------------------------------------------------------------ #
    # private: scrape a single site
    # ------------------------------------------------------------------ #
    def _collect_site(
        self,
        request: CollectionRequest,
        site_key: str,
        site_cfg: dict,
    ) -> Tuple[List[RawMention], int, float]:
        start_urls: List[str] = site_cfg.get("start_urls", [])
        max_pages: int = site_cfg.get("max_pages", 5)
        delay: float = float(site_cfg.get("min_delay_seconds", 0))
        parser = get_parser(site_cfg["parser"])
        site_name = site_cfg.get("name", site_key)
        platform_str = site_cfg.get("platform", "other")
        platform = Platform(platform_str) if platform_str in Platform.__members__ else Platform.other
        content_type_str = site_cfg.get("content_type", "post")

        pending: List[str] = list(start_urls)
        visited: set = set()
        pages_fetched = 0
        mentions: List[RawMention] = []
        total_delay = 0.0

        while pending and pages_fetched < max_pages:
            url = pending.pop(0)
            if url in visited:
                continue
            visited.add(url)

            # polite delay (skip on the very first fetch)
            if pages_fetched > 0 and delay > 0:
                time.sleep(delay)
                total_delay += delay

            html = self._fetch(url)
            pages_fetched += 1
            items = parser.parse(html, url)

            for item in items:
                title = item.get("title", "")
                content_type = item.get("content_type", "")

                # title-filter & URL discovery (for stories/listings):
                # follow item links whose title mentions the company or an alt spelling
                if title:
                    if not matches_company(
                        title, request.company, request.alt_spellings, request.handles
                    ):
                        continue
                    # Only enqueue item page links for top-level stories/posts
                    permalink = item.get("permalink", "")
                    if permalink:
                        abs_permalink = urljoin(url, permalink)
                        if abs_permalink not in visited and abs_permalink not in pending:
                            pending.append(abs_permalink)

                # text-filter: keep items whose text (or title for posts) mentions the company
                text = item.get("text", "") or title
                if not matches_company(
                    text, request.company, request.alt_spellings, request.handles
                ):
                    continue

                raw_html = html[:5000]
                raw_payload = {
                    "item_id": item.get("item_id"),
                    "title": item.get("title"),
                    "author": item.get("author"),
                    "text": item.get("text"),
                    "link": item.get("link"),
                    "permalink": permalink,
                    "raw_html": raw_html,
                    "page_url": item.get("page_url"),
                    "license_note": site_cfg.get("license_note", ""),
                    "attribution": site_cfg.get("attribution", ""),
                    "content_type": item.get("content_type", content_type_str),
                    "points": item.get("points"),
                    "age": item.get("age"),
                    "comment_count": item.get("comment_count"),
                    "parent": item.get("parent"),
                    "indentation": item.get("indentation"),
                }

                ct_hint = None
                ct_val = item.get("content_type", content_type_str)
                if ct_val in ContentType.__members__:
                    ct_hint = ContentType(ct_val)

                mentions.append(RawMention(
                    schema_version="1.0",
                    company=request.company,
                    run_id=request.run_id,
                    platform=platform,
                    item_id=item.get("item_id") or "",
                    url=permalink or item.get("link") or "",
                    content_type_hint=ct_hint,
                    raw_payload=raw_payload,
                    source=site_key,
                    method_used=Method.scraping,
                    tool_used=f"Web scraper: {site_name}",
                    cost_usd=0.0,
                    collected_at=datetime.now(timezone.utc),
                ))

        return mentions, pages_fetched, total_delay

    # ------------------------------------------------------------------ #
    # private: HTTP fetch (thin wrapper, easy to mock)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _fetch(url: str) -> str:
        contact = os.getenv("SCRAPER_CONTACT", "")
        resp = http_client.get(
            url, timeout=30,
            headers={"User-Agent": f"social-listening-bot (contact: {contact})"},
        )
        resp.raise_for_status()
        return resp.text

    # ------------------------------------------------------------------ #
    # private: build a CollectionAttempt
    # ------------------------------------------------------------------ #
    @staticmethod
    def _make_attempt(
        request: CollectionRequest,
        site_cfg: dict,
        status: AttemptStatus,
        *,
        reason: str,
        scraping_checks: Dict[str, bool],
        started_at: datetime,
        item_count: int = 0,
        pages_fetched: int = 0,
        pages_from_cache: int = 0,
        delay_used: float = 0.0,
    ) -> CollectionAttempt:
        platform_str = site_cfg.get("platform", "other")
        platform = Platform(platform_str) if platform_str in Platform.__members__ else Platform.other
        return CollectionAttempt(
            company=request.company,
            platform=platform,
            method=Method.scraping,
            status=status,
            reason=reason,
            item_count=item_count,
            cost_usd=0.0,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            scraping_checks=scraping_checks,
            pages_fetched=pages_fetched,
            pages_from_cache=pages_from_cache,
            delay_used=delay_used,
        )
