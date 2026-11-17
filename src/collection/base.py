from abc import ABC, abstractmethod
from datetime import datetime
from typing import ClassVar, List, Optional, Tuple
from pydantic import BaseModel, ConfigDict, Field

from src.contracts.enums import Method, Platform
from src.contracts.schemas import CollectionAttempt, RawMention


class CollectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: str = Field(..., min_length=1, description="Target company name")
    alt_spellings: List[str] = Field(default_factory=list, description="Alternative spellings or aliases")
    handles: List[str] = Field(default_factory=list, description="Social media handles or brand tags")
    branches: List[str] = Field(default_factory=list, description="Physical branch locations")
    platforms: List[Platform] = Field(default_factory=list, description="Target platforms to query")
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    run_id: Optional[str] = None
    industry: Optional[str] = None
    scraping_allowed: bool = False
    budget_usd: Optional[float] = None
    dataset_keys: Optional[List[str]] = None
    max_age_days: Optional[float] = None
    require_fresh: bool = False
    refresh: bool = False


class BaseConnector(ABC):
    """Abstract base class for all collection connectors."""

    method: ClassVar[Method]
    name: ClassVar[str]
    platforms: ClassVar[List[Platform]] = []

    @abstractmethod
    def can_run(self, request: CollectionRequest) -> Tuple[bool, str]:
        """Check whether connector can run for request. Returns (can_run, reason)."""
        pass

    @abstractmethod
    def estimate_cost(self, request: CollectionRequest) -> float:
        """Estimate the cost in USD for running this request."""
        pass

    @abstractmethod
    def collect(self, request: CollectionRequest) -> Tuple[List[RawMention], CollectionAttempt]:
        """Execute collection and return collected mentions and attempt record."""
        pass

