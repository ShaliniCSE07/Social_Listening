# Handoff Contract Specification: Collection to Processing

This document outlines the data interchange format produced by the **Collection** module (Member 1) and consumed by the **Processing and Storage** modules (Member 2).

All outputs are written as line-delimited JSON (`.jsonl`) files where each row represents a validated JSON object conforming to strict Pydantic v2 schemas.

---

## 1. Mentions Output (`mentions.jsonl`)

Each line represents an individual collected mention (`RawMention` schema).

| Field Name | Type | Required / Nullable | Description |
| :--- | :--- | :--- | :--- |
| `schema_version` | `string` | Required | Schema version identifier (e.g. `"1.0"`). |
| `company` | `string` | Required | Target company name. Non-empty string. |
| `run_id` | `string` | Nullable | Unique identifier of the pipeline run. |
| `platform` | `string` | Required | Standardized platform enum: `twitter_x`, `instagram`, `linkedin`, `reddit`, `google`, `facebook`, `news_blog`, `other`. |
| `item_id` | `string` | Nullable | Platform-native unique item ID (e.g. tweet ID, post ID). May be `null` if unavailable. |
| `url` | `string` | Nullable | Canonical web URL of the item or post. |
| `branch` | `string` | Nullable | Physical branch / store location for local reviews (e.g. Google Places). |
| `content_type_hint` | `string` | Nullable | Content category hint: `post`, `comment`, `reply`, `review`, `article`. |
| `raw_payload` | `object` | Required | Raw payload as returned by the platform / data source. |
| `source` | `string` | Required | Specific source label (e.g. `"reddit_api"`, `"google_places_api"`). |
| `method_used` | `string` | Required | Method used: `api`, `dataset`, or `scraping`. |
| `tool_used` | `string` | Required | Specific tool or client used for collection. |
| `fallback_from` | `string` | Nullable | Previous `Method` that failed or was rate-limited before falling back. |
| `cost_usd` | `float` | Required | Estimated cost in USD incurred to fetch this item ($\ge 0.0$, default `0.0`). |
| `collected_at` | `string` | Required | ISO 8601 UTC timestamp (e.g. `"2026-11-07T08:00:00Z"`). Timezone-aware UTC strictly enforced. |

---

## 2. Attempts Output (`attempts.jsonl`)

Each line logs an execution attempt by a collection plugin connector (`CollectionAttempt` schema).

| Field Name | Type | Required / Nullable | Description |
| :--- | :--- | :--- | :--- |
| `company` | `string` | Required | Target company name. |
| `platform` | `string` | Required | Platform queried (`Platform` enum). |
| `method` | `string` | Required | Method attempted: `api`, `dataset`, or `scraping`. |
| `status` | `string` | Required | Execution status: `success`, `failed`, `rate_limited`, `empty`, `skipped`, `budget_exhausted`. |
| `reason` | `string` | Nullable | Diagnostic reason or error description. |
| `item_count` | `integer` | Required | Count of mentions collected during this attempt ($\ge 0$). |
| `cost_usd` | `float` | Required | Total cost in USD incurred for this collection attempt ($\ge 0.0$). |
| `started_at` | `string` | Required | ISO 8601 UTC timestamp of execution start. |
| `finished_at` | `string` | Required | ISO 8601 UTC timestamp of execution finish. |
| `scraping_checks` | `object` | Nullable | Boolean evaluation map for scraping safety gate (e.g. `{"scraping_allowed": bool, "robots_txt_ok": bool, "min_results_needed": bool}`). |

---

## 3. Serialization & Helper Functions
Defined in `src/contracts/io.py`:
- `write_mentions_jsonl(path, mentions)`
- `read_mentions_jsonl(path) -> dict[str, list[RawMention]]` (grouped by `company`, includes line numbers on validation errors)
- `write_attempts_jsonl(path, attempts)`
- `read_attempts_jsonl(path) -> list[CollectionAttempt]` (flat list, includes line numbers on validation errors)

