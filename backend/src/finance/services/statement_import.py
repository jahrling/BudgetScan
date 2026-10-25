"""Credit card / bank statement upload: CSV or QFX/OFX into import candidates.

The user picks the target account, so unlike Quicken sync there is no account
mapping step. Output is a ``quicken.ParseResult`` so the same duplicate
matching (``match_candidates``) and confirm flow (``apply_confirmations``)
apply unchanged.

CSV layouts differ by issuer. We locate the header row, then pick columns by
name:

- date: posted date preferred over transaction date (matches what bank feeds
  and Quicken report, so dedup against prior imports lines up)
- description: description / payee / merchant / name
- amount: a single signed column, or separate debit/credit columns

Sign convention internally is negative = money out (a charge). Debit/credit
columns are unambiguous. A single amount column is not: some issuers export
charges as negative, others as positive. With ``invert=None`` we infer from
the majority sign (most statement rows are charges); the caller can force it.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from finance.models.account import Account
from finance.services.quicken import (
    ParseResult,
    TransactionCandidate,
    _amount_to_cents,
    import_qfx,
)


class UnsupportedStatementError(ValueError):
    """The upload isn't a format we can parse (e.g. a PDF)."""


@dataclass
class StatementParseResult(ParseResult):
    format: str = "csv"  # 'csv' | 'ofx' | 'pdf'
    # True when a single amount column was sign-flipped; None when the sign
    # was unambiguous (OFX, or debit/credit columns) and the toggle is moot.
    inverted: bool | None = None
    columns: dict[str, str] = field(default_factory=dict)


# Header names, normalized (lowercase, alnum + spaces). Earlier entries win.
_DATE_COLS = (
    "post date", "posted date", "posting date", "date posted",
    "transaction date", "trans date", "date",
)
_DESC_COLS = (
    "description", "transaction description", "payee", "merchant",
    "merchant name", "name", "details",
)
_AMOUNT_COLS = ("amount", "transaction amount", "amount usd", "billing amount")
_DEBIT_COLS = ("debit", "debits", "withdrawal", "withdrawals", "charge", "charges", "debit amount")
_CREDIT_COLS = ("credit", "credits", "deposit", "deposits", "payment", "payments", "credit amount")

_DATE_FORMATS = (
    "%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%m-%d-%Y", "%m-%d-%y",
    "%Y/%m/%d", "%d %b %Y", "%b %d, %Y", "%b %d %Y", "%d-%b-%Y",
)

_TIME_SUFFIX_RE = re.compile(r"[T\s]+\d{1,2}:\d{2}.*$")

# Unsigned amount + a column saying which way it went (some credit unions).
_DIRECTION_COLS = ("credit debit indicator", "debit credit", "dr cr", "transaction type", "type")
_DEBIT_WORDS = {"debit", "dr", "d"}
_CREDIT_WORDS = {"credit", "cr", "c"}

_MAX_HEADER_SCAN = 20


def _norm(h: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", h.lower()).split())


def _pick(headers: list[str], wanted: tuple[str, ...]) -> int | None:
    normed = [_norm(h) for h in headers]
    for w in wanted:
        if w in normed:
            return normed.index(w)
    return None


def _parse_date(raw: str) -> datetime:
    # Some exports append a time ("01/15/2026 00:00:00", "2026-01-15T00:00Z").
    s = _TIME_SUFFIX_RE.sub("", raw.strip())
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"unparseable date: {raw!r}")


def _parse_amount(raw: str) -> tuple[int, bool] | None:
    """Parse "$1,234.56", "-$5.00", "(12.34)", "12.34 CR". Blank → None.

    Returns (cents, explicit). ``explicit`` is True for a CR/DR suffix, which
    states the direction outright: CR = money in, DR = money out. Those rows
    must not be flipped by sign inference.
    """
    s = raw.strip().replace("$", "").replace(",", "").replace(" ", "")
    if not s:
        return None
    upper = s.upper()
    if upper.endswith(("CR", "DR")):
        cents = abs(_amount_to_cents(s[:-2].strip("()+-")))
        return (cents if upper.endswith("CR") else -cents), True
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    if s.startswith("+"):
        s = s[1:]
    cents = _amount_to_cents(s)
    return (-cents if neg else cents), False


def _decode(file_bytes: bytes) -> str:
    try:
        return file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        return file_bytes.decode("latin-1")


def _find_header(rows: list[list[str]]) -> int | None:
    """Index of the first row that names a date column and an amount column."""
    for i, row in enumerate(rows[:_MAX_HEADER_SCAN]):
        if _pick(row, _DATE_COLS) is None:
            continue
        if _pick(row, _AMOUNT_COLS) is not None or (
            _pick(row, _DEBIT_COLS) is not None and _pick(row, _CREDIT_COLS) is not None
        ):
            return i
    return None


def parse_statement_csv(
    file_bytes: bytes,
    account: Account,
    *,
    invert: bool | None = None,
) -> StatementParseResult:
    result = StatementParseResult(format="csv")
    rows = list(csv.reader(io.StringIO(_decode(file_bytes))))
    header_idx = _find_header(rows)
    if header_idx is None:
        result.errors.append(
            "Couldn't find a header row with date and amount columns. "
            "Expected columns like Date, Description, Amount (or Debit/Credit)."
        )
        return result

    headers = rows[header_idx]
    date_i = _pick(headers, _DATE_COLS)
    desc_i = _pick(headers, _DESC_COLS)
    amount_i = _pick(headers, _AMOUNT_COLS)
    debit_i = _pick(headers, _DEBIT_COLS)
    credit_i = _pick(headers, _CREDIT_COLS)
    split_cols = amount_i is None
    assert date_i is not None

    # Only trust a direction column if its values really are debit/credit
    # words — Chase's "Type" column holds Sale/Payment/Return, for example.
    direction_i = None if split_cols else _pick(headers, _DIRECTION_COLS)
    if direction_i is not None:
        values = [
            row[direction_i].strip().lower()
            for row in rows[header_idx + 1:]
            if direction_i < len(row) and row[direction_i].strip()
        ]
        if not values or not all(v in _DEBIT_WORDS | _CREDIT_WORDS for v in values):
            direction_i = None

    result.columns = {"date": headers[date_i].strip()}
    if desc_i is not None:
        result.columns["description"] = headers[desc_i].strip()
    if split_cols:
        assert debit_i is not None and credit_i is not None
        result.columns["debit"] = headers[debit_i].strip()
        result.columns["credit"] = headers[credit_i].strip()
    else:
        result.columns["amount"] = headers[amount_i].strip()
    if direction_i is not None:
        result.columns["direction"] = headers[direction_i].strip()

    def cell(row: list[str], i: int | None) -> str:
        return row[i] if i is not None and i < len(row) else ""

    explicit_rows: list[bool] = []  # parallel to result.candidates
    for line_no, row in enumerate(rows[header_idx + 1:], start=header_idx + 2):
        if not any(c.strip() for c in row):
            continue
        try:
            posted_at = _parse_date(cell(row, date_i))
            explicit = False
            if split_cols:
                debit = _parse_amount(cell(row, debit_i))
                credit = _parse_amount(cell(row, credit_i))
                if debit is None and credit is None:
                    raise ValueError("empty amount")
                # Issuers disagree on whether these columns carry a sign;
                # the column itself says which way the money moved.
                amount_cents = abs(credit[0] if credit else 0) - abs(debit[0] if debit else 0)
            else:
                parsed = _parse_amount(cell(row, amount_i))
                if parsed is None:
                    raise ValueError("empty amount")
                amount_cents, explicit = parsed
                if direction_i is not None:
                    is_debit = cell(row, direction_i).strip().lower() in _DEBIT_WORDS
                    amount_cents = -abs(amount_cents) if is_debit else abs(amount_cents)
        except ValueError as exc:
            # Footer rows ("Total", disclaimers) land here too; report and move on.
            result.errors.append(f"Row {line_no}: {exc}")
            continue
        description = cell(row, desc_i).strip() or None
        result.candidates.append(
            TransactionCandidate(
                source_account_key=account.name,
                account_id=account.id,
                posted_at=posted_at,
                amount_cents=amount_cents,
                description=description,
                quicken_id=None,
                currency=account.currency,
            )
        )
        explicit_rows.append(explicit)

    if not split_cols and direction_i is None:
        if invert is None:
            nonzero = [
                c.amount_cents
                for c, explicit in zip(result.candidates, explicit_rows)
                if c.amount_cents and not explicit
            ]
            positive = sum(1 for a in nonzero if a > 0)
            invert = positive > len(nonzero) / 2
        if invert:
            for c, explicit in zip(result.candidates, explicit_rows):
                if not explicit:
                    c.amount_cents = -c.amount_cents
        result.inverted = invert

    return result


def detect_format(file_bytes: bytes, filename: str | None) -> str:
    head = file_bytes[:4096]
    name = (filename or "").lower()
    if head.startswith(b"%PDF") or name.endswith(".pdf"):
        raise UnsupportedStatementError(
            "PDF statements are parsed by POST /api/import/statement-pdf."
        )
    if b"<OFX" in head.upper() or name.endswith((".qfx", ".ofx")):
        return "ofx"
    return "csv"


async def parse_statement(
    file_bytes: bytes,
    filename: str | None,
    account: Account,
    session: AsyncSession,
    *,
    invert: bool | None = None,
) -> StatementParseResult:
    fmt = detect_format(file_bytes, filename)
    if fmt == "csv":
        return parse_statement_csv(file_bytes, account, invert=invert)

    parsed = await import_qfx(file_bytes, session, force_account=account)
    result = StatementParseResult(errors=parsed.errors, format="ofx")
    # source_account_key holds the file's ACCTID here. One upload targets one
    # account, so refuse a multi-account export rather than merge it.
    if len({c.source_account_key for c in parsed.candidates}) > 1:
        result.errors.append(
            "This file contains several accounts. Download one account's "
            "activity at a time."
        )
        return result
    for c in parsed.candidates:
        # Set even when the file had no ACCTID (import_qfx only maps on that tag).
        c.account_id = account.id
        c.source_account_key = account.name
    result.candidates = parsed.candidates
    return result
