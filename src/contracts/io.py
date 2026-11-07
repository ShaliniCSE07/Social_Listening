import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Union

from src.contracts.schemas import CollectionAttempt, RawMention


def write_mentions_jsonl(path: Union[str, Path], mentions: List[RawMention]) -> None:
    """Write RawMention instances as JSON lines."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        for mention in mentions:
            f.write(mention.model_dump_json() + "\n")


def read_mentions_jsonl(path: Union[str, Path]) -> Dict[str, List[RawMention]]:
    """Read mentions.jsonl and group results by company.

    Raises an error with the line number on invalid format or content.
    """
    file_path = Path(path)
    if not file_path.exists():
        return {}

    grouped: Dict[str, List[RawMention]] = defaultdict(list)
    with open(file_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line_str = line.strip()
            if not line_str:
                continue
            try:
                data = json.loads(line_str)
                mention = RawMention.model_validate(data)
                grouped[mention.company].append(mention)
            except Exception as e:
                raise ValueError(f"Error parsing line {line_num} in {file_path}: {e}") from e

    return dict(grouped)


def write_attempts_jsonl(path: Union[str, Path], attempts: List[CollectionAttempt]) -> None:
    """Write CollectionAttempt instances as JSON lines."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        for attempt in attempts:
            f.write(attempt.model_dump_json() + "\n")


def read_attempts_jsonl(path: Union[str, Path]) -> List[CollectionAttempt]:
    """Read attempts.jsonl as a flat list of CollectionAttempt instances.

    Raises an error with the line number on invalid format or content.
    """
    file_path = Path(path)
    if not file_path.exists():
        return []

    attempts: List[CollectionAttempt] = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line_str = line.strip()
            if not line_str:
                continue
            try:
                data = json.loads(line_str)
                attempt = CollectionAttempt.model_validate(data)
                attempts.append(attempt)
            except Exception as e:
                raise ValueError(f"Error parsing line {line_num} in {file_path}: {e}") from e

    return attempts

