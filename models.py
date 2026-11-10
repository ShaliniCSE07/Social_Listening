from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, ConfigDict


class Platform(str, Enum):
    TWITTER_X = "twitter_x"
    INSTAGRAM = "instagram"
    LINKEDIN = "linkedin"
    REDDIT = "reddit"
    GOOGLE = "google"
    FACEBOOK = "facebook"
    NEWS_BLOG = "news_blog"
    OTHER = "other"


class Method(str, Enum):
    API = "api"
    RSS = "rss"
    DATASET = "dataset"
    SCRAPING = "scraping"


class AttemptStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    RATE_LIMITED = "rate_limited"
    EMPTY = "empty"
    SKIPPED = "skipped"
    BUDGET_EXHAUSTED = "budget_exhausted"


class ContentTypeHint(str, Enum):
    POST = "post"
    COMMENT = "comment"
    REPLY = "reply"
    REVIEW = "review"
    ARTICLE = "article"


class RawMention(BaseModel):
    """Member 1 -> Member 2 handoff model, extra=forbid"""
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    company: str
    run_id: str | None = None
    platform: Platform
    item_id: str | None = None
    url: str | None = None
    branch: str | None = None
    content_type_hint: ContentTypeHint | None = None
    raw_payload: dict[str, Any]
    source: str
    method_used: Method
    tool_used: str
    fallback_from: Method | None = None
    cost_usd: float = Field(default=0.0, ge=0)
    collected_at: datetime

    @field_validator("collected_at")
    @classmethod
    def must_be_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("collected_at must be timezone-aware UTC")
        return v


class CollectionAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: str
    platform: Platform
    method: Method
    status: AttemptStatus
    reason: str | None = None
    item_count: int = Field(ge=0)
    cost_usd: float = Field(ge=0)
    started_at: datetime
    finished_at: datetime
    scraping_checks: dict[str, bool] | None = None


class SoclRecord(BaseModel):
    """PRD 8.6 socl.record.v1 standard output record"""
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "socl.record.v1"
    record_id: str
    mention_id: str
    company: str
    company_id: str
    industry: str | None = None
    platform: Platform
    content_type: str
    mention_type: str
    branch: str | None = None
    text: str
    url: str | None = None
    author: str | None = None
    posted_at: datetime | None = None
    reactions: dict[str, int | None]
    rating: float | None = None
    language: str | None = None
    place: str | None = None
    origin_type: str = "public"
    source: str
    method_used: Method
    tool_used: str
    fallback_from: Method | None = None
    cost_usd: float = 0.0
    collected_at: datetime
    run_id: str
    load_type: str  # "full" | "delta"
    is_update: bool = False
    fingerprint: str = ""
    version: int = 1
    supersedes: str | None = None
    incomplete: list[str] = Field(default_factory=list)
    company_match: str = "confirmed"