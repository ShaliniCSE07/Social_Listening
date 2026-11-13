"""Tests for Scraping plugin – registration, attributes, can_run."""
import os

import pytest
from src.collection.base import CollectionRequest
from src.collection.plugins.scraping.connector import ScrapingConnector, _reset_sites_cfg
from src.collection.registry import get_connector
from src.contracts.enums import Method, Platform


# ------------------------------------------------------------------ #
# Registration & class attributes (unchanged intent)
# ------------------------------------------------------------------ #
def test_scraping_connector_registered():
    conn_cls = get_connector("scraping")
    assert conn_cls is ScrapingConnector


def test_scraping_connector_attributes():
    conn = ScrapingConnector()
    assert conn.method == Method.scraping
    assert conn.name == "scraping"
    assert Platform.other in conn.platforms
    assert conn.estimate_cost(CollectionRequest(company="Zomato")) == 0.0


# ------------------------------------------------------------------ #
# can_run – SCRAPER_CONTACT missing
# ------------------------------------------------------------------ #
def test_can_run_missing_contact(monkeypatch):
    monkeypatch.delenv("SCRAPER_CONTACT", raising=False)
    conn = ScrapingConnector()
    ok, reason = conn.can_run(CollectionRequest(company="Zomato", scraping_allowed=True))
    assert ok is False
    assert "SCRAPER_CONTACT" in reason


# ------------------------------------------------------------------ #
# can_run – scraping_allowed=False on request
# ------------------------------------------------------------------ #
def test_can_run_scraping_not_allowed(monkeypatch):
    monkeypatch.setenv("SCRAPER_CONTACT", "test@example.com")
    conn = ScrapingConnector()
    ok, reason = conn.can_run(CollectionRequest(company="Zomato", scraping_allowed=False))
    assert ok is False
    assert "scraping_allowed" in reason.lower()


# ------------------------------------------------------------------ #
# can_run – no site has allows_scraping=true
# ------------------------------------------------------------------ #
def test_can_run_no_enabled_sites(monkeypatch):
    monkeypatch.setenv("SCRAPER_CONTACT", "test@example.com")
    _reset_sites_cfg()
    import src.collection.plugins.scraping.connector as mod
    monkeypatch.setattr(mod, "_sites_cfg", {"blocked": {"allows_scraping": False}})
    conn = ScrapingConnector()
    ok, reason = conn.can_run(CollectionRequest(company="Zomato", scraping_allowed=True))
    assert ok is False
    assert "no site" in reason.lower()
    _reset_sites_cfg()


# ------------------------------------------------------------------ #
# can_run – happy path
# ------------------------------------------------------------------ #
def test_can_run_happy(monkeypatch):
    monkeypatch.setenv("SCRAPER_CONTACT", "test@example.com")
    conn = ScrapingConnector()
    ok, reason = conn.can_run(CollectionRequest(company="Zomato", scraping_allowed=True))
    assert ok is True
    assert reason == "ready"
