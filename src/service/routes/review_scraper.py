"""Stand-alone review scraper endpoints: URL in, mentions.jsonl out.

Each scrape is saved under data/review_scrapes/<job_id>/ as mentions.jsonl
(the same RawMention format as collection runs) plus a small job.json with
the summary. No attempts.jsonl is produced.
"""
import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from src.contracts.io import write_mentions_jsonl
from src.review_scraper.browser import browser_available
from src.review_scraper.engine import MAX_PAGES_LIMIT, MAX_REVIEWS_LIMIT, scrape_reviews

router = APIRouter(prefix="/api/review-scraper", tags=["review-scraper"])

SCRAPES_DIR = Path("data/review_scrapes")
_JOB_ID_RE = re.compile(r"^scrape_[0-9a-f]{8}$")


class ScrapeRequest(BaseModel):
    url: str = Field(..., min_length=8, max_length=2048)
    company: Optional[str] = Field(None, max_length=200)
    max_pages: int = Field(3, ge=1, le=MAX_PAGES_LIMIT)
    max_reviews: int = Field(200, ge=1, le=MAX_REVIEWS_LIMIT)
    # auto: page HTML first, browser only if no reviews; static: HTML only; browser: always render JS
    mode: Literal["auto", "static", "browser"] = "auto"


class ScrapedReview(BaseModel):
    text: str
    title: Optional[str] = None
    rating: Optional[float] = None
    recommended: Optional[bool] = None
    author: Optional[str] = None
    date: Optional[str] = None
    url: Optional[str] = None
    extraction_method: str


class ScrapeJob(BaseModel):
    job_id: str
    status: str  # completed | empty | failed
    url: str
    company: str
    created_at: str
    reviews_count: int
    pages_fetched: int
    methods: Dict[str, int] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    error: Optional[str] = None
    download_url: str
    mode_requested: str = "auto"
    mode_used: str = "static"
    reviews: Optional[List[ScrapedReview]] = None


class ScraperCapabilities(BaseModel):
    browser_available: bool
    browser_reason: str


def _job_dir(job_id: str) -> Path:
    if not _JOB_ID_RE.match(job_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scrape not found")
    return SCRAPES_DIR / job_id


def _load_job(job_id: str) -> Dict[str, Any]:
    path = _job_dir(job_id) / "job.json"
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scrape not found")
    return json.loads(path.read_text(encoding="utf-8"))


def _load_reviews(job_id: str) -> List[Dict[str, Any]]:
    path = _job_dir(job_id) / "mentions.jsonl"
    out: List[Dict[str, Any]] = []
    if path.is_file():
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    m = json.loads(line)
                    p = m.get("raw_payload") or {}
                    out.append({
                        "text": p.get("text") or "",
                        "title": p.get("title"),
                        "rating": p.get("rating"),
                        "recommended": p.get("recommended"),
                        "author": p.get("author"),
                        "date": p.get("date"),
                        "url": m.get("url"),
                        "extraction_method": p.get("extraction_method") or "unknown",
                    })
    return out


@router.post("", response_model=ScrapeJob)
def create_scrape(request: ScrapeRequest) -> ScrapeJob:
    """Scrape reviews from one URL and save them as mentions.jsonl."""
    job_id = "scrape_" + secrets.token_hex(4)
    result = scrape_reviews(
        request.url,
        company=request.company,
        max_pages=request.max_pages,
        max_reviews=request.max_reviews,
        run_id=job_id,
        mode=request.mode,
    )
    job_dir = SCRAPES_DIR / job_id
    write_mentions_jsonl(job_dir / "mentions.jsonl", result.mentions)

    job = {
        "job_id": job_id,
        "status": "failed" if result.error else ("completed" if result.mentions else "empty"),
        "url": request.url,
        "company": result.company or "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "reviews_count": len(result.mentions),
        "pages_fetched": result.pages_fetched,
        "methods": result.methods,
        "warnings": result.warnings,
        "error": result.error,
        "download_url": f"/api/review-scraper/{job_id}/download",
        "mode_requested": request.mode,
        "mode_used": result.mode_used,
    }
    (job_dir / "job.json").write_text(json.dumps(job, indent=2), encoding="utf-8")
    return ScrapeJob(**job, reviews=_load_reviews(job_id))


@router.get("", response_model=List[ScrapeJob])
def list_scrapes(limit: int = 20) -> List[ScrapeJob]:
    """Most recent scrapes first (without review lists)."""
    jobs = []
    if SCRAPES_DIR.exists():
        for path in SCRAPES_DIR.glob("scrape_*/job.json"):
            try:
                jobs.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
    jobs.sort(key=lambda j: j.get("created_at", ""), reverse=True)
    return [ScrapeJob(**j) for j in jobs[: max(1, min(limit, 100))]]


@router.get("/capabilities", response_model=ScraperCapabilities)
def scraper_capabilities() -> ScraperCapabilities:
    """Whether browser mode (JavaScript rendering) is installed on this server."""
    ok, reason = browser_available()
    return ScraperCapabilities(browser_available=ok, browser_reason=reason)


@router.get("/{job_id}", response_model=ScrapeJob)
def get_scrape(job_id: str) -> ScrapeJob:
    return ScrapeJob(**_load_job(job_id), reviews=_load_reviews(job_id))


@router.get("/{job_id}/download")
def download_scrape(job_id: str) -> FileResponse:
    """Download the scrape's mentions.jsonl."""
    _load_job(job_id)
    path = _job_dir(job_id) / "mentions.jsonl"
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="mentions.jsonl not found")
    return FileResponse(path, media_type="application/x-ndjson", filename=f"{job_id}_mentions.jsonl")
