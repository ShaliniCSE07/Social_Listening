"""Row mapping logic based on catalogue specifications."""
from typing import Any, Dict, Optional


def map_row(row: Dict[str, Any], column_mapping: Dict[str, str]) -> Dict[str, Any]:
    """Extract standard mapped fields from a raw row dict.

    Standard keys: text, date, id, company, rating, author, url, branch.
    """
    mapped: Dict[str, Any] = {}
    for standard_field, source_col in column_mapping.items():
        if source_col and source_col in row:
            mapped[standard_field] = row[source_col]
        else:
            mapped[standard_field] = None
    return mapped


def validate_mapping(row: Dict[str, Any], column_mapping: Dict[str, str]) -> Optional[str]:
    """Validate that required source columns exist in the raw row.

    'text' column mapping is required.
    """
    text_col = column_mapping.get("text")
    if not text_col:
        return "Catalogue entry missing required column mapping: 'text'"

    if text_col not in row:
        return f"Required mapped text column '{text_col}' not found in dataset row"

    return None

