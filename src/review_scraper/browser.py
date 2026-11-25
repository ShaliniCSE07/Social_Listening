"""Browser-based fetching (Playwright headless Chromium) for JavaScript-loaded pages.

Same interface as ``fetcher.Fetcher`` (``fetch`` / ``robots_allows`` /
``crawl_delay``) so the engine can use either. Safety rules match the plain
fetcher: robots.txt is honoured, and every request the page makes - not just
the first one - must go to a public internet address, so scripts on a page
cannot make the server's browser reach localhost or the private network.

The browser lives in the project folder (``<project>/.playwright``) unless
``PLAYWRIGHT_BROWSERS_PATH`` is already set.
"""
import asyncio
import logging
import os
import re
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Optional, Tuple
from urllib.parse import urlsplit

from src.review_scraper.fetcher import MAX_BYTES, Fetcher, FetchError, check_page, user_agent, validate_url

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BROWSERS_PATH = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or PROJECT_ROOT / ".playwright")
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(BROWSERS_PATH))

NAV_TIMEOUT_MS = 30_000
IDLE_TIMEOUT_MS = 8_000
MAX_SCROLL_ROUNDS = 25  # x 2500 px
REVIEW_SECTION_SELECTOR = "[id*='review' i]:not(script):not(style)"
SKIP_RESOURCE_TYPES = {"image", "media", "font"}
REVIEW_SELECTOR = "[class*='review' i], [id*='review' i], [itemprop='review'], [class*='comment' i]"
EXPAND_BUTTON_PATTERN = r"^\s*(load|show|see|view) more( reviews| comments)?\s*$"
INSTALL_HINT = (
    "Browser mode is not installed. In D:\\Social_Listening run: "
    ".venv\\Scripts\\python -m pip install playwright, then "
    "set PLAYWRIGHT_BROWSERS_PATH=D:\\Social_Listening\\.playwright and run "
    ".venv\\Scripts\\python -m playwright install --only-shell chromium"
)


_POLICY_LOCK = threading.Lock()


@contextmanager
def _subprocess_capable_loop():
    """On Windows, let Playwright create its event loop with the Proactor policy.

    uvicorn (with --reload) switches Windows to the Selector event loop policy,
    whose loops cannot start subprocesses, so Playwright fails to launch its
    driver with NotImplementedError. Playwright creates its loop inside
    ``sync_playwright().start()``, so the Proactor policy is set just for that
    call and the previous policy restored afterwards. Loops already running
    (uvicorn's own) are not affected.
    """
    if sys.platform != "win32":
        yield
        return
    with _POLICY_LOCK:
        previous = asyncio.get_event_loop_policy()
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        try:
            yield
        finally:
            asyncio.set_event_loop_policy(previous)


_BLOCKED_HINT = (
    "This usually means the site's bot protection refuses automated browsers. "
    "This scraper does not bypass such protection; use an official API or data provider for this site."
)
# Chromium network error codes -> plain-language explanations
_NET_ERRORS = {
    "ERR_HTTP2_PROTOCOL_ERROR": "The website cut the connection before sending the page. " + _BLOCKED_HINT,
    "ERR_CONNECTION_RESET": "The website reset the connection. " + _BLOCKED_HINT,
    "ERR_CONNECTION_CLOSED": "The website closed the connection without sending the page. " + _BLOCKED_HINT,
    "ERR_EMPTY_RESPONSE": "The website sent back an empty response. " + _BLOCKED_HINT,
    "ERR_NAME_NOT_RESOLVED": "Could not find that website. Check the link.",
    "ERR_CONNECTION_REFUSED": "The website refused the connection. It may be down.",
    "ERR_CONNECTION_TIMED_OUT": "The website did not respond in time.",
    "ERR_INTERNET_DISCONNECTED": "This computer seems to be offline.",
    "ERR_TOO_MANY_REDIRECTS": "The website redirected too many times.",
    "ERR_BLOCKED_BY_CLIENT": "The page was blocked because it points to a local or private network address.",
    "ERR_FAILED": "The browser could not load the page.",
}


def explain_navigation_error(exc: Exception) -> str:
    """Turn a Playwright navigation exception into a readable message."""
    text = str(exc)
    if "Timeout" in type(exc).__name__ or "Timeout" in text.split("\n", 1)[0]:
        return "The website took too long to load in the browser. Some sites deliberately don't answer automated tools."
    m = re.search(r"net::(ERR_[A-Z0-9_]+)", text)
    if m:
        code = m.group(1)
        if code.startswith("ERR_CERT") or code.startswith("ERR_SSL"):
            return f"The website's security certificate could not be verified ({code})."
        return f"{_NET_ERRORS.get(code, 'The browser could not open the page.')} ({code})"
    first = text.strip().splitlines()[0][:160] if text.strip() else type(exc).__name__
    return f"The browser could not open the page: {first}"


def browser_available() -> Tuple[bool, str]:
    """Whether Playwright and a Chromium build are installed."""
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False, INSTALL_HINT
    if not BROWSERS_PATH.is_dir() or not any(BROWSERS_PATH.glob("chromium*")):
        return False, INSTALL_HINT
    return True, "ready"


class BrowserFetcher:
    """Renders pages in headless Chromium. Use as a context manager (or call close())."""

    is_browser = True

    def __init__(self, robots_fetcher: Optional[Fetcher] = None, allow_private: bool = False):
        self.robots = robots_fetcher or Fetcher()
        self.allow_private = allow_private  # tests only: lets a local test server through
        self._pw = None
        self._browser = None
        self._context = None
        self._host_ok: Dict[str, bool] = {}

    # same helpers as Fetcher
    def robots_allows(self, url: str) -> bool:
        return self.robots.robots_allows(url)

    def crawl_delay(self, url: str) -> float:
        return self.robots.crawl_delay(url)

    def __enter__(self) -> "BrowserFetcher":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        for obj, method in ((self._context, "close"), (self._browser, "close"), (self._pw, "stop")):
            if obj is not None:
                try:
                    getattr(obj, method)()
                except Exception:  # closing must never raise
                    pass
        self._pw = self._browser = self._context = None

    def _start(self) -> None:
        if self._context is not None:
            return
        ok, reason = browser_available()
        if not ok:
            raise FetchError(reason)
        from playwright.sync_api import sync_playwright

        try:
            with _subprocess_capable_loop():
                self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=True)
        except Exception as exc:
            self.close()
            detail = str(exc).strip().splitlines()[0][:200] if str(exc).strip() else ""
            raise FetchError(
                f"Could not start the browser ({type(exc).__name__}{': ' + detail if detail else ''}). "
                "Restart the backend and try again; if it keeps failing, use Fast (HTML only) mode."
            )
        # Honest identification: real headless Chrome UA plus our bot token
        ua = (f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              f"HeadlessChrome/{self._browser.version} Safari/537.36 {user_agent()}")
        self._context = self._browser.new_context(
            user_agent=ua, locale="en-US", viewport={"width": 1366, "height": 900},
            accept_downloads=False, service_workers="block",
        )
        self._context.route("**/*", self._guard)

    def _host_allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        if parts.scheme in ("data", "blob", "about"):
            return True
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return False
        if self.allow_private:
            return True
        host = parts.hostname
        if host not in self._host_ok:
            try:
                validate_url(f"{parts.scheme}://{parts.netloc}/")
                self._host_ok[host] = True
            except FetchError:
                self._host_ok[host] = False
        return self._host_ok[host]

    def _guard(self, route) -> None:
        req = route.request
        if req.resource_type in SKIP_RESOURCE_TYPES or not self._host_allowed(req.url):
            route.abort()
        else:
            route.continue_()

    def fetch(self, url: str) -> Tuple[str, str]:
        """Return (final_url, rendered_html). Raises FetchError with a readable message."""
        if not self.allow_private:
            url = validate_url(url)
        if not self.robots_allows(url):
            raise FetchError("This website's robots.txt does not allow automated access to that page.")
        self._start()
        page = self._context.new_page()
        try:
            try:
                resp = page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
            except Exception as exc:
                raise FetchError(explain_navigation_error(exc))
            if resp is not None and resp.status >= 400:
                hint = " The site may block automated tools." if resp.status in (401, 403, 429) else ""
                raise FetchError(f"The website returned HTTP {resp.status}.{hint}")
            self._settle(page)
            html = page.content()
            if len(html.encode("utf-8", errors="ignore")) > MAX_BYTES * 2:
                raise FetchError("The rendered page is too large to scrape.")
            check_page(self, page.url, html)
            return page.url, html
        finally:
            try:
                page.close()
            except Exception:
                pass

    def _settle(self, page) -> None:
        """Give scripts time to load reviews: network idle, scroll, expand, wait."""
        def quiet(fn, *a, **kw):
            try:
                fn(*a, **kw)
            except Exception:
                pass

        quiet(page.wait_for_load_state, "networkidle", timeout=IDLE_TIMEOUT_MS)
        # Scroll down step by step until the bottom (long pages load reviews only when
        # their section comes into view), bounded so endless feeds still finish.
        for _ in range(MAX_SCROLL_ROUNDS):
            quiet(page.mouse.wheel, 0, 2500)
            quiet(page.wait_for_timeout, 450)
            try:
                if page.evaluate("window.scrollY + window.innerHeight >= document.body.scrollHeight - 50"):
                    break
            except Exception:
                break
        # Bring review sections into view directly, so lazy "load when visible" widgets fire
        try:
            sections = page.locator(REVIEW_SECTION_SELECTOR)
            for i in range(min(sections.count(), 4)):
                quiet(sections.nth(i).scroll_into_view_if_needed, timeout=2000)
                quiet(page.wait_for_timeout, 700)
        except Exception:
            pass
        # Click a few "Load more" / "Show more reviews" buttons (buttons only, never links)
        try:
            buttons = page.locator(f"button:text-matches('{EXPAND_BUTTON_PATTERN}', 'i')")
            for i in range(min(buttons.count(), 3)):
                quiet(buttons.nth(i).click, timeout=2000)
                quiet(page.wait_for_timeout, 800)
        except Exception:
            pass
        quiet(page.wait_for_selector, REVIEW_SELECTOR, timeout=3000)
        quiet(page.wait_for_load_state, "networkidle", timeout=3000)
