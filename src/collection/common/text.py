"""Shared text matching utilities for brand identification."""
import re
from typing import List, Optional


def normalize_text(text: str) -> str:
    """Normalize text by lowering case and stripping extra whitespace."""
    return re.sub(r"\s+", " ", text).strip().lower()


def matches_company(
    text: str,
    company: str,
    alt_spellings: Optional[List[str]] = None,
    handles: Optional[List[str]] = None,
) -> bool:
    """Check if normalized text contains the company name, alt spellings, or handles."""
    if not text:
        return False

    norm_text = normalize_text(text)
    targets = [company] + (alt_spellings or []) + (handles or [])

    for target in targets:
        clean_target = normalize_text(target)
        if not clean_target:
            continue
        # If target starts with @ or #, check literal presence
        if clean_target.startswith(("@", "#")):
            if clean_target in norm_text:
                return True
        else:
            # Word boundary check for word targets
            pattern = rf"\b{re.escape(clean_target)}\b"
            if re.search(pattern, norm_text, re.IGNORECASE):
                return True

    return False

