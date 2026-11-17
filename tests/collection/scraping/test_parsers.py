"""Tests for the scraping parsers."""

import os
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from src.collection.plugins.scraping.parsers import get_parser

FIXTURES_DIR = Path(__file__).parents[2] / "fixtures" / "scraping"

def load_fixture(name: str) -> str:
    return (FIXTURES_DIR / f"{name}.html").read_text(encoding="utf-8")

def test_hackernews_listing_parser():
    html = load_fixture("listing")
    parser = get_parser("hackernews")
    items = parser.parse(html, "https://news.ycombinator.com/news")
    assert len(items) == 1
    item = items[0]
    assert item["item_id"] == "123456"
    assert item["title"] == "Test Story Title"
    assert item["link"] == "https://example.com/article"
    assert item["points"] == 42
    assert item["author"] == "testauthor"
    assert "hours ago" in item["age"]
    assert item["comment_count"] == 42
    assert item["permalink"].endswith("/item?id=123456")

def test_hackernews_item_parser():
    html = load_fixture("item")
    parser = get_parser("hackernews")
    items = parser.parse(html, "https://news.ycombinator.com/item?id=123456")
    # Expect first dict is the story, then two comments
    assert len(items) == 3
    story, comment1, comment2 = items
    # Story fields
    assert story["item_id"] == "123456"
    assert story["title"] == "Test Story Title"
    assert story["link"] == "https://example.com/article"
    assert story["points"] == 42
    assert story["author"] == "testauthor"
    assert "hours ago" in story["age"]
    # Comment 1
    assert comment1["item_id"] == "cmt1"
    assert comment1["author"] == "commenter1"
    assert comment1["text"] == "First comment text"
    assert comment1["parent"] == "123456"
    assert comment1["indentation"] == 0
    # Comment 2 (reply to comment1)
    assert comment2["item_id"] == "cmt2"
    assert comment2["author"] == "commenter2"
    assert comment2["text"] == "Second comment text"
    assert comment2["parent"] == "cmt1"
    assert comment2["indentation"] == 1

def test_unknown_parser_name():
    with pytest.raises(ValueError) as exc:
        get_parser("nonexistent")
    assert "Unknown parser name" in str(exc.value)

