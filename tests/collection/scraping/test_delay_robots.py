"""Scraping delay and robots.txt handling."""
from pathlib import Path

import pytest
import requests
import yaml

import src.collection.plugins.scraping.connector as mod
from src.collection.base import CollectionRequest
from src.collection.plugins.scraping.connector import ScrapingConnector, _reset_sites_cfg
from tests.collection.scraping.test_collect import ITEM_HTML_MATCH, LISTING_HTML, _fake_site_cfg

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("SCRAPER_CONTACT", "bot@test.example")
    yield
    _reset_sites_cfg()


@pytest.fixture
def sleeps(monkeypatch):
    calls = []
    monkeypatch.setattr(mod.time, "sleep", lambda s: calls.append(s))
    return calls


def _setup(monkeypatch, robots, site_delay=0, max_pages=5):
    _reset_sites_cfg()
    monkeypatch.setattr(mod, "_sites_cfg", _fake_site_cfg(delay=site_delay, max_pages=max_pages))
    fetched = []

    def fake_fetch(url):
        fetched.append(url)
        if url.endswith("/robots.txt"):
            if isinstance(robots, Exception):
                raise robots
            return robots
        return ITEM_HTML_MATCH if "item" in url else LISTING_HTML

    monkeypatch.setattr(ScrapingConnector, "_fetch", staticmethod(fake_fetch))
    return fetched


def _collect():
    return ScrapingConnector().collect(CollectionRequest(company="Zomato", scraping_allowed=True))


def _http_error(code):
    resp = requests.Response()
    resp.status_code = code
    return requests.HTTPError(f"{code}", response=resp)


def test_hackernews_config_waits_at_least_30_seconds():
    cfg = yaml.safe_load((ROOT / "config/plugins/scraping_sites.yaml").read_text(encoding="utf-8"))
    assert cfg["hackernews"]["min_delay_seconds"] >= 30


def test_robots_crawl_delay_wins_when_larger(monkeypatch, sleeps):
    _setup(monkeypatch, "User-agent: *\nCrawl-delay: 30\n", site_delay=5)
    _, attempts = _collect()
    assert attempts[0].pages_fetched >= 2
    assert sleeps and all(s == 30 for s in sleeps)
    assert attempts[0].delay_used == 30 * len(sleeps)


def test_site_delay_wins_when_larger(monkeypatch, sleeps):
    _setup(monkeypatch, "User-agent: *\nCrawl-delay: 2\n", site_delay=30)
    _collect()
    assert sleeps and all(s == 30 for s in sleeps)


def test_crawl_delay_for_our_agent(monkeypatch, sleeps):
    robots = "User-agent: social-listening-bot\nCrawl-delay: 45\n\nUser-agent: *\nCrawl-delay: 1\n"
    _setup(monkeypatch, robots, site_delay=5)
    _collect()
    assert sleeps and all(s == 45 for s in sleeps)


def test_robots_read_once_per_host(monkeypatch, sleeps):
    fetched = _setup(monkeypatch, "User-agent: *\nCrawl-delay: 30\n")
    _collect()
    assert sum(u.endswith("/robots.txt") for u in fetched) == 1


def test_disallowed_paths_are_not_fetched(monkeypatch, sleeps):
    fetched = _setup(monkeypatch, "User-agent: *\nDisallow: /item\n")
    _collect()
    assert not any("item" in u for u in fetched)


def test_robots_forbidden_means_nothing_fetched(monkeypatch, sleeps):
    fetched = _setup(monkeypatch, _http_error(403))
    _, attempts = _collect()
    assert [u for u in fetched if not u.endswith("/robots.txt")] == []
    assert attempts[0].pages_fetched == 0


def test_unreadable_robots_falls_back_to_site_delay(monkeypatch, sleeps):
    _setup(monkeypatch, _http_error(404), site_delay=30)
    _, attempts = _collect()
    assert attempts[0].pages_fetched >= 2
    assert sleeps and all(s == 30 for s in sleeps)
