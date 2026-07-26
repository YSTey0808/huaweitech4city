"""Public entry point — orchestrates the spec pipeline over one message."""

from __future__ import annotations

from . import entities, identifiers
from .segments import make, render


def preprocess_message(text: str) -> str:
    """Input: one raw chat message. Output: normalised message string.
    Replaces identifiers with placeholder tokens (Step 1), then tags entity
    names with homoglyph-tolerant lookup (Step 2); casing, punctuation, emoji
    and elongation are preserved (Step 3)."""
    if not text:
        return text
    segments = make(text)
    segments = identifiers.extract(segments)
    segments = entities.tag(segments)
    return render(segments)
