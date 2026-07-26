"""Step-1 identifier regexes, compiled once at import so per-message calls pay
zero compilation cost. Patterns follow preprocessing_doc.md; the spoofed-link
fold lives in spoofing.py and the Step-2 entity patterns in entities.py."""

import re

from . import lexicons

# Last char of a link — stops trailing sentence punctuation being swallowed.
_TRAIL = r"""[^\s.,;:!?)"'\]]"""

# ---------------------------------------------------------------------------
# Step 1.1 — contact-redirect handles
# ---------------------------------------------------------------------------
HANDLE_LINK = re.compile(
    rf"(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me|wa\.me|api\.whatsapp\.com)/\S*{_TRAIL}",
    re.IGNORECASE,
)
# "whatsapp/telegram me (at|on) <@handle | phone-like>" — only the target is replaced.
HANDLE_PHRASE = re.compile(
    r"\b(?:whatsapp|telegram|tele)\s+(?:me|us)\s+(?:(?:at|on)\s+)?"
    r"(@\w{3,32}|\+?\d[\d\s\-]{6,13}\d)",
    re.IGNORECASE,
)
# Bare @handle; lookbehind keeps emails (john@x.com) intact.
HANDLE_BARE = re.compile(r"(?<![\w.@])@\w{3,32}\b")

# ---------------------------------------------------------------------------
# Step 1.2 — URLs (scheme'd first, then bare domains; no lookup exclusions)
# ---------------------------------------------------------------------------
URL_SCHEME = re.compile(rf"(?:https?://|www\.)\S*{_TRAIL}", re.IGNORECASE)
_TLDS = "|".join(lexicons.URL_TLDS)
URL_BARE = re.compile(
    rf"(?<![@\w.])(?:[a-z0-9](?:[a-z0-9\-]*[a-z0-9])?\.)+(?:{_TLDS})\b(?:/\S*{_TRAIL})?",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Steps 1.3–1.5 — NRIC, UEN, wallet (spec regexes)
# ---------------------------------------------------------------------------
NRIC = re.compile(r"\b[STFGM]\d{7}[A-Z]\b")
UEN = re.compile(r"\b(?:\d{8,9}[A-Z]|[STR]\d{2}[A-Z]{2}\d{4}[A-Z])\b")
_B58 = r"[1-9A-HJ-NP-Za-km-z]"
WALLET = re.compile(
    rf"\b(?:0x[a-fA-F0-9]{{40}}|bc1[a-z0-9]{{25,60}}|[13]{_B58}{{25,34}}|T{_B58}{{33}})\b"
)

# ---------------------------------------------------------------------------
# Step 1.6 — OTP: 4–8 digit standalone run, gated by a nearby keyword
# ---------------------------------------------------------------------------
OTP_NUM = re.compile(r"(?<![\w,.$])\d{4,8}(?![A-Za-z\d]|[.,]\d)")
OTP_KEYWORDS = re.compile(r"\b(?:%s)\b" % "|".join(lexicons.OTP_KEYWORDS), re.IGNORECASE)

# ---------------------------------------------------------------------------
# Step 1.7 — bank account: keyword-gated digits; digit count validated in code
# ---------------------------------------------------------------------------
BANK_ACCT = re.compile(
    r"\b(?:account|acct|acc|a/c)\b[^\d\n]{0,10}(\d[\d\s\-]{5,16}\d)", re.IGNORECASE
)
NON_DIGIT = re.compile(r"\D+")

# ---------------------------------------------------------------------------
# Step 1.8 — SG phone; lookarounds stop firing inside money amounts, longer
# digit runs, and alphanumeric IDs (e.g. parcel code SG66493012)
# ---------------------------------------------------------------------------
PHONE = re.compile(r"(?<![\w$.,])(?:\+?65[\s\-]?)?[3689]\d{3}[\s\-]?\d{4}(?![A-Za-z\d])")

# ---------------------------------------------------------------------------
# Step 1.9 — money: marked amounts, then keyword-gated bare numbers
# ---------------------------------------------------------------------------
_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
MONEY_MARKED = re.compile(
    rf"(?:S?\$|SGD)\s*(?P<num1>{_NUM})(?:\s?(?P<suf1>mil|k|m)\b)?"
    rf"|\b(?P<num2>{_NUM})(?P<suf2>mil|k|m)\b",
    re.IGNORECASE,
)
_UNITS = "|".join(lexicons.NOT_MONEY_UNITS)
MONEY_BARE = re.compile(rf"\b(?:{_NUM})\b(?!\s?%|\s+(?:{_UNITS})\b)", re.IGNORECASE)
MONEY_KEYWORDS = re.compile(r"\b(?:%s)\b" % "|".join(lexicons.MONEY_KEYWORDS), re.IGNORECASE)
