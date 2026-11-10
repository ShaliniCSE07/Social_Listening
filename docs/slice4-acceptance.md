New-Item -ItemType Directory -Force docs | Out-Null; @'
| Req | Given | When | Then | Test file |
|---|---|---|---|---|
| FR-DLT-01 | a completed run | checkpoint is read | loaded_up_to, cursor, last_run_id, last_run_at, method_used are all present | test_checkpoints.py |
| FR-DLT-02 | no checkpoint, no start date | run starts | window_from = now - 90d, load_type = full | test_windows.py |
| FR-DLT-02 | a start date is given | run starts | window_from = start date | test_windows.py |
| FR-DLT-02 | checkpoint at 30 Sep 23:59:59Z, 2d overlap | run starts 5 Oct | window_from = 28 Sep 23:59:59Z, window_to = run start, load_type = delta | test_windows.py |
| FR-DLT-03 | an overlap item is already stored | saved | counted as duplicate, not delivered twice | test_dedup_overlap.py |
| FR-DLT-04 | no new items | run completes | checkpoint moves to window_to (run start), not newest item date | test_checkpoints.py |
| FR-DLT-05 | a platform fails mid-run | run ends | that platform's checkpoint unchanged, others advanced | test_checkpoints.py |
| FR-DLT-06 | a fallback from API to provider | run completes | one checkpoint (per platform) updated | test_checkpoints.py |
| FR-DLT-07 | manual range for an old month | run ends | checkpoint unchanged, no duplicates | test_manual_range.py |
| FR-DLT-08 | stored item re-read with changed content | saved | new version with is_update=true, old retrievable | test_versions.py |
| FR-DLT-09 | a new company added to saved list | run starts | it is full, others are delta | test_load_type_mix.py |
| FR-DLT-10 | any run | report opened | each platform shows its delta mode | test_report_delta_mode.py |
| GR-9 | a platform fails | run ends | that checkpoint unchanged | test_checkpoints.py |
'@ | Set-Content -Encoding utf8 docs/slice4-acceptance.md