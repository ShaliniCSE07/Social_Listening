"""Base parser interface for scraping plugin.

Implementations must subclass :class:`Parser` and implement ``parse`` which receives the raw
HTML string and the page URL, returning a list of dictionaries representing extracted items.
"""

from abc import ABC, abstractmethod
from typing import List, Dict


class Parser(ABC):
    """Abstract base class for all site parsers."""

    @abstractmethod
    def parse(self, html: str, page_url: str) -> List[Dict]:
        """Parse *html* from *page_url* and return a list of item dicts.

        Each dict should contain the fields required by the scraper connector (e.g.
        ``item_id``, ``author``, ``text``, ``age``, ``parent``, ``indentation``,
        ``permalink`` for comments, and story‑level fields for listings).
        """
        raise NotImplementedError

