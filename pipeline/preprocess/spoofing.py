"""Spoofed-link rule (Step 1.2 of preprocessing_doc.md): classify one matched
link as [url] or [spoofed_link]. A link is spoofed when it contains a homoglyph
or punycode, or when de-obfuscating its domain creates a brand name the raw
domain lacks (rnicrosoft.com folds to microsoft.com; learn.com stays brand-free)."""

from __future__ import annotations

import re

from . import lexicons

# Signal 1: a common homoglyph char or punycode (`xn--`) anywhere in the link.
_HOMOGLYPH_CLASS = "".join(re.escape(c) for c in lexicons.HOMOGLYPHS)
_SPOOF_CHAR = re.compile(rf"[{_HOMOGLYPH_CLASS}]|xn--", re.IGNORECASE)

_DOMAIN = re.compile(r"(?:https?://)?(?:www\.)?([^/\s]+)", re.IGNORECASE)

# Signal 2 targets: Step-2 lookup names plus the curated global list.
_BRANDS = tuple(dict.fromkeys(
    tuple(n.lower().replace(" ", "")
          for names in (*lexicons.LOOKUP_NAMES.values(), *lexicons.STRICT_NAMES.values())
          for n in names)
    + lexicons.SPOOF_BRANDS
))

# Two fold readings of the domain: base table maps 1→l, the second adds 1→i.
_FOLD_BASE = {**lexicons.HOMOGLYPHS, **lexicons.FOLD_ASCII_LOWER}
_FOLDS = (
    str.maketrans(_FOLD_BASE),
    str.maketrans({**_FOLD_BASE, **{v: k for k, v in lexicons.WILDCARD_EXTRAS.items()}}),
)


def _fold_creates_brand(link: str) -> bool:
    """Input: matched link text. Output: True when de-obfuscating the domain
    (0→o, 1→l/i, rn→m, homoglyphs) yields a brand name the raw domain lacks —
    rnicrosoft.com folds to microsoft.com, but learn.com stays brand-free."""
    domain = _DOMAIN.match(link).group(1).lower()
    for table in _FOLDS:
        folded = domain.translate(table)
        for letter, seqs in lexicons.SEQUENCE_FOLDS.items():
            for seq in seqs:
                folded = folded.replace(seq, letter)
        if any(b in folded and b not in domain for b in _BRANDS):
            return True
    return False


def classify_link(m: re.Match) -> str:
    """Input: URL match. Output: [spoofed_link] if the link contains a homoglyph
    or punycode, or its domain de-obfuscates into a brand name; else [url]."""
    link = m.group()
    spoofed = _SPOOF_CHAR.search(link) or _fold_creates_brand(link)
    return "[spoofed_link]" if spoofed else "[url]"
