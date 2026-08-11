"""Layer A: deterministic merchant-name cleanup for bank transaction descriptions.

Strips payment-processor prefixes, POS boilerplate, trailing noise (store numbers,
city/state, card suffixes, reference numbers), then normalizes the result into a
form suitable for Tier 0 exact matching against the ``MemorizedRule`` table.

This is pure string manipulation -- no model calls, no DB access, no risk of
hallucination.  It is the highest-ROI piece of the categorization pipeline.

Usage::

    >>> from finance.services.merchant_resolver import clean_description, normalize_for_matching
    >>> clean_description("SQ *JOES COFFEE #1234 SEATTLE WA")
    "Joes Coffee"
    >>> normalize_for_matching("Joe's Coffee!")
    "joes coffee"
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Processor prefixes -- order matters: longer/more specific patterns first
# ---------------------------------------------------------------------------

_PROCESSOR_PREFIXES: list[tuple[re.Pattern[str], str]] = [
    # Amazon marketplace variants -> keep "Amazon" as the merchant
    (re.compile(r"^AMZN\s*MKTP\s*US\s*\*?\s*", re.IGNORECASE), "Amazon "),
    (re.compile(r"^Amazon\.com\s*\*?\s*", re.IGNORECASE), "Amazon "),
    # Square
    (re.compile(r"^SQ\s*\*\s*", re.IGNORECASE), ""),
    # Toast POS
    (re.compile(r"^TST\s*\*\s*", re.IGNORECASE), ""),
    # PayPal (full prefix)
    (re.compile(r"^PAYPAL\s*\*\s*", re.IGNORECASE), ""),
    # PayPal variant (PP*)
    (re.compile(r"^PP\*\s*", re.IGNORECASE), ""),
    # Shopify
    (re.compile(r"^SP\s+\*?\s*", re.IGNORECASE), ""),
    # iCharge
    (re.compile(r"^IC\*\s*", re.IGNORECASE), ""),
    # Check services
    (re.compile(r"^(?:CKE|CHK)\*\s*", re.IGNORECASE), ""),
    # Apple
    (re.compile(r"^APL\*\s*", re.IGNORECASE), ""),
    (re.compile(r"^APPLE\.COM/\s*", re.IGNORECASE), ""),
    # Google
    (re.compile(r"^GOOG\*\s*", re.IGNORECASE), ""),
    (re.compile(r"^GOOGLE\s+\*?\s*", re.IGNORECASE), ""),
    # Uber
    (re.compile(r"^UBER\s*\*\s*", re.IGNORECASE), "Uber "),
    # Lyft
    (re.compile(r"^LYFT\s*\*\s*", re.IGNORECASE), "Lyft "),
    # DoorDash
    (re.compile(r"^DOORDASH\*\s*", re.IGNORECASE), "Doordash "),
    (re.compile(r"^DD\s+\*?\s*", re.IGNORECASE), "Doordash "),
    # Grubhub
    (re.compile(r"^GRUBHUB\*\s*", re.IGNORECASE), "Grubhub "),
    (re.compile(r"^GH\s+\*?\s*", re.IGNORECASE), "Grubhub "),
]

# ---------------------------------------------------------------------------
# POS boilerplate -- removed anywhere in the string
# ---------------------------------------------------------------------------

_POS_BOILERPLATE: list[re.Pattern[str]] = [
    re.compile(r"DEBIT CARD PURCHASE\s*", re.IGNORECASE),
    re.compile(r"POS DEBIT\s+", re.IGNORECASE),
    re.compile(r"POS PURCHASE\s+", re.IGNORECASE),
    re.compile(r"POS\s+", re.IGNORECASE),
    re.compile(r"PURCHASE\s+", re.IGNORECASE),
    re.compile(r"RECURRING PMT\s+", re.IGNORECASE),
    re.compile(r"RECURRING\s+", re.IGNORECASE),
    re.compile(r"CHECKCARD\s+", re.IGNORECASE),
    re.compile(r"CHK CARD\s+", re.IGNORECASE),
]

# ---------------------------------------------------------------------------
# Trailing noise -- removed from the end of the string
# ---------------------------------------------------------------------------

_TRAILING_PATTERNS: list[re.Pattern[str]] = [
    # Card-last-4: x1234, xx1234, *1234
    re.compile(r"\s*x{1,4}\d{4}$", re.IGNORECASE),
    re.compile(r"\s*\*\d{4}$"),
    # Trailing dates: 08/15
    re.compile(r"\s+\d{2}/\d{2}$"),
    # Long reference numbers (8+ digits)
    re.compile(r"\s+\d{8,}$"),
    # Store/terminal numbers: #12345
    re.compile(r"\s*#\d{3,}$"),
    # 4+ trailing digits (store numbers)
    re.compile(r"\s+\d{4,}$"),
    # City + 2-letter state at end: "SEATTLE WA", "NEW YORK NY"
    # Only strip when preceded by at least one alpha word (the merchant name).
    re.compile(r"\s+[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*\s+[A-Z]{2}$"),
]


def clean_description(raw: str) -> str:
    """Apply ordered regex substitutions to clean a bank transaction description.

    Returns a title-cased merchant name with processor noise, POS boilerplate,
    and trailing location/reference data stripped.

    >>> clean_description("SQ *JOES COFFEE #1234 SEATTLE WA")
    'Joes Coffee'
    >>> clean_description("PAYPAL *ACME WIDGETS 08/15")
    'Acme Widgets'
    >>> clean_description("AMZN MKTP US*AB1CD2EF3")
    'Amazon'
    >>> clean_description("DEBIT CARD PURCHASE COSTCO WHSE #1234")
    'Costco Whse'
    """
    text = raw.strip()
    if not text:
        return text

    # Step 1: Strip processor prefixes (apply first match only).
    for pattern, replacement in _PROCESSOR_PREFIXES:
        text, count = pattern.subn(replacement, text, count=1)
        if count:
            break

    # Step 2: Strip POS boilerplate (anywhere).
    for pattern in _POS_BOILERPLATE:
        text = pattern.sub("", text)

    # Step 3: Strip trailing noise (apply all, outermost first).
    # Run multiple passes since stripping one suffix may reveal another.
    for _ in range(3):
        prev = text
        for pattern in _TRAILING_PATTERNS:
            text = pattern.sub("", text)
        if text == prev:
            break

    # Step 4: Final cleanup.
    text = re.sub(r"\s+", " ", text).strip()

    # Title-case: "JOES COFFEE" -> "Joes Coffee"
    if text:
        text = text.title()

    return text


def normalize_for_matching(name: str) -> str:
    """Normalize a merchant name for exact-match lookups.

    Lowercases, strips all non-alphanumeric characters except spaces, and
    collapses whitespace.  The result is what gets stored in
    ``MemorizedRule.normalized_payee`` and used for Tier 0 matching.

    >>> normalize_for_matching("Joe's Coffee!")
    'joes coffee'
    >>> normalize_for_matching("  COSTCO  WHSE  ")
    'costco whse'
    """
    text = name.lower()
    text = re.sub(r"[^a-z0-9\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text
