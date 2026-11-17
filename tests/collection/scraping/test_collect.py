"""Tests for ScrapingConnector.collect() — attempts, filters, payload, limits, URL scan."""
import json
import os
import re
from pathlib import Path
from unittest import mock

import pytest

from src.collection.base import CollectionRequest
from src.collection.plugins.scraping.connector import (
    ScrapingConnector,
    _reset_sites_cfg,
)
from src.contracts.enums import AttemptStatus, Method, Platform


# ====================================================================
# Fixtures – tiny HTML for listing / item pages
# ====================================================================
LISTING_HTML = """\
<html><body><table>
<tr class="athing" id="11"><td class="title">
  <a href="item?id=11" class="storylink">Zomato launches feature</a></td></tr>
<tr><td class="subtext">
  <span class="score">10 points</span>
  <a class="hnuser">alice</a><span class="age">1 hour ago</span>
  <a href="item?id=11">5 comments</a></td></tr>
<tr class="athing" id="22"><td class="title">
  <a href="item?id=22" class="storylink">Unrelated topic</a></td></tr>
<tr><td class="subtext">
  <span class="score">3 points</span>
  <a class="hnuser">bob</a><span class="age">2 hours ago</span>
  <a href="item?id=22">1 comments</a></td></tr>
</table></body></html>
"""

ITEM_HTML_MATCH = """\
<html><head><title>Zomato launches feature</title></head><body>
<table>
<tr class="fatitem"><td class="title">
  <a href="https://zomato.com/press" class="storylink">Zomato launches feature</a></td></tr>
<tr><td class="subtext">
  <span class="score">10 points</span>
  <a class="hnuser">alice</a><span class="age">1 hour ago</span></td></tr>
<tr class="comment" id="c1" data-parent="11"><td>
  <img class="indent" src="s.gif" width="0"/>
  <a class="hnuser">dan</a><span class="age">50 min ago</span>
  <span class="commtext">I love Zomato food delivery</span></td></tr>
<tr class="comment" id="c2" data-parent="11"><td>
  <img class="indent" src="s.gif" width="0"/>
  <a class="hnuser">eve</a><span class="age">45 min ago</span>
  <span class="commtext">Nothing about the company here</span></td></tr>
</table></body></html>
"""


# ====================================================================
# Helpers
# ====================================================================
def _fake_site_cfg(allows=True, max_pages=5, delay=0):
    return {
        "testsite": {
            "key": "testsite",
            "name": "Test Site",
            "allows_scraping": allows,
            "platform": "other",
            "content_type": "post",
            "start_urls": ["https://test.example/news"],
            "max_pages": max_pages,
            "min_delay_seconds": delay,
            "parser": "hackernews",
            "license_note": "CC-BY",
            "attribution": "Test Site",
        }
    }


def _two_site_cfg():
    """Two sites — one allowed, one blocked."""
    cfg = _fake_site_cfg(allows=True)
    cfg["blocked"] = {
        "key": "blocked",
        "name": "Blocked Site",
        "allows_scraping": False,
        "platform": "other",
        "content_type": "post",
        "start_urls": ["https://blocked.example/news"],
        "max_pages": 3,
        "min_delay_seconds": 0,
        "parser": "hackernews",
        "license_note": "",
        "attribution": "",
    }
    return cfg


def _inject_cfg(monkeypatch, cfg):
    """Inject a fake site config dict."""
    import src.collection.plugins.scraping.connector as mod
    _reset_sites_cfg()
    monkeypatch.setattr(mod, "_sites_cfg", cfg)


def _mock_fetch(monkeypatch, url_to_html):
    """Replace ScrapingConnector._fetch with a dict-based lookup."""
    def fake_fetch(url):
        # Match more specific patterns first (e.g. "item" before "news" if both present)
        for pattern in sorted(url_to_html.keys(), key=lambda p: -len(p)):
            if pattern in url:
                return url_to_html[pattern]
        return "<html></html>"
    monkeypatch.setattr(ScrapingConnector, "_fetch", staticmethod(fake_fetch))


def _request(**kw):
    defaults = dict(company="Zomato", scraping_allowed=True)
    defaults.update(kw)
    return CollectionRequest(**defaults)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("SCRAPER_CONTACT", "bot@test.example")
    yield
    _reset_sites_cfg()


# ====================================================================
# 1.  Attempt per site – success / empty / failed / skipped
# ====================================================================
class TestAttemptPerSite:
    def test_skipped_when_policy_disallows(self, monkeypatch):
        _inject_cfg(monkeypatch, _fake_site_cfg(allows=False))
        _mock_fetch(monkeypatch, {})
        mentions, attempts = ScrapingConnector().collect(_request())
        assert len(attempts) == 1
        att = attempts[0]
        assert att.status == AttemptStatus.skipped
        assert att.scraping_checks == {"site_policy_allows": False}
        assert "disallows" in att.reason
        assert len(mentions) == 0

    def test_success_when_items_found(self, monkeypatch):
        _inject_cfg(monkeypatch, _fake_site_cfg())
        _mock_fetch(monkeypatch, {"news": LISTING_HTML, "item": ITEM_HTML_MATCH})
        mentions, attempts = ScrapingConnector().collect(_request())
        att = [a for a in attempts if a.status == AttemptStatus.success]
        assert len(att) == 1
        assert att[0].item_count > 0
        assert att[0].scraping_checks == {"site_policy_allows": True}
        assert att[0].pages_fetched >= 1

    def test_empty_when_no_items(self, monkeypatch):
        _inject_cfg(monkeypatch, _fake_site_cfg())
        _mock_fetch(monkeypatch, {"news": "<html></html>"})
        mentions, attempts = ScrapingConnector().collect(_request())
        att = attempts[0]
        assert att.status == AttemptStatus.empty
        assert att.item_count == 0

    def test_failed_on_fetch_error(self, monkeypatch):
        _inject_cfg(monkeypatch, _fake_site_cfg())

        def boom(url):
            raise ConnectionError("network down")
        monkeypatch.setattr(ScrapingConnector, "_fetch", staticmethod(boom))

        mentions, attempts = ScrapingConnector().collect(_request())
        att = attempts[0]
        assert att.status == AttemptStatus.failed
        assert "network down" in att.reason
        assert len(mentions) == 0

    def test_one_site_failing_does_not_stop_another(self, monkeypatch):
        cfg = _two_site_cfg()
        _inject_cfg(monkeypatch, cfg)

        call_count = {"n": 0}
        def selective_fetch(url):
            call_count["n"] += 1
            if "blocked" in url:
                raise RuntimeError("should not be called — site is skipped")
            if "news" in url:
                return LISTING_HTML
            return ITEM_HTML_MATCH
        monkeypatch.setattr(ScrapingConnector, "_fetch", staticmethod(selective_fetch))

        mentions, attempts = ScrapingConnector().collect(_request())
        # Two attempts: one for testsite, one skipped for blocked
        assert len(attempts) == 2
        statuses = {a.status for a in attempts}
        assert AttemptStatus.skipped in statuses
        # The allowed site should have succeeded or been empty (not failed)
        allowed = [a for a in attempts if a.scraping_checks["site_policy_allows"]]
        assert len(allowed) == 1
        assert allowed[0].status in (AttemptStatus.success, AttemptStatus.empty)

    def test_no_exception_escapes_collect(self, monkeypatch):
        """Even if *every* site blows up, collect returns normally."""
        _inject_cfg(monkeypatch, _fake_site_cfg())

        def explode(url):
            raise RuntimeError("kaboom")
        monkeypatch.setattr(ScrapingConnector, "_fetch", staticmethod(explode))

        mentions, attempts = ScrapingConnector().collect(_request())
        assert isinstance(mentions, list)
        assert isinstance(attempts, list)
        assert all(a.status == AttemptStatus.failed for a in attempts)


# ====================================================================
# 2.  Attempt fields – pages_fetched, delay_used, scraping_checks
# ====================================================================
class TestAttemptFields:
    def test_pages_fetched_counted(self, monkeypatch):
        _inject_cfg(monkeypatch, _fake_site_cfg(max_pages=2))
        _mock_fetch(monkeypatch, {"news": LISTING_HTML, "item": ITEM_HTML_MATCH})
        _, attempts = ScrapingConnector().collect(_request())
        att = attempts[0]
        assert att.pages_fetched >= 1
        assert att.pages_fetched <= 2  # max_pages=2

    def test_delay_used_recorded(self, monkeypatch):
        # delay=0 → no sleeping, delay_used should be 0
        _inject_cfg(monkeypatch, _fake_site_cfg(delay=0))
        _mock_fetch(monkeypatch, {"news": LISTING_HTML, "item": ITEM_HTML_MATCH})
        _, attempts = ScrapingConnector().collect(_request())
        assert attempts[0].delay_used == 0.0

    def test_scraping_checks_present(self, monkeypatch):
        _inject_cfg(monkeypatch, _fake_site_cfg())
        _mock_fetch(monkeypatch, {"news": LISTING_HTML})
        _, attempts = ScrapingConnector().collect(_request())
        assert "site_policy_allows" in attempts[0].scraping_checks
        assert attempts[0].scraping_checks["site_policy_allows"] is True

    def test_reason_is_clear(self, monkeypatch):
        _inject_cfg(monkeypatch, _fake_site_cfg())
        _mock_fetch(monkeypatch, {"news": LISTING_HTML, "item": ITEM_HTML_MATCH})
        _, attempts = ScrapingConnector().collect(_request())
        att = attempts[0]
        assert att.reason  # non-empty
        # either "collected N items" or "no matching items found"
        assert "collected" in att.reason or "no matching" in att.reason


# ====================================================================
# 3.  Title and text company filter
# ====================================================================
class TestCompanyFilter:
    def test_title_filter_drops_unrelated(self, monkeypatch):
        _inject_cfg(monkeypatch, _fake_site_cfg())
        _mock_fetch(monkeypatch, {"news": LISTING_HTML, "item": ITEM_HTML_MATCH})
        mentions, _ = ScrapingConnector().collect(_request())
        # "Unrelated topic" (id=22) must not produce any mention
        ids = [m.item_id for m in mentions]
        assert "22" not in ids

    def test_text_filter_keeps_matching_comment(self, monkeypatch):
        _inject_cfg(monkeypatch, _fake_site_cfg())
        _mock_fetch(monkeypatch, {"news": LISTING_HTML, "item": ITEM_HTML_MATCH})
        mentions, _ = ScrapingConnector().collect(_request())
        texts = [m.raw_payload.get("text", "") for m in mentions]
        # comment c1 says "Zomato" → should be present
        assert any("Zomato" in (t or "") for t in texts)

    def test_text_filter_drops_nonmatching_comment(self, monkeypatch):
        _inject_cfg(monkeypatch, _fake_site_cfg())
        _mock_fetch(monkeypatch, {"news": LISTING_HTML, "item": ITEM_HTML_MATCH})
        mentions, _ = ScrapingConnector().collect(_request())
        ids = [m.item_id for m in mentions]
        # comment c2 has no company mention → should be absent
        assert "c2" not in ids


# ====================================================================
# 4.  Payload fields and raw_html limit
# ====================================================================
class TestPayloadFields:
    def test_required_fields_present(self, monkeypatch):
        _inject_cfg(monkeypatch, _fake_site_cfg())
        _mock_fetch(monkeypatch, {"news": LISTING_HTML, "item": ITEM_HTML_MATCH})
        mentions, _ = ScrapingConnector().collect(_request())
        assert len(mentions) > 0
        m = mentions[0]
        assert m.method_used == Method.scraping
        assert m.source == "testsite"
        assert m.tool_used == "Web scraper: Test Site"
        assert m.cost_usd == 0.0
        payload = m.raw_payload
        for key in ("item_id", "page_url", "license_note", "attribution", "raw_html"):
            assert key in payload, f"missing key: {key}"
        assert payload["license_note"] == "CC-BY"
        assert payload["attribution"] == "Test Site"

    def test_raw_html_truncated_to_5000(self, monkeypatch):
        big_html = LISTING_HTML + ("x" * 10_000)
        _inject_cfg(monkeypatch, _fake_site_cfg())
        _mock_fetch(monkeypatch, {"news": big_html, "item": big_html})
        mentions, _ = ScrapingConnector().collect(_request())
        for m in mentions:
            assert len(m.raw_payload["raw_html"]) <= 5000


# ====================================================================
# 5.  Max-pages limit
# ====================================================================
class TestMaxPages:
    def test_respects_max_pages(self, monkeypatch):
        _inject_cfg(monkeypatch, _fake_site_cfg(max_pages=1))
        fetch_urls = []

        def tracking_fetch(url):
            fetch_urls.append(url)
            return LISTING_HTML
        monkeypatch.setattr(ScrapingConnector, "_fetch", staticmethod(tracking_fetch))

        ScrapingConnector().collect(_request())
        assert len(fetch_urls) <= 1


# ====================================================================
# 6.  No real HTTP URL or site name in connector source files
# ====================================================================
class TestNoHardcodedUrls:
    """Scan *.py under src/collection/plugins/scraping/ for leaked URLs/names."""

    SRC_DIR = Path(__file__).resolve().parents[3] / "src" / "collection" / "plugins" / "scraping"

    # Patterns that must NOT appear (except inside CSS selectors)
    _URL_RE = re.compile(r'https?://[^\s\'"]+')
    # CSS selectors look like 'a.storylink', 'tr.athing', etc.
    _CSS_SELECTOR_RE = re.compile(
        r"""['"]          # opening quote
        [^'"]*            # content
        (?:               # known CSS patterns
          (?:tr|td|a|span|img|div)  # tag
          [.#\[]          # class / id / attr selector
        | \.              # bare class selector
        | \[              # attr selector
        )
        [^'"]*            # rest
        ['"]              # closing quote
        """,
        re.VERBOSE,
    )

    def _source_files(self):
        return list(self.SRC_DIR.rglob("*.py"))

    def test_no_http_urls_in_connector_source(self):
        """No http(s) URL should appear in .py files (parsers may have CSS selectors only)."""
        violations = []
        for py in self._source_files():
            for lineno, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
                for m in self._URL_RE.finditer(line):
                    url = m.group()
                    # Allow URLs inside string literals that are CSS selectors
                    # (CSS selectors never start with http)
                    violations.append(f"{py.name}:{lineno}: {url}")
        assert violations == [], "Hard-coded URLs found:\n" + "\n".join(violations)

    def test_no_site_names_in_connector_source(self):
        """Site names like 'hackernews' or 'Hacker News' must not be in connector.py."""
        connector_py = self.SRC_DIR / "connector.py"
        text = connector_py.read_text(encoding="utf-8")
        # Only the *connector* module should be free of site names;
        # parsers/hackernews.py is allowed to reference the site.
        for name in ("hackernews", "hacker news", "Hacker News"):
            assert name not in text, (
                f"connector.py should not contain site name '{name}' — "
                "all site-specific info must come from config"
            )

