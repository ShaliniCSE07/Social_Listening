# Social Listening System

Collects what people say about companies online (reviews, posts, comments), then cleans, de-duplicates, masks personal data and stores it for analysis. One FastAPI backend serves both stages, with a Next.js dashboard for collection and a Streamlit dashboard for processing.

```
 Sources                         Collection                      Processing                      Storage
 ───────                         ──────────                      ──────────                      ───────
 APIs (Reddit, Google Places,    plan → choose method →          validate → clean → de-duplicate
 TripAdvisor via RapidAPI)  ──►  fallback chain → budget   ──►   → company match → mask PII  ──►  MongoDB
 Datasets (local, Kaggle, URL)   data/runs/<id>/                 → pseudonymize authors →        (records, runs,
 Web scraping (polite, gated)    mentions.jsonl + attempts.jsonl   version + delta checkpoints     checkpoints)
```

---

## Quick start

**Requirements:** Python 3.11+, Node.js 18.17+, and MongoDB on `localhost:27017` (only needed for processing).

```bash
# Backend
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env            # macOS/Linux: cp .env.example .env, then fill in the values

# Optional: browser mode for the Web Scraper (JavaScript-loaded pages)
set PLAYWRIGHT_BROWSERS_PATH=.playwright
python -m playwright install --only-shell chromium

# Frontend
cd frontend
npm install
copy .env.example .env.local
```

**Run** (each in its own terminal, from the project folder):

| What | Command | URL |
|---|---|---|
| Backend (collection + processing API) | `uvicorn src.service.main:app --reload --port 8000` | http://localhost:8000/docs |
| Collection dashboard | `cd frontend && npm run dev` | http://localhost:3000 |
| Processing dashboard | `streamlit run app_ui.py` | http://localhost:8501 |

### Environment variables (`.env`)

| Variable | Used for |
|---|---|
| `RAPIDAPI_KEY` | TripAdvisor reviews (one key works for every RapidAPI listing) |
| `GOOGLE_PLACES_API_KEY` | Google Places reviews |
| `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT` | Reddit search |
| `KAGGLE_USERNAME`, `KAGGLE_KEY` | Downloading Kaggle datasets |
| `SCRAPER_USER_AGENT_NAME`, `SCRAPER_CONTACT` | Identifying the scraper to websites |
| `SOCL_MONGO_URI` | MongoDB connection (default `mongodb://localhost:27017`) |
| `SOCL_AUTHOR_PEPPER` | Secret used to pseudonymize author names (required for processing) |

Frontend (`frontend/.env.local`): `NEXT_PUBLIC_API_BASE_URL` (default `http://localhost:8000`) and `NEXT_PUBLIC_PROCESSING_DASHBOARD_URL` (default `http://localhost:8501`).

A source without its keys is shown as "needs setup" on the **Sources** page and is skipped; everything else keeps working.

---

## Collection

### Sources

| Method | Source | Platform | Notes |
|---|---|---|---|
| API | Reddit | `reddit` | Posts found by Reddit search for the company |
| API | Google Places | `google` | Up to 5 reviews per place |
| API | TripAdvisor (RapidAPI) | `tripadvisor` | Reviews from the URLs in `api.tripadvisor_urls` in `companies.yaml`; 1 request per page, cached per day |
| Dataset | Local files, Kaggle, URL | from catalogue | Defined in `config/plugins/dataset_catalogue.yaml` with a column mapping (`text`, `date`, `rating`, `company`, `platform`, …) |
| Scraping | Hacker News | `news_blog` | Only as a last resort, see below |

### How a run works

1. **Plan:** companies (name, alternate spellings, handles, branches, industry) plus chosen sources, date window and budget become one task per company and platform.
2. **Choose a method:** each task ranks its candidates (API → dataset → scraping) using `source_policy.yaml`; unusable ones are rejected with a reason.
3. **Execute with fallback:** if a method fails, is rate-limited or returns too little, the next one runs. A shared budget stops paid calls once the limit is reached.
4. **Output:** `data/runs/<run_id>/mentions.jsonl` (one `RawMention` per item), `attempts.jsonl` (one `CollectionAttempt` per try) and `run_summary.json`. The formats are defined in `src/contracts/schemas.py`.

**Scraping safety gate.** Scraping runs only when the run allows it, the site allows it in `scraping_sites.yaml`, every earlier method failed or came back empty, and fewer than `min_results_threshold` items were collected. It obeys `robots.txt` and waits between pages (Hacker News: 30 seconds).

**Platform filter (optional).** On New run you can limit collection to platforms such as Instagram, Google or TripAdvisor, or free text like "play store". Sources for other platforms are skipped before they run (no API quota used), dataset rows are filtered by their platform column, and a final check drops anything else. Empty means collect from everything.

**Star rating summary.** Every run page shows the average rating and the share of reviews at each star level, overall and per platform, for any source that provides ratings.

### Configuration

| File | Contents |
|---|---|
| `config/companies.yaml` | Monitored companies: alternate spellings, handles, branches, industry, TripAdvisor URLs |
| `config/config.yaml` | Global pipeline settings |
| `config/plugins/api.yaml` | API connector settings and limits (e.g. `max_places_per_run`) |
| `config/plugins/dataset_catalogue.yaml` | Datasets and their column mappings |
| `config/plugins/scraping_sites.yaml` | Sites that may be scraped, platform mapping, delays |
| `config/plugins/source_policy.yaml` | Which methods are tried for each platform, in which order, and the scraping threshold |

### Command-line tools

```bash
python -m src.collection.planner  --input targets.json                  # show the planned tasks
python -m src.collection.agent    --input targets.json --explain        # explain method ranking
python -m src.collection.executor --input targets.json --out data/output
python -m src.collection.plugins.dataset.cli --company Zomato --dataset kaggle_zomato_playstore_2025
```

---

## Web Scraper

A separate tool (sidebar → **Web Scraper**) that takes any review page URL and returns a `mentions.jsonl` in the same format as collection runs. Results are saved in `data/review_scrapes/<scrape_id>/`.

- **Extraction:** structured review data (JSON-LD, microdata), review blocks found by their markup, and repeated review cards inside a reviews section. Stars, author, date and Recommended / Not recommended are captured when present.
- **Modes:** *Auto* reads the page HTML and switches to a headless browser (Playwright) only when no reviews are found; *Fast* uses HTML only; *Browser* always runs the page's JavaScript.
- **Rules:** respects `robots.txt` (also after redirects), fetches public addresses only, follows up to 10 "next" pages with a delay, and never bypasses logins, captchas or bot protection. Those cases are reported in plain language, and the page's overall rating is shown when review texts are hidden.
- **Works well on** pages that show reviews publicly (e.g. Sitejabber, Goodreads, Steam). Sites that block bots or require sign-in (e.g. Amazon, Zomato, TripAdvisor, Trustpilot) need an official API or data provider instead.

---

## Processing

### From collection to processing

When a run has finished, click **Send to processing** on its page (or upload the two JSONL files in the processing dashboard). The run ID stays the same in both dashboards.

| Endpoint | Purpose |
|---|---|
| `GET /api/processing/status` | Whether processing is available (MongoDB, Presidio, pepper) |
| `POST /api/runs/{id}/process` | Hand a `completed` or `partial` run to processing |
| `GET /api/runs/{id}/processing` | State: `not_started`, `queued`, `running`, `completed`, `failed` |

If processing can't start (for example MongoDB is down), collection keeps working and the run page explains why.

### Pipeline (per mention)

| Step | What happens |
|---|---|
| Validate | Strict schema check of every mention and attempt |
| Clean | Mentions without text are quarantined |
| De-duplicate | By platform item ID, then URL, then text + date |
| Company match | Name, alternate spellings, handles or dataset tag; others are dropped as wrong company |
| Mask personal data | Presidio replaces emails, phones (country code kept), names, cards, IBANs, IPs, addresses and more, using the rules for the author's country when known, otherwise the global default |
| Pseudonymize | Author handles become stable hashes (salted with `SOCL_AUTHOR_PEPPER`) |
| Label and check | Content type, mention type, missing URL or date flagged as incomplete |
| Version | A changed mention is stored as a new version that supersedes the old one |
| Save and report | Records saved to MongoDB; a run report with counts (collected, duplicates, wrong company, quarantined, incomplete, updated) |

**Delta loads.** The first load of a company and platform looks back 90 days; later loads start from the last checkpoint minus a 2-day overlap. Checkpoints move forward only for platforms whose collection succeeded.

**Masking rules** live in `masking_config.json`: a global default (strictest of GDPR and India DPDP) plus per-country overrides (e.g. India, US). They can be edited in the processing dashboard.

### Storage (MongoDB database `socl_db`)

| Collection | Contents |
|---|---|
| `records` | Processed, masked mentions with version history |
| `runs` | Run receipts with counters and report |
| `checkpoints` | Last loaded point per company and platform |

### Processing dashboard and API

The Streamlit dashboard has tabs for **Process Data** (upload JSONL), **Records Explorer**, **Run Metrics & Rerun**, **Checkpoints** and **Settings** (masking rules). It uses these routes on the same backend:

| Endpoint | Purpose |
|---|---|
| `POST /process` | Process uploaded `mentions.jsonl` + `attempts.jsonl` (optional industry mapping) |
| `GET /runs/{run_id}/records` | Stream a run's processed records |
| `POST /api/v1/runs/{run_id}/rerun` | Rerun a failed job |
| `GET` / `POST /api/v1/settings/masking` | Read or update masking rules |

---

## Collection dashboard pages

| Page | What it does |
|---|---|
| `/` Dashboard | Run totals, recent runs, source readiness |
| `/runs/new` | Four steps: companies, sources (and platform filter), options, review and launch |
| `/runs` | Searchable, sortable list of runs |
| `/runs/[id]` | Status, star rating summary, mentions, attempts, downloads, Send to processing |
| `/sources` | API keys status, datasets and scraping sites (no secrets shown) |
| `/scraper` | Web Scraper |

Main collection endpoints: `POST /api/runs`, `GET /api/runs`, `GET /api/runs/{id}`, `/mentions`, `/attempts`, `/ratings`, `/download`, `POST /api/plan`, `/api/config/*`, and `/api/review-scraper`. Full list at http://localhost:8000/docs.

---

## Project layout

```
config/                 settings, companies and per-plugin configuration
src/
  contracts/            shared schemas (RawMention, CollectionAttempt) and JSONL I/O
  collection/           planner, agent, executor, budget, platform filter
    plugins/            api/ (Reddit, Google Places, TripAdvisor), dataset/, scraping/
  review_scraper/       Web Scraper engine (fetcher, browser, extractors)
  reporting/            star rating summary
  service/              FastAPI app, run store, runner, processing gateway, routes
main.py, processor.py   processing API and pipeline
masker.py, pseudonym.py personal-data masking and author pseudonymization
checkpoint.py           delta windows and checkpoints
storage.py, models.py   MongoDB access and processing models
app_ui.py               processing dashboard (Streamlit)
frontend/               collection dashboard (Next.js, TypeScript, Tailwind)
tests/                  backend tests; frontend tests in frontend/src/__tests__
data/                   run outputs, caches and downloads (not committed)
docs/                   handoff contract and acceptance notes
```

## Tests

```bash
python -m pytest                 # backend (tests marked "live" are skipped by default)
cd frontend && npm test          # frontend
cd frontend && npm run lint && npm run build
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the branch workflow and how to add a collection plugin.
