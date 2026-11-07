from typing import ClassVar, List, Tuple
from src.collection.base import BaseConnector, CollectionRequest
from src.contracts.enums import Method, Platform
from src.contracts.schemas import CollectionAttempt, RawMention


class ScrapingConnector(BaseConnector):
    """Scraping Collection Plugin stub.

    Future connectors:
    - TODO: three-condition gate validation (scraping_allowed, robots.txt, min_results)
    - TODO: HTML scrapers and parser modules
    """

    method: ClassVar[Method] = Method.scraping
    name: ClassVar[str] = "scraping"
    platforms: ClassVar[List[Platform]] = [Platform.other]

    def can_run(self, request: CollectionRequest) -> Tuple[bool, str]:
        return False, "Scraping collection not implemented yet"

    def estimate_cost(self, request: CollectionRequest) -> float:
        return 0.0

    def collect(self, request: CollectionRequest) -> Tuple[List[RawMention], CollectionAttempt]:
        raise NotImplementedError("Scraping collection plugin is a stub")

