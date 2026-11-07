# Social Listening System

A modular social media listening and sentiment analytics platform built in Python 3.11+.

## Architecture & Layout

```
.
├── config/                  # Configuration files and settings loader
│   ├── plugins/             # Per-plugin configuration files
│   │   ├── api.yaml
│   │   ├── dataset.yaml
│   │   └── scraping.yaml
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
│   │   ├── registry.py      # Dynamic plugin discovery registry
│   │   ├── agent.py         # Orchestration & connector selection (placeholder)
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

