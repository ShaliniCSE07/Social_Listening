"""Stand-alone review scraper: any URL in, ``mentions.jsonl`` out.

Separate from collection runs. See ``engine.scrape_reviews``.
"""
from src.review_scraper.engine import ScrapeResult, scrape_reviews

__all__ = ["ScrapeResult", "scrape_reviews"]
