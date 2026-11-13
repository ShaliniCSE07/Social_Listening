from datetime import datetime, timezone
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.contracts.enums import AttemptStatus, ContentType, Method, Platform


class RawMention(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    company: str = Field(..., min_length=1)
    run_id: Optional[str] = None
    platform: Platform
    item_id: Optional[str] = None
    url: Optional[str] = None
    branch: Optional[str] = None
    content_type_hint: Optional[ContentType] = None
    raw_payload: Dict[str, Any]
    source: str
    method_used: Method
    tool_used: str
    fallback_from: Optional[Method] = None
    cost_usd: float = Field(default=0.0, ge=0.0)
    collected_at: datetime

    @field_validator("collected_at")
    @classmethod
    def validate_collected_at(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("collected_at must be timezone-aware")
        if v.tzinfo != timezone.utc and v.utcoffset() != timezone.utc.utcoffset(v):
            raise ValueError("collected_at must be in UTC timezone")
        return v


class CollectionAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: str = Field(..., min_length=1)
    platform: Platform
    method: Method
    status: AttemptStatus
    reason: Optional[str] = None
    item_count: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0.0)
    started_at: datetime
    finished_at: datetime
    scraping_checks: Optional[Dict[str, bool]] = None
    pages_fetched: int = Field(default=0, ge=0)
    pages_from_cache: int = Field(default=0, ge=0)
    delay_used: float = Field(default=0.0, ge=0.0)

    @field_validator("started_at", "finished_at")
    @classmethod
    def validate_timestamps(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("timestamps must be timezone-aware")
        if v.tzinfo != timezone.utc and v.utcoffset() != timezone.utc.utcoffset(v):
            raise ValueError("timestamps must be in UTC timezone")
        return v

