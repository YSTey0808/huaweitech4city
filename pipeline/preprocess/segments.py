"""Segment machinery: a message is a list of (frozen, text) parts. Frozen parts
are emitted placeholder tokens that later pipeline steps must never touch."""

from __future__ import annotations

import re
from typing import Callable

Seg = tuple[bool, str]
Repl = str | Callable[[re.Match], str | None]
Accept = Callable[[re.Match, int], bool]


def make(text: str) -> list[Seg]:
    """Input: raw message string. Output: initial one-segment list.
    Wraps text so pipeline steps can operate on live/frozen parts."""
    return [(False, text)] if text else []


def render(segments: list[Seg]) -> str:
    """Input: segment list. Output: flat string.
    Joins live text and frozen tokens back into the final message."""
    return "".join(text for _, text in segments)


def sub(
    segments: list[Seg],
    pattern: re.Pattern,
    repl: Repl,
    group: int = 0,
    accept: Accept | None = None,
) -> list[Seg]:
    """Input: segments, compiled pattern, replacement (token str, or fn(Match)->str|None
    where None skips), group index to replace, optional accept(match, segment_offset)
    gate rejecting matches by message-wide position. Output: new segment list.
    Freezes each match's `group` span as a placeholder token; live text only."""
    out: list[Seg] = []
    offset = 0
    for frozen, text in segments:
        if frozen:
            out.append((frozen, text))
            offset += len(text)
            continue
        pos = 0
        for m in pattern.finditer(text):
            if accept is not None and not accept(m, offset):
                continue
            token = repl(m) if callable(repl) else repl
            if token is None:
                continue
            start, end = m.span(group)
            if start > pos:
                out.append((False, text[pos:start]))
            out.append((True, token))
            pos = end
        if pos < len(text):
            out.append((False, text[pos:]))
        offset += len(text)
    return out


def gated_sub(
    segments: list[Seg],
    num_pattern: re.Pattern,
    keyword_pattern: re.Pattern,
    window: int,
    repl: Repl,
) -> list[Seg]:
    """Input: segments, number pattern, gating keyword pattern, char window, replacement.
    Output: new segment list. Freezes number matches that lie within `window` chars
    of a keyword. Keywords are searched message-wide with frozen tokens masked out —
    the masking is load-bearing: token text like "[otp]" contains keyword words, so
    unmasked earlier tokens would gate later numbers."""
    joined = "".join("\x00" * len(text) if frozen else text for frozen, text in segments)
    spans = [m.span() for m in keyword_pattern.finditer(joined)]
    if not spans:
        return segments

    def near_keyword(m: re.Match, offset: int) -> bool:
        a, b = m.start() + offset, m.end() + offset
        return any(ks - b <= window and a - ke <= window for ks, ke in spans)

    return sub(segments, num_pattern, repl, accept=near_keyword)
