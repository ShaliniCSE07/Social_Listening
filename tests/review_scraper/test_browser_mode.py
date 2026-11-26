"""Tests for dynamic (browser) scraping and the auto/static/browser modes."""
import http.server
import json
import sys
import threading

import pytest
from fastapi.testclient import TestClient

from src.review_scraper import engine
from src.review_scraper.browser import BrowserFetcher, browser_available
from src.review_scraper.extractors import extract_reviews
from src.review_scraper.fetcher import Fetcher, FetchError
from src.review_scraper.engine import scrape_reviews

STATIC_SHELL = "<html><body><h1>Shop</h1><div id='reviews'></div><script>/* reviews loaded by JS */</script></body></html>"
RENDERED = """
<html><body><h1>Shop</h1><div id='reviews'>
  <div class="review-card"><span class="review-author">Asha</span><span class="rating" aria-label="5 out of 5 stars"></span>
    <p class="review-text">Arrived quickly and works perfectly, very happy.</p></div>
  <div class="review-card"><span class="review-author">Ravi</span><span class="rating" aria-label="2 out of 5 stars"></span>
    <p class="review-text">Stopped working after two weeks, poor quality.</p></div>
</div></body></html>
"""


class Pages(Fetcher):
    def __init__(self, pages, is_browser=False):
        super().__init__(respect_robots=False)
        self.pages, self.is_browser, self.calls, self.closed = pages, is_browser, 0, False

    def fetch(self, url):
        self.calls += 1
        if url not in self.pages:
            raise FetchError("The website returned HTTP 403. The site may block automated tools.")
        return url, self.pages[url]

    def close(self):
        self.closed = True


URL = "https://shop.example/item"


def test_auto_switches_to_browser_when_html_has_no_reviews():
    static, browser = Pages({URL: STATIC_SHELL}), Pages({URL: RENDERED}, is_browser=True)
    res = scrape_reviews(URL, fetcher=static, browser_factory=lambda: browser, delay_seconds=0)
    assert res.mode_used == "browser" and len(res.mentions) == 2
    assert static.calls == 1 and browser.calls == 1 and browser.closed
    assert "loaded in a browser" in res.warnings[0]
    m = res.mentions[0]
    assert m.raw_payload["rendered_with_browser"] is True and m.tool_used.endswith(", browser)")
    assert m.raw_payload["rating"] == 5.0


def test_auto_stays_static_when_html_has_reviews():
    def no_browser():
        raise AssertionError("browser should not be started")

    res = scrape_reviews(URL, fetcher=Pages({URL: RENDERED}), browser_factory=no_browser, delay_seconds=0)
    assert res.mode_used == "static" and len(res.mentions) == 2
    assert res.mentions[0].raw_payload["rendered_with_browser"] is False


def test_static_mode_never_uses_browser():
    res = scrape_reviews(URL, fetcher=Pages({URL: STATIC_SHELL}), mode="static",
                         browser_factory=lambda: pytest.fail("browser started"), delay_seconds=0)
    assert res.mode_used == "static" and res.mentions == [] and "JavaScript" in res.warnings[0]


def test_browser_mode_skips_static_fetch():
    static, browser = Pages({URL: STATIC_SHELL}), Pages({URL: RENDERED}, is_browser=True)
    res = scrape_reviews(URL, fetcher=static, mode="browser", browser_factory=lambda: browser, delay_seconds=0)
    assert static.calls == 0 and res.mode_used == "browser" and len(res.mentions) == 2


def test_auto_does_not_retry_in_browser_after_http_error():
    res = scrape_reviews(URL, fetcher=Pages({}), browser_factory=lambda: pytest.fail("browser started"), delay_seconds=0)
    assert "HTTP 403" in res.error and res.mode_used == "static"


def test_auto_keeps_static_result_when_browser_fails():
    res = scrape_reviews(URL, fetcher=Pages({URL: STATIC_SHELL}),
                         browser_factory=lambda: Pages({}, is_browser=True), delay_seconds=0)
    assert res.mode_used == "static" and res.error is None
    assert any(w.startswith("Also tried loading the page in a browser") for w in res.warnings)


def test_browser_not_installed(monkeypatch):
    monkeypatch.setattr(engine, "browser_available", lambda: (False, "Browser mode is not installed."))
    res = scrape_reviews(URL, fetcher=Pages({URL: STATIC_SHELL}), mode="browser", delay_seconds=0)
    assert res.error == "Browser mode is not installed." and res.mode_used == "browser"

    res = scrape_reviews(URL, fetcher=Pages({URL: STATIC_SHELL}), mode="auto", delay_seconds=0)
    assert res.error is None and any("not installed" in w for w in res.warnings)


def test_browser_request_guard_blocks_private_and_non_web_addresses():
    bf = BrowserFetcher()
    assert not bf._host_allowed("http://127.0.0.1:8000/api/runs")
    assert not bf._host_allowed("http://10.1.2.3/")
    assert not bf._host_allowed("http://169.254.169.254/latest/meta-data")
    assert not bf._host_allowed("file:///C:/Windows/win.ini")
    assert bf._host_allowed("data:text/html,hi")


def test_api_mode_and_capabilities(monkeypatch, tmp_path):
    from src.service import main
    from src.service.routes import review_scraper as routes

    monkeypatch.setattr(routes, "SCRAPES_DIR", tmp_path / "scrapes")
    seen = {}

    def fake(url, **kw):
        seen.update(kw)
        return scrape_reviews(url, fetcher=Pages({url: STATIC_SHELL}),
                              browser_factory=lambda: Pages({url: RENDERED}, is_browser=True),
                              delay_seconds=0, **{k: v for k, v in kw.items() if k != "delay_seconds"})

    monkeypatch.setattr(routes, "scrape_reviews", fake)
    client = TestClient(main.app)
    body = client.post("/api/review-scraper", json={"url": URL, "mode": "browser"}).json()
    assert seen["mode"] == "browser" and body["mode_requested"] == "browser" and body["mode_used"] == "browser"
    assert body["reviews_count"] == 2

    assert client.post("/api/review-scraper", json={"url": URL, "mode": "turbo"}).status_code == 422

    caps = client.get("/api/review-scraper/capabilities").json()
    assert set(caps) == {"browser_available", "browser_reason"}


# ── real headless browser (skipped when Playwright/Chromium are not installed) ──

JS_PAGE = """<!doctype html><html><head><title>JS Shop</title></head><body>
<h1>JS Shop item</h1><div id="reviews">Loading reviews...</div>
<script>
fetch('/reviews.json').then(r => r.json()).then(list => {
  const box = document.getElementById('reviews'); box.innerHTML = '';
  for (const r of list) {
    const d = document.createElement('div'); d.className = 'review-card';
    d.innerHTML = '<span class="review-author"></span><span class="rating"></span><p class="review-text"></p>';
    d.querySelector('.review-author').textContent = r.author;
    d.querySelector('.rating').setAttribute('aria-label', r.stars + ' out of 5 stars');
    d.querySelector('.review-text').textContent = r.text;
    box.appendChild(d);
  }
});
</script></body></html>"""
REVIEWS_JSON = [
    {"author": "Meera", "stars": 4, "text": "Good value for money, delivery took a little long."},
    {"author": "Karan", "stars": 1, "text": "Wrong size sent and the return process was painful."},
    {"author": "Zoe", "stars": 5, "text": "Exactly as described, would definitely buy again."},
]


@pytest.fixture
def js_server():
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/reviews.json":
                body, ctype = json.dumps(REVIEWS_JSON).encode(), "application/json"
            elif self.path == "/robots.txt":
                body, ctype = b"User-agent: *\nAllow: /\n", "text/plain"
            else:
                body, ctype = JS_PAGE.encode(), "text/html; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/item"
    srv.shutdown()


@pytest.mark.skipif(not browser_available()[0], reason="Playwright Chromium not installed")
def test_real_browser_renders_javascript_reviews(js_server):
    # The raw HTML has no reviews...
    assert extract_reviews(JS_PAGE, js_server)[0] == []
    # ...but the rendered page does. allow_private only because the test server is local.
    factory = lambda: BrowserFetcher(robots_fetcher=Fetcher(respect_robots=False), allow_private=True)  # noqa: E731
    res = scrape_reviews(js_server, mode="browser", browser_factory=factory, max_pages=1, delay_seconds=0)
    assert res.error is None, res.error
    assert res.mode_used == "browser"
    by_author = {m.raw_payload["author"]: m.raw_payload for m in res.mentions}
    assert set(by_author) == {"Meera", "Karan", "Zoe"}
    assert by_author["Karan"]["rating"] == 1.0 and by_author["Zoe"]["rating"] == 5.0
    assert all(p["rendered_with_browser"] for p in by_author.values())


# ── bot-protection pages and redirects ──

from src.review_scraper.fetcher import CHALLENGE_MESSAGE, is_bot_challenge  # noqa: E402

CHALLENGE_PAGE = """<!doctype html><html><head><title>Just a moment...</title></head><body>
<div class="main-wrapper"><div class="main-content"><h1>www.shop.example</h1>
<p>Performing security verification</p><p>This website uses a security service to protect against malicious bots.</p>
<div id="cf-chl-widget"></div></div></div>
<script src="/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1"></script></body></html>"""

REVIEWS_WITH_CAPTCHA_FORM = RENDERED.replace(
    "</body>",
    "<form class='comment-form'><div class='cf-turnstile' data-sitekey='x'></div>"
    "<p>Please verify you are human before posting.</p></form>"
    + "<p>" + ("Lots of real page text about the product and its specifications. " * 60) + "</p></body>",
)


def test_bot_challenge_detection():
    assert is_bot_challenge(CHALLENGE_PAGE)
    assert not is_bot_challenge(REVIEWS_WITH_CAPTCHA_FORM)  # real page that merely has a captcha on a form
    assert not is_bot_challenge(RENDERED)


class _CannedGet(Fetcher):
    """Real Fetcher.fetch logic, canned network responses."""

    def __init__(self, final_url, html, robots_ok=lambda u: True):
        super().__init__(respect_robots=False)
        self._final, self._html, self._robots_ok = final_url, html, robots_ok

    def _get(self, url, allow_error_status=False):
        return 200, self._html, self._final

    def robots_allows(self, url):
        return self._robots_ok(url)


def test_fetch_reports_bot_challenge(monkeypatch):
    monkeypatch.setattr("src.review_scraper.fetcher.validate_url", lambda u: u)
    with pytest.raises(FetchError) as exc:
        _CannedGet(URL, CHALLENGE_PAGE).fetch(URL)
    assert str(exc.value) == CHALLENGE_MESSAGE


def test_fetch_rechecks_robots_after_redirect(monkeypatch):
    monkeypatch.setattr("src.review_scraper.fetcher.validate_url", lambda u: u)
    f = _CannedGet("https://shop.example/private/list", RENDERED, robots_ok=lambda u: "/private/" not in u)
    with pytest.raises(FetchError) as exc:
        f.fetch(URL)
    assert "redirected" in str(exc.value)


def test_auto_reports_bot_check_from_browser():
    class Blocked(Pages):
        def fetch(self, url):
            raise FetchError(CHALLENGE_MESSAGE)

    res = scrape_reviews(URL, fetcher=Pages({URL: STATIC_SHELL}),
                         browser_factory=lambda: Blocked({}, is_browser=True), delay_seconds=0)
    assert res.mentions == [] and res.error is None
    assert any("bot-protection check" in w for w in res.warnings)


@pytest.mark.skipif(sys.platform != "win32" or not browser_available()[0],
                    reason="Windows-only uvicorn event-loop issue; needs Playwright Chromium")
def test_browser_starts_under_uvicorn_windows_loop_policy():
    """uvicorn --reload sets WindowsSelectorEventLoopPolicy, whose loops cannot start
    subprocesses; the browser must still start, and the policy must be restored."""
    import asyncio

    previous = asyncio.get_event_loop_policy()
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    outcome = {}

    def run():
        try:
            with BrowserFetcher() as bf:
                bf._start()
                outcome["version"] = bf._browser.version
        except Exception as exc:  # pragma: no cover - reported below
            outcome["error"] = repr(exc)

    try:
        t = threading.Thread(target=run)
        t.start()
        t.join(timeout=120)
        assert "error" not in outcome, outcome.get("error")
        assert outcome.get("version")
        assert isinstance(asyncio.get_event_loop_policy(), asyncio.WindowsSelectorEventLoopPolicy)
    finally:
        asyncio.set_event_loop_policy(previous)


@pytest.mark.parametrize("message,expected", [
    ("Page.goto: net::ERR_HTTP2_PROTOCOL_ERROR at https://site.example/r", "bot protection"),
    ("Page.goto: net::ERR_CONNECTION_RESET at https://site.example/r", "bot protection"),
    ("Page.goto: net::ERR_NAME_NOT_RESOLVED at https://nope.example/", "Could not find that website"),
    ("Page.goto: net::ERR_CERT_DATE_INVALID at https://site.example/", "security certificate"),
    ("Page.goto: net::ERR_SOMETHING_NEW at https://site.example/", "(ERR_SOMETHING_NEW)"),
    ("Page.goto: Timeout 30000ms exceeded.", "took too long"),
])
def test_navigation_errors_are_explained(message, expected):
    from src.review_scraper.browser import explain_navigation_error

    class Error(Exception):
        pass

    assert expected in explain_navigation_error(Error(message))
