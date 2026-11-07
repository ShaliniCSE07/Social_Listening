"""Tests for Scraping plugin stub."""
import pytest
from src.collection.base import CollectionRequest
from src.collection.plugins.scraping.connector import ScrapingConnector
from src.collection.registry import get_connector
from src.contracts.enums import Method, Platform


def test_scraping_stub_registered():
    conn_cls = get_connector("scraping")
    assert conn_cls is ScrapingConnector


def test_scraping_stub_attributes():
    conn = ScrapingConnector()
    assert conn.method == Method.scraping
    assert conn.name == "scraping"
    assert Platform.other in conn.platforms
    assert conn.estimate_cost(CollectionRequest(company="Zomato")) == 0.0


def test_scraping_stub_can_run():
    conn = ScrapingConnector()
    can_run, reason = conn.can_run(CollectionRequest(company="Zomato"))
    assert can_run is False
    assert "not implemented" in reason.lower()


def test_scraping_stub_collect_raises():
    conn = ScrapingConnector()
    with pytest.raises(NotImplementedError):
        conn.collect(CollectionRequest(company="Zomato"))

