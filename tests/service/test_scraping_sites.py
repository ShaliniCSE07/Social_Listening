"""Tests for GET /api/config/scraping-sites."""
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.service.main import app


@pytest.fixture()
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _patch_yaml(tmp_path: Path, content: str):
    """Write a temporary scraping_sites.yaml and patch load_plugin_config to use it."""
    import yaml
    from config.settings import load_yaml

    site_file = tmp_path / "scraping_sites.yaml"
    site_file.write_text(textwrap.dedent(content), encoding="utf-8")
    parsed = load_yaml(site_file)

    # Patch only the call that uses the "scraping_sites" key
    original_load = __import__(
        "config.settings", fromlist=["load_plugin_config"]
    ).load_plugin_config

    def patched_load(name: str):
        if name == "scraping_sites":
            return parsed
        return original_load(name)

    return patch("src.service.routes.config.load_plugin_config", side_effect=patched_load)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_scraping_sites_lists_hackernews_with_right_fields(client, monkeypatch):
    """The endpoint returns the hackernews entry with all required fields."""
    monkeypatch.setenv("SCRAPER_CONTACT", "bot@example.com")

    resp = client.get("/api/config/scraping-sites")
    assert resp.status_code == 200
    items = resp.json()
    assert isinstance(items, list)

    hn = next((s for s in items if s["key"] == "hackernews"), None)
    assert hn is not None, "hackernews site not found in response"

    # Required fields present
    assert hn["key"] == "hackernews"
    assert hn["name"] == "Hacker News"
    assert hn["platform"] == "news_blog"
    assert isinstance(hn["allows_scraping"], bool)
    assert isinstance(hn["can_run"], bool)
    assert "reason" in hn

    # start_urls, policy details must NOT appear
    assert "start_urls" not in hn
    assert "policy_evidence" not in hn
    assert "allowed_path_prefixes" not in hn
    assert "max_pages" not in hn
    assert "min_delay_seconds" not in hn
    assert "parser" not in hn


def test_scraping_sites_can_run_false_when_contact_missing(client, monkeypatch, tmp_path):
    """can_run is False and reason names the missing env var when SCRAPER_CONTACT is unset."""
    monkeypatch.delenv("SCRAPER_CONTACT", raising=False)

    resp = client.get("/api/config/scraping-sites")
    assert resp.status_code == 200
    items = resp.json()

    # hackernews has allows_scraping=true; without SCRAPER_CONTACT it cannot run
    hn = next((s for s in items if s["key"] == "hackernews"), None)
    assert hn is not None
    assert hn["allows_scraping"] is True
    assert hn["can_run"] is False
    assert "SCRAPER_CONTACT" in hn["reason"]


def test_scraping_sites_can_run_true_when_contact_set(client, monkeypatch):
    """can_run is True for a site with allows_scraping=true when SCRAPER_CONTACT is set."""
    monkeypatch.setenv("SCRAPER_CONTACT", "bot@example.com")

    resp = client.get("/api/config/scraping-sites")
    assert resp.status_code == 200
    items = resp.json()

    hn = next((s for s in items if s["key"] == "hackernews"), None)
    assert hn is not None
    assert hn["allows_scraping"] is True
    assert hn["can_run"] is True
    assert hn["reason"] == ""


def test_scraping_sites_empty_list_when_no_sites(client, tmp_path):
    """An empty (or missing) scraping_sites.yaml returns an empty list."""
    from config.settings import load_plugin_config as _orig

    def patched_load(name: str):
        if name == "scraping_sites":
            return {}
        return _orig(name)

    with patch("src.service.routes.config.load_plugin_config", side_effect=patched_load):
        resp = client.get("/api/config/scraping-sites")

    assert resp.status_code == 200
    assert resp.json() == []


def test_scraping_sites_no_secret_value_in_response(client, monkeypatch):
    """The actual value of SCRAPER_CONTACT never appears in the response body."""
    secret = "super_secret_bot_contact_xyz_99999"
    monkeypatch.setenv("SCRAPER_CONTACT", secret)

    resp = client.get("/api/config/scraping-sites")
    assert resp.status_code == 200
    assert secret not in resp.text

