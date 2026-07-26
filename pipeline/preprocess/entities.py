"""Step 2 — name-based entity tagging. Runs on raw (pre-fold) text with
homoglyph-tolerant matching, so `1` can resolve as `l` or `i` (fix #9).
Patterns are built from the lexicon lists and compiled once at import."""

from __future__ import annotations

import re

from . import lexicons
from .segments import Seg, sub


def _inverse_folds() -> dict[str, set[str]]:
    """Output: latin letter -> the look-alike chars that fold to it, inverted
    from the homoglyph/ASCII/wildcard maps in lexicons.py."""
    inverse: dict[str, set[str]] = {}
    for src, dst in {**lexicons.HOMOGLYPHS, **lexicons.FOLD_ASCII_LOWER}.items():
        inverse.setdefault(dst.lower(), set()).add(src)
    for dst, src in lexicons.WILDCARD_EXTRAS.items():
        inverse.setdefault(dst, set()).add(src)
    return inverse


def _name_pattern(name: str, inverse: dict[str, set[str]]) -> str:
    """Input: entity name plus the inverse fold map. Output: regex fragment.
    Maps each letter to a char class of itself plus its homoglyphs (case handled
    by IGNORECASE), plus any look-alike sequences (rn for m); spaces become \\s*
    so joined spellings also match."""
    parts = []
    for ch in name:
        if ch == " ":
            parts.append(r"\s*")
        elif ch.isalpha() and ch.isascii():
            cls = {ch.lower()} | inverse.get(ch.lower(), set())
            frag = "[" + "".join(re.escape(c) for c in sorted(cls)) + "]"
            seqs = lexicons.SEQUENCE_FOLDS.get(ch.lower())
            if seqs:
                frag = "(?:%s|%s)" % (frag, "|".join(map(re.escape, seqs)))
            parts.append(frag)
        else:
            parts.append(re.escape(ch))
    return "".join(parts)


def _build_patterns() -> tuple[re.Pattern, re.Pattern]:
    """Output: (fuzzy, strict) entity patterns with one named group per category.
    Fuzzy is homoglyph-tolerant and case-insensitive; strict is exact-case for
    names that are also common words (Trust, Grab)."""
    inverse = _inverse_folds()
    fuzzy = "|".join(
        "(?P<%s>%s)" % (cat, "|".join(_name_pattern(n, inverse)
                                      for n in sorted(names, key=len, reverse=True)))
        for cat, names in lexicons.LOOKUP_NAMES.items()
    )
    strict = "|".join(
        "(?P<%s>%s)" % (cat, "|".join(map(re.escape, names)))
        for cat, names in lexicons.STRICT_NAMES.items()
    )
    return (
        re.compile(r"(?<!\w)(?:%s)(?!\w)" % fuzzy, re.IGNORECASE),
        re.compile(r"\b(?:%s)\b" % strict),  # case-sensitive
    )


ENTITY_FUZZY, ENTITY_STRICT = _build_patterns()


def tag(segments: list[Seg]) -> list[Seg]:
    """Input: segments after Step 1. Output: segments with org/payment names frozen
    as [gov]/[bank]/[delivery]/[platform]/[payment_app] tokens.
    Fuzzy (homoglyph, case-insensitive) pass first, then exact-case pass for
    common-word names (Trust, Grab)."""
    segments = sub(segments, ENTITY_FUZZY, lambda m: f"[{m.lastgroup}]")
    segments = sub(segments, ENTITY_STRICT, lambda m: f"[{m.lastgroup}]")
    return segments
