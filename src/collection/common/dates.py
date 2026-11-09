"""Date and datetime conversion utilities for collection layer."""
from datetime import date, datetime, time, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Optional


def to_utc(value: Any) -> Optional[datetime]:
    """Convert a datetime, date, string or numeric timestamp to an aware UTC datetime.

    - If value is already an aware datetime, converts it to UTC.
    - If value is a naive datetime, treats it as UTC.
    - If value is a date (not datetime), treats it as midnight UTC.
    - If value is an int or float, treats it as a POSIX timestamp.
    - If value is a string, parses ISO formats, RFC 2822, or common date formats.
      If the parsed result has no timezone, treats it as UTC; otherwise converts to UTC.
    - Returns None if value is None, empty, or cannot be parsed.
    """
    if value is None:
        return None

    # Check datetime first because datetime inherits from date
    if isinstance(value, datetime):
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=timezone.utc)

    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except Exception:
            return None

    if not isinstance(value, str):
        try:
            val_str = str(value).strip()
        except Exception:
            return None
    else:
        val_str = value.strip()

    if not val_str:
        return None

    # 1. Try ISO 8601
    try:
        dt = datetime.fromisoformat(val_str)
        if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass

    # 2. Try RFC 2822 / HTTP format (e.g. Last-Modified header)
    try:
        dt = parsedate_to_datetime(val_str)
        if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass

    # 3. Try common date formats
    for fmt in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%d-%m-%Y %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M",
        "%b %d, %Y",
        "%B %d, %Y",
        "%d %b %Y",
        "%d %B %Y",
    ):
        try:
            dt = datetime.strptime(val_str, fmt)
            if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            continue

    return None

