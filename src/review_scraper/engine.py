"""Review scraper engine: one URL in, RawMention reviews out."""
import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from src.contracts.enums import ContentType, Method, Platform
from src.contracts.schemas import RawMention
from src.review_scraper.browser import BrowserFetcher, browser_available
from src.review_scraper.extractors import extract_reviews, find_next_page, page_rating_summary, page_subject
from src.review_scraper.fetcher import Fetcher, FetchError

log = logging.getLogger(__name__)

MAX_PAGES_LIMIT = 10
MAX_REVIEWS_LIMIT = 1000
DEFAULT_DELAY_SECONDS = 1.0
MODES = ("auto", "static", "browser")

_DOMAIN_PLATFORMS = {
    "tripadvisor.": Platform.tripadvisor,
    "google.": Platform.google,
    "facebook.com": Platform.facebook,
    "instagram.com": Platform.instagram,
    "linkedin.com": Platform.linkedin,
    "reddit.com": Platform.reddit,
    "twitter.com": Platform.twitter_x,
    "x.com": Platform.twitter_x,
}


def platform_for(host: str) -> Platform:
    host = host.lower()
    for key, plat in _DOMAIN_PLATFORMS.items():
        if host == key or host.endswith("." + key) or (key.endswith(".") and key in host):
            return plat
    return Platform.other


@dataclass
class ScrapeResult:
    url: str
    company: str
    mentions: List[RawMention] = field(default_factory=list)
    pages_fetched: int = 0
    pages_skipped_robots: int = 0
    methods: Dict[str, int] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    error: Optional[str] = None
    mode_used: str = "static"  # "static" (page HTML) or "browser" (rendered with JavaScript)
    page_rating: Optional[Tuple[float, Optional[int]]] = None  # overall rating shown when no reviews were found


NO_REVIEWS_HINT = (
    "No reviews were found on this page. The site may load reviews with JavaScript, "
    "require a login, or show them on a different page (look for a 'See all reviews' link)."
)
NO_REVIEWS_AFTER_BROWSER = (
    "No reviews were found, even after loading the page in a browser. The reviews may need a login "
    "or a click to open, or be on a different page (look for a 'See all reviews' link)."
)


def scrape_reviews(
    url: str,
    company: Optional[str] = None,
    max_pages: int = 3,
    max_reviews: int = 200,
    run_id: Optional[str] = None,
    fetcher: Optional[Fetcher] = None,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    mode: str = "auto",
    browser_factory: Optional[Callable[[], Any]] = None,
) -> ScrapeResult:
    """Scrape reviews from ``url`` (and up to ``max_pages-1`` 'next' pages).

    ``mode``: ``static`` reads the page HTML only (fast); ``browser`` renders
    the page in headless Chromium so JavaScript-loaded reviews appear;
    ``auto`` tries static first and switches to the browser only when the
    HTML has no reviews. Never raises for site problems: they end up in
    ``result.error`` / ``result.warnings`` with a readable message.
    """
    if mode not in MODES:
        mode = "auto"
    max_pages = max(1, min(int(max_pages), MAX_PAGES_LIMIT))
    max_reviews = max(1, min(int(max_reviews), MAX_REVIEWS_LIMIT))
    args = (url, company, max_pages, max_reviews, run_id, delay_seconds)

    def with_browser() -> ScrapeResult:
        if browser_factory is None:
            ok, reason = browser_available()
            if not ok:
                res = ScrapeResult(url=url, company=(company or "").strip(), mode_used="browser")
                res.error = reason
                return res
        factory = browser_factory or BrowserFetcher
        bf = factory()
        try:
            res = _scrape(*args, fetcher=bf)
        finally:
            close = getattr(bf, "close", None)
            if close:
                close()
        res.mode_used = "browser"
        if not res.error and not res.mentions:
            res.warnings = [w for w in res.warnings if w != NO_REVIEWS_HINT] + [NO_REVIEWS_AFTER_BROWSER]
        return res

    if mode == "browser":
        return with_browser()

    static = _scrape(*args, fetcher=fetcher or Fetcher())
    if mode == "static" or static.error or static.mentions:
        return static

    # auto: the HTML had no reviews -> probably loaded by JavaScript
    if browser_factory is None and not browser_available()[0]:
        static.warnings.append("Browser mode (for JavaScript-loaded pages) is not installed, so it was not tried.")
        return static
    browser_res = with_browser()
    if browser_res.error:
        static.warnings.append(f"Also tried loading the page in a browser, but: {browser_res.error}")
        return static
    if browser_res.mentions:
        browser_res.warnings.insert(0, "The page HTML had no reviews, so it was loaded in a browser to run its JavaScript.")
    return browser_res


def _scrape(
    url: str,
    company: Optional[str],
    max_pages: int,
    max_reviews: int,
    run_id: Optional[str],
    delay_seconds: float,
    fetcher: Any,
) -> ScrapeResult:
    result = ScrapeResult(url=url, company=(company or "").strip())
    rendered = bool(getattr(fetcher, "is_browser", False))
    seen: set = set()
    now = datetime.now(timezone.utc)

    page_url: Optional[str] = url
    visited: set = set()
    while page_url and result.pages_fetched < max_pages and len(result.mentions) < max_reviews:
        if page_url in visited:
            break
        visited.add(page_url)
        if result.pages_fetched > 0:
            time.sleep(max(delay_seconds, fetcher.crawl_delay(page_url)))
        try:
            final_url, html = fetcher.fetch(page_url)
        except FetchError as exc:
            if result.pages_fetched == 0:
                result.error = str(exc)
            else:
                result.warnings.append(f"Stopped at page {result.pages_fetched + 1}: {exc}")
            break
        result.pages_fetched += 1

        reviews, item_name, soup = extract_reviews(html, final_url)
        if not reviews and result.page_rating is None:
            result.page_rating = page_rating_summary(soup)
        if not result.company:
            result.company = item_name or page_subject(soup) or urlsplit(final_url).hostname or "Unknown"

        host = urlsplit(final_url).hostname or ""
        platform = platform_for(host)
        for rv in reviews:
            key = hashlib.sha1(rv["text"].lower().encode("utf-8")).hexdigest()
            if key in seen:
                continue
            seen.add(key)
            result.methods[rv["extraction_method"]] = result.methods.get(rv["extraction_method"], 0) + 1
            payload: Dict[str, Any] = {
                "text": rv["text"],
                "title": rv["title"],
                "rating": rv["rating"],
                "recommended": rv.get("recommended"),
                "rating_raw": rv["rating_raw"],
                "best_rating": rv["best_rating"],
                "author": rv["author"],
                "date": rv["date"],
                "review_id": rv["review_id"],
                "review_url": rv["url"],
                "page_url": final_url,
                "source_url": url,
                "item_reviewed": item_name,
                "extraction_method": rv["extraction_method"],
                "rendered_with_browser": rendered,
            }
            result.mentions.append(RawMention(
                company=result.company,
                run_id=run_id,
                platform=platform,
                item_id=rv["review_id"] or key[:16],
                url=rv["url"] or final_url,
                content_type_hint=ContentType.review,
                raw_payload=payload,
                source=host,
                method_used=Method.scraping,
                tool_used=f"Review Scraper ({rv['extraction_method']}{', browser' if rendered else ''})",
                collected_at=now,
            ))
            if len(result.mentions) >= max_reviews:
                break

        page_url = find_next_page(soup, final_url) if result.pages_fetched < max_pages else None

    if not result.error and not result.mentions:
        if result.page_rating:
            value, count = result.page_rating
            result.warnings.append(
                f"This page shows an overall rating of {value:.1f}/5"
                + (f" from {count:,} ratings" if count else "")
                + ", but not the individual reviews. The site may hide review texts from automated tools."
            )
        result.warnings.append(NO_REVIEWS_HINT)
    if len(result.mentions) >= max_reviews:
        result.warnings.append(f"Stopped at the limit of {max_reviews} reviews.")
    return result
