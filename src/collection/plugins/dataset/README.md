# Dataset Collection Plugin

## Purpose
Loads mentions from historical or pre-downloaded datasets (e.g. Kaggle datasets, CSVs, JSON dumps, Hugging Face URLs) with data freshness verification, robust UTF-8/BOM decoding, and size-limited streaming.

## Details
- **Status**: Active
- **Config file**: `config/plugins/dataset.yaml`
- **Catalogue file**: `config/plugins/dataset_catalogue.yaml`
- **Supported Formats**: CSV, JSON, JSONL, ZIP archives
- **Supported Sources**: Local files, HTTPS / Hugging Face URLs, Kaggle datasets

## Key Features

### 1. Company Matching Strategies
Mentions record their match source under `raw_payload["dataset_match_basis"]`:
- **`company_column`**: When a `company` column is mapped in the catalogue, this column wins and determines matching against target company and alt spellings (`default_company` is ignored).
- **`default_company`**: When an entry specifies `default_company` and has no mapped `company` column, all rows belong to that brand. If the run's target company or alt spellings does not match `default_company` (case-insensitive), an empty attempt is returned with reason `"dataset is for <default_company>"`.
- **`text_mention`**: When neither a mapped company column nor `default_company` is specified, rows are filtered by searching for the brand in the mapped `text` column.

### 2. UTF-8 & BOM Decoding Resilience
- Files are opened as UTF-8, automatically falling back to `utf-8-sig` when a UTF-8 BOM (`\xef\xbb\xbf`) is present.
- Non-ASCII text and emojis are fully supported.
- Corrupted or undecodable rows/lines do not crash collection; bad rows are counted and reported in the attempt reason (e.g. `"<count> bad rows had decode errors"`).
- Completely unreadable files fail gracefully with a clear error reason.

### 3. Resource & Download Limits
Configured in `config/plugins/dataset.yaml`:
- **`max_download_mb`** (default `200.0`): Maximum allowed size for downloaded files or zip archives. Exceeding this limit aborts the download and deletes partial files.
- **`max_unpacked_mb`** (default `400.0`): Maximum allowed size for uncompressed / extracted files. Exceeding this limit aborts extraction and cleans up temporary files.
- Large files stream row-by-row via generators, preventing out-of-memory errors.

### 4. Catalogue Configuration
Entries in `config/plugins/dataset_catalogue.yaml` define dataset sources, column mappings, licences, and optional `default_company` or `file` targets.
