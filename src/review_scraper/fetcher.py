"""Safe page fetching for the review scraper.

The backend fetches whatever URL a user types, so every request (and every
redirect hop) is checked: only http/https, only public internet addresses
(no localhost / private / link-local ranges), a size cap and a timeout.
robots.txt is honoured.
"""
import ipaddress
import logging
import os
import re
import socket
from typing import Dict, Optional, Tuple
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup, UnicodeDammit

log = logging.getLogger(__name__)

ROBOTS_USER_AGENT = "social-listening-bot"
TIMEOUT_SECONDS = 20
MAX_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5


class FetchError(Exception):
    """A page could not be fetched; the message is safe to show users."""


def user_agent() -> str:
    contact = os.getenv("SCRAPER_CONTACT", "").strip()
    return f"{ROBOTS_USER_AGENT} (review-scraper{'; contact: ' + contact if contact else ''})"


def validate_url(url: str) -> str:
    """Return the cleaned URL or raise FetchError if it is not a public http(s) URL."""
    url = (url or "").strip()
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise FetchError("Only http:// and https:// links are supported.")
    if not parts.hostname:
        raise FetchError("The link has no website address.")
    if parts.username or parts.password:
        raise FetchError("Links with a username or password are not supported.")
    _ensure_public_host(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
    return url


def _ensure_public_host(host: str, port: int) -> None:
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise FetchError(f"Could not find the website '{host}'. Check the link.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global or ip.is_multicast:
            raise FetchError("Links to local or private network addresses are not allowed.")


# Pages shown by bot-protection services instead of the real content. The
# scraper reports these clearly; it does not try to get past them.
_CHALLENGE_MARKERS = re.compile(
    r"performing security verification|just a moment\.\.\.|checking your browser before accessing|"
    r"attention required! \| cloudflare|cf-chl-|challenge-platform|verify you are (a )?human|"
    r"are you a robot|captcha-delivery\.com|px-captcha|_incapsula_resource|access denied</title>",
    re.I,
)
CHALLENGE_MESSAGE = (
    "The website showed a bot-protection check (for example Cloudflare's \"security verification\" or a "
    "captcha) instead of its content. This scraper does not bypass such checks; use an official API or "
    "data provider for this site."
)


def is_bot_challenge(html: str) -> bool:
    """True for a bot-check / captcha page (strong marker and little real text)."""
    if not html or not _CHALLENGE_MARKERS.search(html):
        return False
    visible = BeautifulSoup(html, "html.parser")
    for el in visible(["script", "style", "noscript", "template"]):
        el.decompose()
    return len(visible.get_text(" ", strip=True)) < 2500


def check_page(fetcher, final_url: str, html: str) -> None:
    """Shared after-fetch checks: robots.txt for the page we ended up on, and bot checks."""
    if not fetcher.robots_allows(final_url):
        raise FetchError("The page redirected to an address that this website's robots.txt does not allow.")
    if is_bot_challenge(html):
        raise FetchError(CHALLENGE_MESSAGE)


class Fetcher:
    """Fetches pages politely and safely; caches robots.txt per host."""

    def __init__(self, session: Optional[requests.Session] = None, respect_robots: bool = True):
        self.session = session or requests.Session()
        self.respect_robots = respect_robots
        self._robots: Dict[str, Optional[RobotFileParser]] = {}

    def robots_allows(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parts = urlsplit(url)
        key = f"{parts.scheme}://{parts.netloc}"
        if key not in self._robots:
            rp = RobotFileParser(f"{key}/robots.txt")
            try:
                status, text, _ = self._get(f"{key}/robots.txt", allow_error_status=True)
                if status in (401, 403):
                    rp.disallow_all = True
                elif status >= 400:
                    rp.allow_all = True
                else:
                    rp.parse(text.splitlines())
            except FetchError:
                rp.allow_all = True  # robots.txt unreachable: treat as no rules
            self._robots[key] = rp
        rp = self._robots[key]
        return rp is None or rp.can_fetch(ROBOTS_USER_AGENT, url)

    def crawl_delay(self, url: str) -> float:
        parts = urlsplit(url)
        rp = self._robots.get(f"{parts.scheme}://{parts.netloc}")
        try:
            return float(rp.crawl_delay(ROBOTS_USER_AGENT) or 0) if rp else 0.0
        except Exception:
            return 0.0

    def fetch(self, url: str) -> Tuple[str, str]:
        """Return (final_url, html). Raises FetchError with a readable message."""
        url = validate_url(url)
        if not self.robots_allows(url):
            raise FetchError("This website's robots.txt does not allow automated access to that page.")
        status, text, final_url = self._get(url)
        check_page(self, final_url, text)
        return final_url, text

    def _get(self, url: str, allow_error_status: bool = False) -> Tuple[int, str, str]:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            validate_url(current)
            try:
                resp = self.session.get(
                    current,
                    timeout=TIMEOUT_SECONDS,
                    allow_redirects=False,
                    stream=True,
                    headers={
                        "User-Agent": user_agent(),
                        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
                        "Accept-Language": "en;q=0.9,*;q=0.5",
                    },
                )
            except requests.Timeout:
                raise FetchError("The website took too long to respond. Some sites deliberately don't answer automated tools.")
            except requests.RequestException as exc:
                raise FetchError(f"Could not connect to the website ({type(exc).__name__}).")

            if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("Location")
                resp.close()
                if not location:
                    raise FetchError("The website sent a redirect without a destination.")
                current = urljoin(current, location)
                continue

            if resp.status_code >= 400 and not allow_error_status:
                resp.close()
                hint = " The site may block automated tools." if resp.status_code in (401, 403, 429) else ""
                raise FetchError(f"The website returned HTTP {resp.status_code}.{hint}")

            chunks, size = [], 0
            for chunk in resp.iter_content(64 * 1024):
                size += len(chunk)
                if size > MAX_BYTES:
                    resp.close()
                    raise FetchError("The page is larger than 5 MB, which is too big to scrape.")
                chunks.append(chunk)
            raw = b"".join(chunks)
            # Only trust an explicit charset; otherwise let BeautifulSoup sniff
            # (meta tags, BOM, byte patterns) to avoid mojibake.
            declared = "charset=" in resp.headers.get("Content-Type", "").lower()
            if declared and resp.encoding:
                text = raw.decode(resp.encoding, errors="replace")
            else:
                text = UnicodeDammit(raw, is_html=True).unicode_markup or raw.decode("utf-8", errors="replace")
            return resp.status_code, text, current
        raise FetchError("The website redirected too many times.")
