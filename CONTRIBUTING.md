# Contributing Guidelines

## Team Responsibilities & Ownership
- **Member 1 (Collection)**:
  - Owns `src/collection/` and all plugin implementations.
  - Owns `config/plugins/<name>.yaml` for collection plugins.
  - Owns `tests/collection/`.
- **Member 2 (Processing, Storage, Reporting & Pipeline)**:
  - Owns `src/processing/`, `src/storage/`, `src/reporting/`, and `pipeline.py`.
  - Reviews schemas in `src/contracts/schemas.py`.
  - Owns `tests/processing/`, `tests/storage/`, and `tests/integration/`.
- **Shared Contracts (`src/contracts/`)**:
  - `enums.py`, `schemas.py`, and `io.py` are shared contracts between collection and downstream processing.
  - Any modifications must be proposed via a minimal PR and explicitly reviewed by the counterpart.

## Git Workflow
- `main` must always remain stable and pass all tests (`pytest`).
- Branch naming convention: `feature/<plugin-or-component>-<short-description>` (e.g., `feature/api-reddit-connector`, `feature/processing-dedup`).
- Always pull the latest changes before starting work: `git pull origin main`.
- Run the full test suite locally before pushing: `python -m pytest -v`.

## Checklist for Adding a New Collection Plugin / Connector
1. **Module creation**: Add a package under `src/collection/plugins/<name>/`.
2. **Connector implementation**: Subclass `BaseConnector` from `src/collection/base.py`.
3. **Export connector**: Add `CONNECTORS = [MyConnector]` to `src/collection/plugins/<name>/__init__.py`.
4. **Configuration**: Provide `config/plugins/<name>.yaml` with configuration defaults.
5. **Documentation**: Add `README.md` in the plugin directory explaining target platforms, setup, credentials, and constraints.
6. **Testing**: Add unit tests in `tests/collection/<name>/` verifying `can_run`, `estimate_cost`, and output contracts.
7. **Contract compliance**: Ensure all collected items are serialized as valid `RawMention` instances and attempts as `CollectionAttempt`.

