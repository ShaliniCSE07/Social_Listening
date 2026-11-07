"""CLI runner for API collection (Reddit and Google Places)."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Optional

from src.collection.base import CollectionRequest
from src.collection.plugins.api.google_places import GooglePlacesConnector
from src.collection.plugins.api.reddit_api import RedditAPIConnector
from src.contracts.enums import Platform
from src.contracts.io import write_attempts_jsonl, write_mentions_jsonl


def parse_iso_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    if not dt_str:
        return None
    try:
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception as e:
        raise argparse.ArgumentTypeError(f"Invalid ISO datetime '{dt_str}': {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect social mentions via official APIs.")
    parser.add_argument("--company", required=True, help="Target company name (e.g. 'Tata Motors')")
    parser.add_argument("--alt", action="append", dest="alt_spellings", default=[], help="Alternative spelling / alias")
    parser.add_argument("--platform", choices=["reddit", "google"], default="reddit", help="Platform to collect from")
    parser.add_argument("--branch", action="append", dest="branches", default=[], help="Branch or location (repeatable)")
    parser.add_argument("--out", default="data/output", help="Output directory for JSONL files")
    parser.add_argument("--run-id", default=None, help="Run identifier")
    parser.add_argument("--date-from", type=parse_iso_datetime, default=None, help="Earliest publication date (ISO)")
    parser.add_argument("--date-to", type=parse_iso_datetime, default=None, help="Latest publication date (ISO)")

    args = parser.parse_args()

    expanded_alts: list[str] = []
    for item in args.alt_spellings:
        for piece in item.split(","):
            cleaned = piece.strip()
            if cleaned and cleaned not in expanded_alts and cleaned != args.company:
                expanded_alts.append(cleaned)

    target_platform = Platform(args.platform)
    if target_platform == Platform.reddit:
        connector = RedditAPIConnector()
    else:
        connector = GooglePlacesConnector()

    request = CollectionRequest(
        company=args.company.strip(),
        alt_spellings=expanded_alts,
        branches=args.branches or [],
        platforms=[target_platform],
        date_from=args.date_from,
        date_to=args.date_to,
        run_id=args.run_id,
    )

    can_run, reason = connector.can_run(request)
    if not can_run:
        print(f"Error: {reason}", file=sys.stderr)
        sys.exit(1)

    mentions, attempt = connector.collect(request)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    mentions_path = out_dir / "mentions.jsonl"
    attempts_path = out_dir / "attempts.jsonl"

    write_mentions_jsonl(mentions_path, mentions)
    write_attempts_jsonl(attempts_path, [attempt])

    print("--- API Collection Summary ---")
    print(f"Company:    {request.company}")
    print(f"Platform:   {target_platform.value}")
    print(f"Status:     {attempt.status.value}")
    print(f"Item Count: {attempt.item_count}")
    print(f"Reason:     {attempt.reason}")
    print(f"Cost USD:   ${attempt.cost_usd:.4f}")
    print(f"Mentions:   {mentions_path}")
    print(f"Attempts:   {attempts_path}")


if __name__ == "__main__":
    main()
