"""Dataset source abstract interface."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterator, Optional


@dataclass
class DatasetInfo:
    """Metadata describing a dataset source."""
    name: str
    source_type: str
    last_updated: datetime
    row_count: Optional[int] = None
    license: Optional[str] = None


class DatasetSource(ABC):
    """Abstract base class for dataset readers/sources."""

    @abstractmethod
    def describe(self) -> DatasetInfo:
        """Return metadata regarding the dataset source."""
        pass

    @abstractmethod
    def iter_rows(self) -> Iterator[Dict[str, Any]]:
        """Stream dataset rows as dictionaries without loading entire file into memory."""
        pass

