from __future__ import annotations

import re

_WHITESPACE_PATTERN = re.compile(r"\s+")

# Sentence terminators handled: ASCII (.!?;), Hebrew period/colon (׃), and newlines.
# We split *after* the terminator so the punctuation is preserved on the previous chunk.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?;׃])\s+|\n+")


def normalize_whitespace(text: str) -> str:
    """Collapse runs of whitespace into a single space and strip the result."""
    if not text:
        return ""
    return _WHITESPACE_PATTERN.sub(" ", text).strip()


def split_sentences(text: str) -> list[str]:
    """Split text into sentence-like chunks usable for evidence extraction.

    The split is intentionally lightweight: it preserves Hebrew text (which is
    inherently Unicode) and avoids any language-specific tokenizer dependency.
    Returned chunks are stripped and non-empty.
    """
    if not text:
        return []
    parts = _SENTENCE_BOUNDARY.split(text)
    return [chunk.strip() for chunk in parts if chunk and chunk.strip()]
