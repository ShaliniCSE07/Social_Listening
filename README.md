# ICXBee Social Listening Module

## 1. Project Overview

The **ICXBee Social Listening Module** is designed to collect online mentions and reviews about one company or a list of companies from social media platforms, review sites, news sources, and other permitted online sources.

The module identifies the best permitted data collection method for each company and platform, collects new and updated information, processes the collected data, masks personally identifiable information (PII), and delivers standardised records to the ICXBee Text Analytics project.

The system uses a deterministic agent to plan and coordinate data collection based on platform access, collection policies, cost, budget, and previously collected data.

**Project:** ICXBee Social Listening Module  
**Module Identifier:** SOCL  
**Repository:** `icxbee-social-listening`  
**PRD Version:** 1.0  
**PRD Date:** November 2, 2026  
**Status:** Draft for stakeholder review

## 2. Problem Statement

Company-related information is distributed across multiple online platforms, and each platform provides different ways to access its data.

Collecting this information manually creates several challenges:

- Data is available in different formats across platforms.
- No single collection method works for every platform.
- Some platforms require paid API access or prior approval.
- Repeated collection can increase costs and create duplicate records.
- Collected content may contain personally identifiable information.
- Downstream analytics systems require a consistent data format.
- Collection failures and unavailable sources must be reported transparently.

The module addresses these challenges through policy-aware data acquisition, incremental collection, standardised processing, privacy controls, and traceable delivery.

## 3. Project Scope

### 3.1 In Scope

- Single-company and multi-company input.
- Company input with optional industry labels.
- CSV-based company input.
- Automated collection planning.
- Platform-specific data collection adapters.
- API, RSS feed, dataset, and approved web-scraping methods.
- Cost estimation and budget enforcement.
- Full and incremental (delta) data collection.
- Per-company and per-platform checkpoints.
- Data cleaning and standardisation.
- Duplicate detection.
- Company relevance verification.
- PII masking and author pseudonymisation.
- Standard record generation.
- Data delivery to the Text Analytics project.
- Run monitoring and reporting.
- Privacy, retention, access control, and audit capabilities.

### 3.2 Out of Scope

The Social Listening Module does not perform:

- Sentiment analysis.
- Topic analysis.
- Emotion analysis.
- Text categorisation or classification.
- Response generation.
- Other text analytics operations.

These capabilities belong to the separate **ICXBee Text Analytics project**.

## 4. Data Sources and Collection Methods

The module is designed to collect company-related mentions from sources such as:

- Reddit
- X
- Instagram
- Facebook
- LinkedIn
- Google Business Profile and Google Places
- News websites
- RSS feeds
- Authorised datasets

The actual availability of data depends on each platform's access permissions, API capabilities, terms, and applicable policies.

### Collection Methods

The PRD defines four collection methods:

| Method | Description |
|---|---|
| API | Collect data through an available platform or provider API. |
| RSS Feed | Collect published content from available RSS feeds. |
| Dataset | Use authorised datasets for suitable historical or other available data. |
| Web Scraping | Collect permitted public web content, subject to approval and policy checks. |

### Collection Priority

The system follows a free-first approach:

1. Prefer available official free APIs and RSS feeds.
2. Consider authorised datasets where suitable.
3. Use paid APIs or providers when permitted and within budget.
4. Consider web scraping only as a last resort and when explicitly approved.

The system must not bypass authentication, access controls, platform restrictions, or other security mechanisms.

## 5. System Workflow

The main workflow consists of the following stages:

1. **Company Input:** The user enters one company, multiple companies, or uploads a CSV file.
2. **Planning:** The agent analyses the companies, platforms, access permissions, budgets, and existing checkpoints.
3. **Method Selection:** The agent selects an appropriate permitted collection method for each company-platform combination.
4. **Cost Estimation:** The system estimates the collection cost and checks the available budget.
5. **Data Collection:** Platform-specific adapters collect the available information.
6. **Delta Loading:** Previously collected information is checked so that only new or changed records are collected during repeat runs.
7. **Data Processing:** The collected information is cleaned, mapped, deduplicated, and validated.
8. **Privacy Processing:** Personally identifiable information is masked, and author information is pseudonymised.
9. **Record Generation:** The processed information is converted into the standard `socl.record.v1` format.
10. **Data Delivery:** Records and run information are delivered to the Text Analytics project.
11. **Run Reporting:** The system generates a report containing collection results, failures, costs, and data-quality information.

## 6. Agent Architecture

The module uses a **deterministic planning and orchestration agent**.

The agent is responsible for selecting and coordinating collection methods based on predefined policies and available information.

### Agent Responsibilities

- Understand the collection request.
- Identify the companies and relevant platforms.
- Check source availability and access permissions.
- Evaluate available collection methods.
- Estimate collection costs.
- Check platform and run budgets.
- Generate a collection plan.
- Coordinate platform adapters.
- Handle failures and permitted fallback methods.
- Track collection progress.
- Coordinate processing and delivery.
- Record decisions and fallback reasons.

### Agent Design by Phase

| Phase | Agent Capability |
|---|---|
| Stage 1 | Deterministic collection planning and orchestration. |
| Stage 2 | Deterministic planning with additional paid and approved sources. |
| Stage 3 | Re-rank collection methods using historical run statistics and transparent scoring rules. |

**Important:** The PRD specifies that no LLM is called anywhere in the collection path. Collected text is treated as untrusted data and must not influence the agent's decisions.

## 7. Delta Loading and Checkpoints

Delta loading prevents the system from repeatedly collecting the same information.

### Full Collection

During the initial run, the system performs a full collection for the selected company-platform combinations.

### Incremental Collection

During subsequent runs, the system uses previously stored checkpoints to identify new or updated information.

### Checkpoint Management

- A checkpoint is maintained for each company and platform.
- The system uses checkpoints to determine the collection starting point.
- An overlap window can be used to account for delayed or updated content.
- Failed platform collections must not advance their checkpoints.
- Successful checkpoints are updated only after the relevant processing and saving steps succeed.

This approach reduces unnecessary collection, duplicate records, and avoidable costs.

## 8. Data Processing

Collected information may have different structures and formats depending on the source.

The processing pipeline prepares the information for consistent downstream consumption.

### Processing Steps

1. Field mapping.
2. Content cleaning.
3. Date and timestamp normalisation.
4. HTML sanitisation.
5. Duplicate detection.
6. Company matching and relevance verification.
7. PII masking.
8. Author pseudonymisation.
9. Record labelling and metadata preparation.
10. Completeness and schema validation.
11. Suppression checks.
12. Standard record generation.

Invalid or incomplete records must be handled according to the PRD's validation and quarantine requirements.

## 9. Standard Record Format

The module uses the standard record schema:

`socl.record.v1`

Each record contains structured information, including:

- `schema_version`
- `record_id`
- `mention_id`
- `company`
- `industry`
- `platform`
- `content_type`
- `text`
- `author`
- `source`
- `method_used`
- `run_id`
- `load_type`
- `is_update`
- `company_match`

The complete record must follow the field definitions, mandatory requirements, and validation rules specified in the PRD.

Every record must retain its provenance, including its source, collection method, tool, run ID, and collection time.

## 10. Data Delivery

The processed records are delivered to the downstream **ICXBee Text Analytics project (`Text-Analytics_Base`)**.

The PRD defines three delivery channels:

### 10.1 Paginated JSON Lines API

Records are exposed through a paginated API using JSON Lines format.

### 10.2 AWS S3 Delivery

The system delivers a compressed JSONL file to AWS S3.

The proposed storage region is:

`ap-south-1` (AWS Mumbai)

The file must use KMS encryption.

### 10.3 Webhook Notification

The system sends a signed `run.completed` webhook notification after the run is completed.

Delivery must support appropriate retry and idempotency handling.

## 11. Run Reports and Monitoring

Every collection run generates a report containing information about the execution.

The report includes:

- Run identification and status.
- Companies processed.
- Platforms attempted.
- Collection methods used.
- Records collected.
- Duplicate records.
- Incomplete or rejected records.
- Failed collection methods.
- Source availability and coverage gaps.
- Collection costs.
- Budget usage.
- Checkpoint changes.
- Delivery status.

The report must provide an honest account of both successful and unsuccessful collection attempts.

## 12. Privacy and Security

Privacy and security are mandatory parts of the module.

### Privacy Controls

- PII masking.
- Author pseudonymisation.
- Data suppression.
- Data-subject access requests.
- Data deletion requests.
- Data retention policies.
- Automatic deletion jobs.
- Controlled access to raw collected data.

### Security Controls

- Back-Office authentication.
- Role-based access control.
- Secure credential management.
- Encryption for stored delivery files.
- Audit logging.
- Source permission checks.
- Budget enforcement.
- Scraping approval controls.

### Module Roles

| Role | Responsibility |
|---|---|
| `SOCL_ANALYST` | Create collection runs and view results. |
| `SOCL_PRIVACY` | Manage privacy requests, suppression, retention, and approvals. |
| `SOCL_ADMIN` | Manage configuration, users, connections, and delivery targets. |
| `SOCL_AUDITOR` | Review audit information, reports, and compliance evidence. |

The PRD specifies Back-Office authentication with the token audience `icxbee-bo`.

## 13. Technology Stack

| Component | Technology |
|---|---|
| Programming Language | Python 3.12 |
| Backend API | FastAPI |
| Database | MongoDB 8.0 |
| Background Processing | Worker service |
| Queue | Redis |
| Scheduling | Scheduler service |
| Object Storage | AWS S3 |
| Encryption and Key Management | AWS KMS |
| Credential Management | AWS Secrets Manager |
| API Specification | OpenAPI 3.1 |
| Authentication | ICXBee Back-Office JWT |
| Monitoring | Prometheus |
| Frontend | Existing ICXBee Back-Office shell and shared design system |

The frontend implementation must follow the existing ICXBee Back-Office design conventions.

## 14. Major Application Screens

The PRD defines 15 screens:

| Screen ID | Screen |
|---|---|
| `SOCL-SCR-001` | Runs Dashboard |
| `SOCL-SCR-002` | New Run and Company Input |
| `SOCL-SCR-003` | Collection Plan Preview |
| `SOCL-SCR-004` | Run Monitoring |
| `SOCL-SCR-005` | Run Report |
| `SOCL-SCR-006` | Mentions Explorer |
| `SOCL-SCR-007` | Mention Provenance |
| `SOCL-SCR-008` | Companies and Checkpoints |
| `SOCL-SCR-009` | Source Policy |
| `SOCL-SCR-010` | Scraping Approvals |
| `SOCL-SCR-011` | Budget and Cost |
| `SOCL-SCR-012` | Privacy |
| `SOCL-SCR-013` | Retention and Raw Store |
| `SOCL-SCR-014` | Audit Log |
| `SOCL-SCR-015` | Administration |

The screens must follow the approved Back-Office design system and the state specifications in the PRD.

## 15. Development Phases

The project follows three main implementation stages, preceded by specification and design activities.

### Phase 1 – Specification and Requirements

- Confirm project scope and budget.
- Resolve important open questions.
- Confirm authorised-company and source decisions.
- Establish the PRD baseline.
- Prepare security and NIST CSF 2.0 profiles.

### Phase 2 – Screen Design and Mockups

- Prepare screen specifications.
- Generate mockups for all 15 screens.
- Define the collection method policy table.
- Finalise the standard record schema with the Text Analytics project.

### Phase 3 – Feature and API Specifications

- Prepare feature specifications.
- Define API contracts.
- Prepare test specifications and fixtures.
- Define security and privacy controls.
- Approve screen mockups and interaction flows.

### Phase 4 – Stage 1 Build

Implement the initial release:

- RSS and news collection.
- Free Reddit collection.
- Google Business Profile and Google Places, subject to the applicable access and storage conditions.
- Dataset collection.
- Single-company and multi-company input.
- Delta loading and checkpoints.
- Data processing and standardisation.
- Run reports.
- Data delivery.

### Phase 5 – Stage 2 Build

Extend the collection capabilities:

- X pay-per-use API with a spending cap.
- Meta Graph API for connected accounts.
- LinkedIn Page API.
- One authorised data provider.
- Web scraping only when the required approvals and conditions are satisfied.

### Phase 6 – Stage 3

- Analyse historical run statistics.
- Improve collection-method ranking using transparent scoring.
- Evaluate pilot results.
- Prepare recommendations for further expansion.

## 16. Important Development Rules

1. Follow the requirements and acceptance criteria defined in the PRD.
2. Do not implement sentiment analysis or other text analytics in this module.
3. Use deterministic planning in the initial collection workflow.
4. Respect platform permissions, API terms, and privacy requirements.
5. Never bypass authentication or access restrictions.
6. Enforce budgets before and during collection.
7. Maintain separate checkpoints for each company-platform combination.
8. Do not advance checkpoints for failed collections.
9. Preserve provenance for every processed record.
10. Mask personal information before downstream delivery.
11. Keep credentials and secrets out of source code.
12. Maintain audit records for important operations.
13. Use test fixtures for development and testing instead of depending on live or paid API calls.

## 17. Expected Outcome

The completed module should provide a reliable and traceable data acquisition pipeline that:

- Accepts one or multiple company inputs.
- Collects permitted online mentions from supported sources.
- Selects suitable collection methods based on policies and budgets.
- Avoids unnecessary repeated collection.
- Cleans, validates, and standardises collected information.
- Protects personal information.
- Preserves source and collection provenance.
- Delivers structured records to the Text Analytics project.
- Provides detailed reports, monitoring, and governance controls.

The final objective is to make company-related online data collection organised, incremental, cost-aware, privacy-conscious, and ready for downstream text analytics.

## 18. Reference Documentation

- Social Listening Module PRD v1.0 – November 2, 2026.
- Social Listening Approach Document v2 – October 27, 2026.
- ICXBee Back-Office Login PRD.
- ICXBee Back-Office Master Data PRD.
- ICXBee Text Analytics project.
