"""Step 1 — extract high-cardinality identifiers into placeholder tokens,
in spec order (most specific first) so digits are claimed before folding."""

from __future__ import annotations

import re

from . import lexicons, patterns
from .segments import Seg, gated_sub, sub
from .spoofing import classify_link

_MULT = {"k": 1_000, "m": 1_000_000, "mil": 1_000_000}


def _bucket(amount: float) -> str:
    """Input: parsed SGD amount. Output: [money_eN] token.
    Buckets by order of magnitude, N clamped to [0, 6] (integer-based, no float log)."""
    n = 0 if amount < 1 else min(len(str(int(amount))) - 1, 6)
    return f"[money_e{n}]"


def _acct_repl(m: re.Match) -> str | None:
    """Input: BANK_ACCT match. Output: [bank_acct] token, or None to skip.
    Validates the spec's 7–14 digit count after stripping spaces/dashes."""
    return "[bank_acct]" if 7 <= len(patterns.NON_DIGIT.sub("", m.group(1))) <= 14 else None


def _money_marked_repl(m: re.Match) -> str:
    """Input: MONEY_MARKED match. Output: [money_eN] token.
    Parses commas/decimals and k/m/mil suffixes into a numeric amount."""
    num = m.group("num1") or m.group("num2")
    suffix = (m.group("suf1") or m.group("suf2") or "").lower()
    return _bucket(float(num.replace(",", "")) * _MULT.get(suffix, 1))


def _money_bare_repl(m: re.Match) -> str:
    """Input: bare-number match (already keyword-gated). Output: [money_eN] token."""
    return _bucket(float(m.group().replace(",", "")))


def extract(segments: list[Seg]) -> list[Seg]:
    """Input: segments from make(). Output: segments with all Step-1 identifiers
    frozen as tokens. Runs the 9 spec substeps in order (most specific first)."""
    segments = sub(segments, patterns.HANDLE_LINK, "[handle]")
    segments = sub(segments, patterns.HANDLE_PHRASE, "[handle]", group=1)
    segments = sub(segments, patterns.HANDLE_BARE, "[handle]")
    segments = sub(segments, patterns.URL_SCHEME, classify_link)
    segments = sub(segments, patterns.URL_BARE, classify_link)
    segments = sub(segments, patterns.NRIC, "[nric]")
    segments = sub(segments, patterns.UEN, "[uen]")
    segments = sub(segments, patterns.WALLET, "[wallet]")
    segments = gated_sub(segments, patterns.OTP_NUM, patterns.OTP_KEYWORDS,
                         lexicons.OTP_WINDOW, "[otp]")
    segments = sub(segments, patterns.BANK_ACCT, _acct_repl, group=1)
    segments = sub(segments, patterns.PHONE, "[phone]")
    segments = sub(segments, patterns.MONEY_MARKED, _money_marked_repl)
    segments = gated_sub(segments, patterns.MONEY_BARE, patterns.MONEY_KEYWORDS,
                         lexicons.MONEY_WINDOW, _money_bare_repl)
    return segments
