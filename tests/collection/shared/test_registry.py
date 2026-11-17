"""Tests for registry auto-discovery."""
import sys
from pathlib import Path

from src.collection.base import BaseConnector, CollectionRequest
from src.collection.registry import get_all_connectors, get_connector, get_connectors
from src.contracts.enums import Method, Platform


def test_registry_finds_all_connectors():
    connectors = get_all_connectors()
    names = {c.name for c in connectors}
    assert names == {"reddit_api", "google_places", "dataset", "scraping"}
    assert len(connectors) == 4


def test_registry_filter_by_method():
    api_connectors = get_connectors(Method.api)
    assert len(api_connectors) == 2
    api_names = {c.name for c in api_connectors}
    assert api_names == {"reddit_api", "google_places"}

    dataset_connectors = get_connectors(Method.dataset)
    assert len(dataset_connectors) == 1
    assert dataset_connectors[0].name == "dataset"

    scraping_connectors = get_connectors(Method.scraping)
    assert len(scraping_connectors) == 1
    assert scraping_connectors[0].name == "scraping"


def test_registry_get_connector_by_name():
    reddit_conn = get_connector("reddit_api")
    assert reddit_conn is not None
    assert reddit_conn.name == "reddit_api"
    assert reddit_conn.method == Method.api

    google_conn = get_connector("google_places")
    assert google_conn is not None
    assert google_conn.name == "google_places"
    assert google_conn.method == Method.api

    assert get_connector("nonexistent") is None


def test_dummy_plugin_discovered_in_temp_dir(tmp_path):
    # Create a dynamic plugin package under tmp_path
    plugin_dir = tmp_path / "dummy_plugin"
    plugin_dir.mkdir(parents=True)

    init_file = plugin_dir / "__init__.py"
    init_content = """from src.collection.base import BaseConnector, CollectionRequest
from src.contracts.enums import Method, Platform

class DummyConnector(BaseConnector):
    method = Method.api
    name = "dummy"
    platforms = [Platform.other]

    def can_run(self, request: CollectionRequest):
        return True, "OK"

    def estimate_cost(self, request: CollectionRequest):
        return 0.0

    def collect(self, request: CollectionRequest):
        raise NotImplementedError()

CONNECTORS = [DummyConnector]
"""
    init_file.write_text(init_content, encoding="utf-8")

    # Add tmp_path to sys.path so pkgutil can import modules dynamically
    sys.path.insert(0, str(tmp_path))
    try:
        connectors = get_all_connectors(plugins_path=[str(tmp_path)], prefix="")
        names = {c.name for c in connectors}
        assert "dummy" in names
    finally:
        if str(tmp_path) in sys.path:
            sys.path.remove(str(tmp_path))
