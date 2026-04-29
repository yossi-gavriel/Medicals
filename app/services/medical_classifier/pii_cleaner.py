from __future__ import annotations

import re

ISRAELI_ID_PATTERN = re.compile(r"(?<!\d)\d{5,9}(?!\d)")


def mask_israeli_ids(text: str, replacement: str = "[ID_REMOVED]") -> tuple[str, int]:
    if not text:
        return "", 0
    masked, count = ISRAELI_ID_PATTERN.subn(replacement, text)
    return masked, count
