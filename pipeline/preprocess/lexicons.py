"""Lookup data only — no logic. Extend coverage by editing the tuples here;
patterns.py compiles everything at import time."""

# ---------------------------------------------------------------------------
# Step 2 lookup lists — case-insensitive, homoglyph-tolerant matching.
# Dict order = match priority: payment_app first so "GrabPay" wins over "Grab".
# ---------------------------------------------------------------------------
LOOKUP_NAMES: dict[str, tuple[str, ...]] = {
    "payment_app": ("PayNow", "PayLah", "GrabPay", "PayPal",
                    "ShopeePay", "YouTrip", "Revolut"), 
    # "gov.sg" intentionally absent: bare domains are claimed as [url] in Step 1.
    "gov": (
        # Full agency names
        "Singapore Police Force", "Ministry of Manpower", "Ministry of Health",
        "Immigration & Checkpoints Authority", "Immigration and Checkpoints Authority",
        "Central Provident Fund", "Inland Revenue Authority of Singapore",
        "Monetary Authority of Singapore",
        # Abbreviations
        # MOM lives in STRICT_NAMES
        "Singpass", "Police", "SPF", "MOH", "ICA", "CPF", "IRAS", "MAS", "govt", "gov",
    ),
    "bank": ("Standard Chartered", "Citibank", "Maybank", "POSB", "OCBC", "DBS", "UOB", "GXS", "United Overseas Bank"),
    "delivery": ("SingPost", "SpeedPost", "Ninja Van", "J&T", "DHL"), 
    # WhatsApp/Telegram excluded: contact-redirect semantics belong to [handle].
    "platform": ("Carousell", "Instagram", "Facebook", "Shopee", "Lazada"),
}

# Names that are also common English words: exact-case match, no homoglyph tolerance.
STRICT_NAMES: dict[str, tuple[str, ...]] = {
    "gov": ("MOM",),
    "bank": ("Trust",),
    "platform": ("Grab",),
    "payment_app": ("Wise",), 
}

# ---------------------------------------------------------------------------
# Keyword gates for context-dependent numeric identifiers.
# ---------------------------------------------------------------------------
OTP_KEYWORDS = ("one-time password", "one time password", "verification", "passcode",
                "verify", "codes", "code", "otp", "pin", "2fa", "singpass")
OTP_WINDOW = 30  # max chars between code and keyword

MONEY_KEYWORDS = (
    "transferred", "investment", "commission", "transfer", "payment", "deposit",
    "paying", "refund", "salary", "profit", "amount", "charge", "invest", "top up",
    "top-up", "topup", "money", "price", "fees", "paid", "sent", "send", "cash",
    "cost", "earn", "owe", "fee", "pay", "win", "won", "sum",
)
MONEY_WINDOW = 30  # max chars between bare number and keyword

# A bare number followed by one of these units is a time/count, never money.
NOT_MONEY_UNITS = (
    "minutes", "minute", "mins", "min", "hours", "hour", "hrs", "hr",
    "seconds", "secs", "days", "day", "weeks", "week", "months", "month",
    "years", "year", "yrs", "yr", "am", "pm", "times", "slots", "slot",
    "people", "pax", "percent",
)

# ---------------------------------------------------------------------------
# TLDs recognised for scheme-less URLs (bare domains).
# ---------------------------------------------------------------------------
URL_TLDS = (
    "com", "net", "org", "sg", "co", "io", "me", "xyz", "info", "biz", "site",
    "online", "shop", "store", "top", "club", "vip", "cc", "tv", "link", "live",
    "app", "space", "website", "fun", "icu", "buzz", "cn", "ru", "win",
    "sbs", "cfd", "bond", "lol", "li", "es", 
)

# ---------------------------------------------------------------------------
# Homoglyph maps — feed the Step 1.2 spoofed-link fold and the Step 2 entity
# lookup. Curated Cyrillic/Greek -> Latin.
# ---------------------------------------------------------------------------
HOMOGLYPHS: dict[str, str] = {
    # Cyrillic lowercase
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x",
    "і": "i", "ѕ": "s", "ј": "j", "һ": "h", "ԁ": "d", "ԛ": "q", "ԝ": "w",
    "к": "k", "м": "m", "т": "t", "в": "b", "н": "n",
    # Cyrillic uppercase
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O",
    "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X", "Ѕ": "S", "І": "I", "Ј": "J",
    # Greek lowercase
    "α": "a", "ο": "o", "ν": "v", "ρ": "p", "τ": "t", "υ": "u", "ι": "i",
    "κ": "k", "η": "n", "ε": "e", "χ": "x",
    # Greek uppercase
    "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K",
    "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X",
}

# ASCII look-alike folds feeding homoglyph-tolerant entity lookup (g0v, Pay1ah).
FOLD_ASCII_LOWER = {"0": "o", "1": "l", "$": "s"}
WILDCARD_EXTRAS = {"i": "1"} # extra reading: 1 can also be i 
SEQUENCE_FOLDS: dict[str, tuple[str, ...]] = {"m": ("rn",)} # "rn" reads as "m" (rnicrosoft)

# Extra brands (lowercase) for the spoofed-link fold.
# a link is [spoofed_link] only when de-obfuscating its domain creates one of
# these (rnicrosoft.com -> microsoft.com), not when the brand is already present.
SPOOF_BRANDS = ("microsoft", "google", "apple", "amazon", "netflix",
                "whatsapp", "telegram", "outlook", "icloud")
