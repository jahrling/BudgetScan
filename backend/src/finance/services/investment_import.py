"""Investment import: QIF !Type:Invst/Security/Prices parsing, manual snapshots,
and benchmark CSV upload.

Fixes F1 (investment records silently dropped) by actually parsing investment
blocks instead of routing them to a dead-end section kind. Unknown action codes
surface in errors rather than being swallowed.

QIF action code mapping follows plan §4.2. The Cash action is not one action
(F12) — it is split by sign and L/Y fields.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from io import StringIO

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# QIF action code → §2.2 action mapping
# ---------------------------------------------------------------------------


_QIF_ACTION_MAP: dict[str, str] = {
    "buy": "buy",
    "buyx": "buy",
    "sell": "sell",
    "sellx": "sell",
    "div": "dividend",
    "divx": "dividend",
    "reinvdiv": "reinvest_dividend",
    "reinvlg": "reinvest_capital_gain",
    "reinvsh": "reinvest_capital_gain",
    "reinvint": "reinvest_dividend",
    "cglong": "capital_gain_dist",
    "cglongx": "capital_gain_dist",
    "cgshort": "capital_gain_dist",
    "cgshortx": "capital_gain_dist",
    "cgmid": "capital_gain_dist",
    "cgmidx": "capital_gain_dist",
    "intinc": "interest",
    "intincx": "interest",
    "shrsin": "shares_in",
    "shrsout": "shares_out",
    "xin": "cash_in",
    "xout": "cash_out",
    "miscexp": "fee",
    "miscinc": "interest",
    "stksplit": "split",
    "contribx": "cash_in",
    "withdrwx": "cash_out",
    "rtrncap": "return_of_capital",
    "rtrncapx": "return_of_capital",
    "margint": "fee",
    "margintx": "fee",
}

# Recognized but out-of-scope for v1 (equity compensation).
_OUT_OF_SCOPE_ACTIONS = frozenset({"vest", "grant", "exercise"})

# QIF security type letter → our security_type.
_SECURITY_TYPE_MAP: dict[str, str] = {
    "stock": "stock",
    "mutual fund": "mutual_fund",
    "bond": "bond",
    "option": "other",
    "index": "index",
    "other": "other",
}


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass
class InvestmentCandidate:
    """A parsed investment transaction, not yet persisted."""
    account_key: str
    action: str
    trade_date: date
    security_name: str | None = None
    quantity_micros: int | None = None
    price_micros: int | None = None
    amount_cents: int = 0
    fee_cents: int = 0
    memo: str | None = None
    transfer_account: str | None = None
    external_id: str | None = None


@dataclass
class SecurityCandidate:
    """A security parsed from !Type:Security."""
    name: str
    symbol: str | None = None
    security_type: str = "other"


@dataclass
class PriceCandidate:
    """A price point parsed from !Type:Prices."""
    security_name: str
    price_micros: int
    date: date


@dataclass
class InvestmentParseResult:
    candidates: list[InvestmentCandidate] = field(default_factory=list)
    securities: list[SecurityCandidate] = field(default_factory=list)
    prices: list[PriceCandidate] = field(default_factory=list)
    unmapped_accounts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skipped_count: int = 0


# ---------------------------------------------------------------------------
# Amount / quantity / price parsing
# ---------------------------------------------------------------------------


_AMOUNT_RE = re.compile(r"^-?\d+(?:\.\d+)?$")


def _parse_cents(raw: str) -> int:
    s = raw.strip().replace(",", "").replace("$", "")
    if not s:
        raise ValueError("empty amount")
    if not _AMOUNT_RE.match(s):
        raise ValueError(f"unparseable amount: {raw!r}")
    neg = s.startswith("-")
    if neg:
        s = s[1:]
    if "." in s:
        whole, frac = s.split(".", 1)
        frac = (frac + "00")[:2]
    else:
        whole, frac = s, "00"
    cents = int(whole) * 100 + int(frac)
    return -cents if neg else cents


def _parse_micros(raw: str) -> int:
    """Parse a decimal string to integer millionths (× 1,000,000)."""
    s = raw.strip().replace(",", "").replace("$", "")
    if not s:
        raise ValueError("empty value")
    neg = s.startswith("-")
    if neg:
        s = s[1:]
    if "." in s:
        whole, frac = s.split(".", 1)
        frac = (frac + "000000")[:6]
    else:
        whole, frac = s, "000000"
    micros = int(whole) * 1_000_000 + int(frac)
    return -micros if neg else micros


def _parse_qif_date(raw: str) -> date:
    s = raw.strip().replace("'", "/").replace(" ", "")
    fmts = ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%d/%m/%Y")
    from datetime import datetime
    for fmt in fmts:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unparseable QIF date: {raw!r}")


# ---------------------------------------------------------------------------
# Content hash for QIF deduplication (no FITIDs in QIF)
# ---------------------------------------------------------------------------


def _content_hash(
    trade_date: date,
    action: str,
    security_name: str | None,
    quantity_micros: int | None,
    amount_cents: int,
) -> str:
    parts = [
        trade_date.isoformat(),
        action,
        security_name or "",
        str(quantity_micros or 0),
        str(amount_cents),
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]


# ---------------------------------------------------------------------------
# Cash action subtype mapping (F12)
# ---------------------------------------------------------------------------


def _map_cash_action(
    amount_cents: int,
    category_raw: str | None,
    security_name: str | None,
) -> str | None:
    """Map the QIF 'Cash' action to a specific action based on context.

    Returns None to signal "skip this record" (e.g., no amount).
    """
    if amount_cents == 0:
        return None

    cat = (category_raw or "").lower().strip()

    if "interest" in cat:
        return "interest"

    if security_name:
        return "other"

    if amount_cents > 0:
        return "cash_in"
    return "cash_out"


# ---------------------------------------------------------------------------
# QIF investment block parser
# ---------------------------------------------------------------------------


def parse_investment_qif(text: str) -> InvestmentParseResult:
    """Parse investment blocks from a QIF document.

    Handles !Type:Invst, !Type:Security, !Type:Prices, and !Account blocks.
    This is a standalone parser (not async, no DB) — the caller is responsible
    for resolving securities by name and persisting.
    """
    result = InvestmentParseResult()

    current_account_key: str = ""
    section_kind: str | None = None
    record: dict[str, str] = {}

    for raw_line in StringIO(text):
        line = raw_line.rstrip("\r\n")
        if not line:
            continue

        if line.startswith("!"):
            header = line[1:].strip()
            hl = header.lower()
            if hl.startswith("account"):
                section_kind = "account"
            elif hl.startswith("type:invst"):
                section_kind = "invst"
            elif hl.startswith("type:security"):
                section_kind = "security_def"
            elif hl.startswith("type:prices"):
                section_kind = "prices"
            elif hl in ("option:autoswitch", "clear:autoswitch"):
                continue
            else:
                section_kind = "other"
            record = {}
            continue

        if line == "^":
            if section_kind == "account":
                acct_name = record.get("N", "").strip()
                current_account_key = acct_name
            elif section_kind == "invst":
                _flush_invst_record(
                    record, current_account_key, result,
                )
            elif section_kind == "security_def":
                _flush_security_record(record, result)
            record = {}
            continue

        if section_kind == "prices":
            _parse_price_line(line, result)
            continue

        code = line[0]
        value = line[1:]

        if section_kind == "account":
            record[code] = value
        elif section_kind == "invst":
            if code in record and code in ("S", "E", "$"):
                record[code] = value
            else:
                record[code] = value
        elif section_kind == "security_def":
            record[code] = value

    return result


def _flush_invst_record(
    record: dict[str, str],
    account_key: str,
    result: InvestmentParseResult,
) -> None:
    """Process one ^-terminated investment transaction record."""
    raw_action = record.get("N", "").strip()
    raw_date = record.get("D", "").strip()

    if not raw_action:
        result.errors.append(f"Investment record missing action (N line), date={raw_date}")
        return

    action_lower = raw_action.lower()

    if action_lower in _OUT_OF_SCOPE_ACTIONS:
        result.errors.append(
            f"Out-of-scope action '{raw_action}' (equity compensation) skipped"
        )
        result.skipped_count += 1
        return

    # Cash action needs special handling (F12)
    if action_lower == "cash":
        try:
            trade_date = _parse_qif_date(raw_date) if raw_date else None
        except ValueError:
            trade_date = None

        amount_cents = 0
        if record.get("T"):
            try:
                amount_cents = _parse_cents(record["T"])
            except ValueError:
                pass
        elif record.get("U"):
            try:
                amount_cents = _parse_cents(record["U"])
            except ValueError:
                pass

        if amount_cents == 0 and trade_date:
            result.errors.append(
                f"Cash record with no amount on {raw_date} skipped"
            )
            result.skipped_count += 1
            return

        mapped_action = _map_cash_action(
            amount_cents,
            record.get("L"),
            record.get("Y"),
        )
        if mapped_action is None:
            result.skipped_count += 1
            return
        action = mapped_action
    else:
        action = _QIF_ACTION_MAP.get(action_lower)
        if action is None:
            result.errors.append(f"Unknown investment action code: '{raw_action}'")
            result.skipped_count += 1
            return

    try:
        trade_date = _parse_qif_date(raw_date)
    except ValueError as e:
        result.errors.append(f"Bad date in investment record: {e}")
        return

    security_name = record.get("Y", "").strip() or None
    memo = record.get("M", "").strip() or None

    # Parse quantity, price, amount, fee
    quantity_micros: int | None = None
    price_micros: int | None = None
    amount_cents = 0
    fee_cents = 0

    if record.get("Q"):
        try:
            quantity_micros = _parse_micros(record["Q"])
        except ValueError as e:
            result.errors.append(f"Bad quantity: {e}")
            return

    if record.get("I"):
        try:
            price_micros = _parse_micros(record["I"])
        except ValueError as e:
            result.errors.append(f"Bad price: {e}")
            return

    if record.get("T"):
        try:
            amount_cents = _parse_cents(record["T"])
        except ValueError as e:
            result.errors.append(f"Bad amount: {e}")
            return
    elif record.get("U"):
        try:
            amount_cents = _parse_cents(record["U"])
        except ValueError as e:
            result.errors.append(f"Bad amount: {e}")
            return

    if record.get("O"):
        try:
            fee_cents = _parse_cents(record["O"])
        except ValueError as e:
            result.errors.append(f"Bad commission: {e}")
            return

    # Transfer account (X suffix actions)
    transfer_account: str | None = None
    if record.get("L"):
        l_value = record["L"].strip()
        if l_value.startswith("[") and l_value.endswith("]"):
            transfer_account = l_value[1:-1]

    # Generate content hash for dedup (QIF has no FITIDs)
    external_id = _content_hash(
        trade_date, action, security_name, quantity_micros, amount_cents,
    )

    # For memo, also capture the L field info if it has category info
    if not memo and record.get("L") and not transfer_account:
        memo = record["L"].strip()

    candidate = InvestmentCandidate(
        account_key=account_key,
        action=action,
        trade_date=trade_date,
        security_name=security_name,
        quantity_micros=quantity_micros,
        price_micros=price_micros,
        amount_cents=amount_cents,
        fee_cents=fee_cents,
        memo=memo,
        transfer_account=transfer_account,
        external_id=external_id,
    )
    result.candidates.append(candidate)


def _flush_security_record(
    record: dict[str, str],
    result: InvestmentParseResult,
) -> None:
    """Process one ^-terminated !Type:Security record."""
    name = record.get("N", "").strip()
    if not name:
        return
    symbol = record.get("S", "").strip() or None
    raw_type = record.get("T", "other").strip().lower()
    security_type = _SECURITY_TYPE_MAP.get(raw_type, "other")

    result.securities.append(
        SecurityCandidate(name=name, symbol=symbol, security_type=security_type)
    )


def _parse_price_line(line: str, result: InvestmentParseResult) -> None:
    """Parse a QIF !Type:Prices line: "SYM",price,"MM/DD/YYYY" """
    line = line.strip()
    if not line or line == "^":
        return

    parts = line.split(",")
    if len(parts) < 3:
        return

    security_name = parts[0].strip().strip('"')
    if not security_name:
        return

    try:
        price_micros = _parse_micros(parts[1].strip().strip('"'))
    except ValueError:
        result.errors.append(f"Bad price in !Type:Prices: {line!r}")
        return

    raw_date = parts[2].strip().strip('"')
    try:
        price_date = _parse_qif_date(raw_date)
    except ValueError:
        result.errors.append(f"Bad date in !Type:Prices: {line!r}")
        return

    result.prices.append(
        PriceCandidate(security_name=security_name, price_micros=price_micros, date=price_date)
    )


# ---------------------------------------------------------------------------
# Benchmark CSV upload parser
# ---------------------------------------------------------------------------


@dataclass
class PriceCSVResult:
    prices: list[PriceCandidate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def parse_price_csv(text: str, security_name: str) -> PriceCSVResult:
    """Parse a CSV with date,close columns (Yahoo Finance / Stooq format).

    Expects a header row. The date column can be 'Date' or 'date', and the
    close column can be 'Close', 'close', 'Adj Close', or 'adj close'.
    """
    result = PriceCSVResult()
    lines = text.strip().split("\n")
    if len(lines) < 2:
        result.errors.append("CSV must have a header row and at least one data row")
        return result

    header = lines[0].lower().split(",")
    date_col = None
    close_col = None
    for i, h in enumerate(header):
        h = h.strip().strip('"')
        if h in ("date",):
            date_col = i
        elif h in ("close", "adj close", "adj_close"):
            close_col = i

    if date_col is None or close_col is None:
        result.errors.append(
            "CSV header must contain 'Date' and 'Close' (or 'Adj Close') columns"
        )
        return result

    for line_num, line in enumerate(lines[1:], start=2):
        parts = line.split(",")
        if len(parts) <= max(date_col, close_col):
            continue

        raw_date = parts[date_col].strip().strip('"')
        raw_close = parts[close_col].strip().strip('"')

        if not raw_date or not raw_close or raw_close.lower() == "null":
            continue

        try:
            price_date = _parse_qif_date(raw_date)
        except ValueError:
            from datetime import datetime
            try:
                price_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
            except ValueError:
                result.errors.append(f"Line {line_num}: bad date {raw_date!r}")
                continue

        try:
            price_micros = _parse_micros(raw_close)
        except ValueError:
            result.errors.append(f"Line {line_num}: bad price {raw_close!r}")
            continue

        result.prices.append(
            PriceCandidate(
                security_name=security_name,
                price_micros=price_micros,
                date=price_date,
            )
        )

    return result
