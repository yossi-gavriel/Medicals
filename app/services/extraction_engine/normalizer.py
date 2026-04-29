from __future__ import annotations

import re
from datetime import date

_ISO_DATE = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_DMY_DATE = re.compile(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})\b")
_NUMBER = re.compile(r"-?\d+(?:[.,]\d+)?")


def _safe_iso(year: int, month: int, day: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def normalize_date(text: str) -> str | None:
    """Find the first plausible date in `text` and return it as ISO YYYY-MM-DD.

    Recognized formats:
      - ISO:                       YYYY-MM-DD
      - Day/Month/Year:            DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY (also 2-digit year)
    Two-digit years are interpreted as 2000+YY when YY < 70 else 1900+YY.
    Returns None when no recognizable date is present.
    """
    if not text:
        return None

    iso_match = _ISO_DATE.search(text)
    if iso_match:
        year, month, day = (int(g) for g in iso_match.groups())
        result = _safe_iso(year, month, day)
        if result is not None:
            return result

    dmy_match = _DMY_DATE.search(text)
    if dmy_match:
        day, month, year_raw = (int(g) for g in dmy_match.groups())
        year = year_raw if year_raw >= 100 else (2000 + year_raw if year_raw < 70 else 1900 + year_raw)
        result = _safe_iso(year, month, day)
        if result is not None:
            return result

    return None


def normalize_number(text: str) -> float | int | None:
    """Find the first numeric token and return it as int or float."""
    if not text:
        return None
    match = _NUMBER.search(text)
    if not match:
        return None
    raw = match.group(0).replace(",", ".")
    try:
        if "." in raw:
            return float(raw)
        return int(raw)
    except ValueError:
        return None


def normalize_enum_value(candidate: str, allowed_values: list[str]) -> str | None:
    """Match a candidate string against an enum's allowed_values (case-insensitive)."""
    if not candidate:
        return None
    cleaned = candidate.strip().lower()
    for value in allowed_values:
        if value.lower() == cleaned:
            return value
    return None
