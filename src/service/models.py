"""Pydantic models for the FastAPI service."""
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, field_validator


class HealthResponse(BaseModel):
    status: str = "ok"


class SourceConfigItem(BaseModel):
    name: str
    method: str
    platforms: List[str]
    enabled: bool
    can_run: bool
    reason: str


class DatasetConfigItem(BaseModel):
    key: str
    name: str
    source_type: str
    enabled: bool
    last_updated: Optional[str] = None
    license_note: Optional[str] = None


class CompanyInput(BaseModel):
    name: str
    alt_spellings: Optional[List[str]] = Field(default_factory=list)
    handles: List[str] = Field(default_factory=list)
    branches: Optional[List[str]] = Field(default_factory=list)
    industry: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Company name is required and cannot be empty")
        return v.strip()


class SourcesInput(BaseModel):
    api: Optional[List[str]] = None
    dataset_keys: Optional[List[str]] = None


class CreateRunRequest(BaseModel):
    companies: List[CompanyInput]
    sources: Optional[SourcesInput] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    budget_usd: Optional[float] = None
    run_id: Optional[str] = None
    max_age_days: Optional[float] = None
    require_fresh: Optional[bool] = None
    refresh: Optional[bool] = None

    @field_validator("companies")
    @classmethod
    def validate_companies(cls, v: List[CompanyInput]) -> List[CompanyInput]:
        if not v:
            raise ValueError("At least one company must be specified")
        return v


class CreateRunResponse(BaseModel):
    run_id: str
    status: str = "queued"


class RunTotals(BaseModel):
    mentions_count: int = 0
    attempts_count: int = 0
    cost_usd: float = 0.0


class RunListItem(BaseModel):
    id: str
    status: str
    created_at: str
    companies: List[str]
    totals: RunTotals


class RunDetailResponse(BaseModel):
    id: str
    status: str
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None
    companies: List[str]
    progress: Dict[str, Any] = Field(default_factory=dict)
    counts: RunTotals
    budget_snapshot: Dict[str, Any] = Field(default_factory=dict)
    per_source_results: Dict[str, Any] = Field(default_factory=dict)


class CompactMention(BaseModel):
    platform: str
    source: str
    date: Optional[str] = None
    short_text: Optional[str] = None
    url: Optional[str] = None
    method: str
    cost: float = 0.0


class PaginatedMentionsResponse(BaseModel):
    items: List[Union[CompactMention, Dict[str, Any]]]
    total: int
    page: int
    page_size: int
    pages: int

