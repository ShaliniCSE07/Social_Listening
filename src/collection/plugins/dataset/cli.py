"""CLI runner for Dataset collection."""
import argparse
from pathlib import Path
import sys
from typing import Optional

from src.collection.base import CollectionRequest
from src.collection.plugins.dataset.connector import DatasetConnector
from src.contracts.enums import Platform
from src.contracts.io import write_attempts_jsonl, write_mentions_jsonl


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect mentions from offline datasets.")
    parser.add_argument("--company", required=True, help="Target company name")
    parser.add_argument("--dataset", action="append", dest="dataset_keys", default=[], help="Dataset key (repeatable)")
    parser.add_argument("--out", default="data/output", help="Output directory for JSONL files")
    parser.add_argument("--max-age-days", type=float, default=None, help="Freshness threshold in days")
    parser.add_argument("--require-fresh", action="store_true", default=False, help="Skip stale datasets")

    args = parser.parse_args()

    connector = DatasetConnector()
    request = CollectionRequest(
        company=args.company.strip(),
        dataset_keys=args.dataset_keys or None,
        max_age_days=args.max_age_days,
        require_fresh=args.require_fresh,
        platforms=[Platform.other],
    )

    can_run, reason = connector.can_run(request)
    if not can_run:
        print(f"Error: {reason}", file=sys.stderr)
        sys.exit(1)

    mentions, attempts = connector.collect(request)
    attempt_list = attempts if isinstance(attempts, list) else [attempts]

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    mentions_path = out_dir / "mentions.jsonl"
    attempts_path = out_dir / "attempts.jsonl"

    write_mentions_jsonl(mentions_path, mentions)
    write_attempts_jsonl(attempts_path, attempt_list)

    print("--- Dataset Collection Summary ---")
    print(f"Company:        {request.company}")
    print(f"Total Mentions: {len(mentions)}")
    print(f"Total Attempts: {len(attempt_list)}")
    for att in attempt_list:
        print(f"  - Status: {att.status.value:<10} Count: {att.item_count:<5} Reason: {att.reason}")
    print(f"Mentions:       {mentions_path}")
    print(f"Attempts:       {attempts_path}")


if __name__ == "__main__":
    main()

