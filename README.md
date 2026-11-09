# Social Listening System

A modular social media listening and sentiment analytics platform built in Python 3.11+.

## Architecture & Layout

```
.
├── config/                  # Configuration files and settings loader
│   ├── plugins/             # Per-plugin configuration files
│   │   ├── api.yaml
│   │   ├── dataset.yaml
│   │   ├── scraping.yaml
│   │   └── source_policy.yaml # Data-driven source candidates and scraping policy
│   ├── config.yaml          # Global pipeline settings
│   ├── companies.yaml       # Monitored companies & targeting definitions
│   └── settings.py          # Unified settings loader with environment overrides
├── src/
│   ├── contracts/           # Shared domain models, enums, schemas & serialization
│   │   ├── enums.py         # Standard Platform, Method, ContentType, AttemptStatus
│   │   ├── schemas.py       # Pydantic v2 domain schemas (RawMention, CollectionAttempt)
│   │   └── io.py            # Line-delimited JSON (JSONL) writers and readers
│   ├── collection/          # Collection layer (Member 1)
│   │   ├── common/          # Shared HTTP session and text utilities
│   │   ├── plugins/         # Auto-discovered collection plugins
│   │   │   ├── api/         # Direct API connectors (Reddit, Google Places, etc.)
│   │   │   ├── dataset/     # Offline/historical dataset connectors
│   │   │   └── scraping/    # Web scraping connectors (governed by safety gate)
│   │   ├── base.py          # BaseConnector and CollectionRequest interfaces
│   │   ├── planner.py       # Input normalization & collection request planner
│   │   ├── policy.py        # Data-driven source selection policy loader
│   │   ├── registry.py      # Dynamic plugin discovery registry
│   │   ├── agent.py         # Task candidate evaluation, ranking & decision engine
│   │   ├── executor.py      # Fallback chain executor and collection pipeline runner
│   │   ├── budget.py        # Shared budget manager (placeholder)
│   │   └── fallback.py      # Dynamic fallback handler (placeholder)
│   ├── processing/          # Normalization, cleaning & validation (Member 2)
│   ├── storage/             # Raw, processed, and checkpoint stores (Member 2)
│   ├── reporting/           # Report generation and analytics (Member 2)
│   └── pipeline.py          # End-to-end orchestration pipeline (Member 2)
├── tests/                   # Comprehensive unit and integration test suite
├── data/                    # Storage roots (mock, raw, processed, checkpoints, output)
└── docs/                    # Architecture and handoff specifications
```

## Running the API Service

Start the FastAPI service:

```bash
uvicorn src.service.main:app --reload --port 8000
```

## Running Tests

Install required dependencies:

```bash
pip install -r requirements.txt
```

Run test suite:

```bash
python -m pytest -v
```

By default, tests marked with `@pytest.mark.live` (requiring active internet/network) are skipped.

## Collection Planner CLI

Generate collection requests and execution tasks from JSON or YAML target definitions:

```bash
python -m src.collection.planner --input targets.json
```

## Collection Agent & Source Policy CLI

Evaluate eligible collection methods and explain candidate ranking per task:

```bash
python -m src.collection.agent --input targets.json --explain
```

## Collection Pipeline Executor CLI

Execute collection tasks with fallback chains, scraping safety gates, and budget tracking:

```bash
python -m src.collection.executor --input targets.json --out data/output
```

## Frontend

The frontend is a Next.js (App Router) application with TypeScript and Tailwind CSS.

### Setup

```bash
cd frontend
npm install
cp .env.example .env.local   # default: NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

### Development

Start the backend first, then the frontend:

```bash
# Terminal 1 – backend
uvicorn src.service.main:app --reload --port 8000

# Terminal 2 – frontend
cd frontend
npm run dev
```

The frontend runs at http://localhost:3000.

### Lint, Build & Test

```bash
cd frontend
npm run lint
npm run build
npm test
```

### Page Map & Features

- **`/` — Dashboard**: Stat cards (total runs, total mentions, spend, completion rate computed from runs), recent runs preview, source connector readiness, and quick launch button.
- **`/runs/new` — New Run Wizard**: 4-step workflow (Companies with bulk-paste support, Live API & Dataset catalog selection with select-all tabs, Budget and date window options, Review & Launch) with live sticky summary.
- **`/runs` — Collection Runs**: Filterable and searchable table by company or run ID, sortable columns, status badges with icons, exact timestamps in tooltips, and pagination.
- **`/runs/[id]` — Run Details**: Header with live polling indicator, duration, copy run ID, and direct `.jsonl` download actions. Tabs for Overview (budget progress bar & platform spend), Mentions (searchable table with side-drawer inspector & JSON export), Attempts (timeline grouped by company), and Downloads.
- **`/sources` — Source Integrations**: Overview of active API platforms, authentication state, and offline dataset catalogs without exposing secrets.
- **App Shell**: Collapsible left sidebar, top bar with real-time backend health check (`/health` rechecked every 30s) and light/dark theme toggle (persisted in `localStorage`).

### Capturing Screenshots

1. Ensure the backend is running on `http://localhost:8000`:
   ```bash
   uvicorn src.service.main:app --reload --port 8000
   ```
2. Start the Next.js development server:
   ```bash
   cd frontend && npm run dev
   ```
3. Open `http://localhost:3000` in your browser. Use browser devtools (e.g., Device Toolbar or standard viewport capture) to take desktop and mobile screenshots across `/`, `/runs/new`, `/runs`, `/runs/[id]`, and `/sources`.


