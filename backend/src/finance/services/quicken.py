"""Quicken interop: parse QFX/OFX and QIF, and emit QIF with split categories.

Design notes
------------
QFX is a Microsoft-flavored OFX 1.x SGML payload preceded by a header block.
We don't pull in a full OFX parser — the documents we care about are small and
the subset we need (account id, txn date, amount, memo/name, FITID) is easy to
walk with a tag-aware tokenizer that tolerates unclosed tags.

QIF is a flat record-per-block format with single-letter type tags
(D=date, T=amount, P=payee, M=memo, L=category, S/E/$ for splits, ^ separator).
Categories in QIF use ":" between parent and child — we use the same
convention internally when emitting full category paths.

Mapping to our model
--------------------
- Accounts are mapped by ``Account.quicken_id`` (set to the QFX ACCTID or the
  QIF ``!Account`` block name). Unmapped accounts surface in
  ``ParseResult.unmapped_accounts`` so the UI can prompt the user.
- A parse never throws on a single bad row: errors collect per-row in
  ``ParseResult.errors`` and the rest continue.
- Currency mismatch (a QFX CURDEF that disagrees with the mapped account's
  currency) is a hard error per the brief — logged in ``errors`` and the
  whole sub-list is skipped.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from io import StringIO
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from finance.models.account import Account
from finance.models.category import Category
from finance.models.line_item import LineItem
from finance.models.transaction import Transaction

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Data classes shared by importers
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class TransactionCandidate:
    """A parsed inbound transaction not yet persisted.

    ``account_id`` is None when the source account couldn't be mapped to one of
    our accounts; ``source_account_key`` always carries the raw identifier so
    the UI can offer to create or map it.
    """

    source_account_key: str  # raw ACCTID / QIF !Account name
    account_id: int | None
    posted_at: datetime
    amount_cents: int
    description: str | None
    quicken_id: str | None  # FITID / QIF "N" tag if present
    currency: str | None = None
    splits: list["SplitCandidate"] = field(default_factory=list)
    cleared: str | None = None  # None | '*' (cleared) | 'X' (reconciled)
    transfer_account: str | None = None  # populated when L=[Account Name]
    # Populated by match_candidates():
    match_status: str = "new"  # 'new' | 'duplicate' | 'likely-duplicate' | 'matched-receipt'
    match_transaction_id: int | None = None


@dataclass
class SplitCandidate:
    category_path: str  # full colon-joined path, e.g. "Food:Groceries"
    amount_cents: int
    description: str | None = None


@dataclass
class CategoryDefinition:
    """A category parsed from a QIF !Type:Cat block."""

    name: str  # full colon-joined path, e.g. "Food & Dining:Groceries"
    description: str | None = None
    is_income: bool = False
    tax_related: bool = False
    tax_schedule: str | None = None  # e.g. "R286"


@dataclass
class MemorizedRule:
    """A memorized payee-to-category mapping from QIF !Type:Memorized."""

    payee: str
    category_path: str  # full colon-joined path
    amount_cents: int | None = None
    transfer_account: str | None = None  # when category is [Account Name]
    kind: str = "payment"  # 'payment' | 'deposit' | 'check' | 'transfer'


@dataclass
class ParseResult:
    candidates: list[TransactionCandidate] = field(default_factory=list)
    unmapped_accounts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    categories: list[CategoryDefinition] = field(default_factory=list)
    memorized_rules: list[MemorizedRule] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────────
# Money helpers
# ──────────────────────────────────────────────────────────────────────────────


_AMOUNT_RE = re.compile(r"^-?\d+(?:\.\d+)?$")


def _amount_to_cents(raw: str) -> int:
    """Convert "12.34" / "-12.34" / "1,234.56" to integer cents.

    Raises ValueError on garbage so callers can record a per-row error.
    """
    s = raw.strip().replace(",", "").replace("$", "")
    if not s:
        raise ValueError("empty amount")
    if not _AMOUNT_RE.match(s):
        raise ValueError(f"unparseable amount: {raw!r}")
    # Use string arithmetic to avoid float drift on .005 boundaries.
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


def _cents_to_amount(cents: int) -> str:
    """Inverse of _amount_to_cents — emits a fixed two-decimal string."""
    neg = cents < 0
    c = abs(cents)
    return f"{'-' if neg else ''}{c // 100}.{c % 100:02d}"


# ──────────────────────────────────────────────────────────────────────────────
# QFX / OFX parsing
# ──────────────────────────────────────────────────────────────────────────────


_TAG_RE = re.compile(r"<(/?)([A-Za-z0-9._]+)>([^<\r\n]*)")


def _ofx_strip_header(text: str) -> str:
    """Drop the OFX 1.x header block (everything before the first '<')."""
    idx = text.find("<OFX")
    if idx < 0:
        idx = text.find("<ofx")
    if idx < 0:
        return text
    return text[idx:]


def _ofx_tokenize(body: str) -> Iterable[tuple[str, str, str]]:
    """Yield (closing, tag, inline_value) tuples in document order.

    OFX 1.x SGML lets value tags omit their close (``<DTPOSTED>20240101``),
    so we treat any tag followed by text on the same line as a leaf.
    """
    for m in _TAG_RE.finditer(body):
        closing, tag, inline = m.group(1), m.group(2).upper(), m.group(3).strip()
        yield closing, tag, inline


def _parse_ofx_datetime(raw: str) -> datetime:
    """Parse OFX YYYYMMDD or YYYYMMDDHHMMSS[.XXX][TZ]."""
    s = raw.strip()
    # Strip timezone suffix like "[-5:EST]" — we treat all dates as UTC midnight
    # since QFX is just a daily snapshot for this app.
    tz_idx = s.find("[")
    if tz_idx >= 0:
        s = s[:tz_idx]
    # Drop fractional seconds if any
    if "." in s:
        s = s.split(".", 1)[0]
    fmts = ("%Y%m%d%H%M%S", "%Y%m%d")
    for fmt in fmts:
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"unparseable OFX date: {raw!r}")


async def _account_map_by_quicken_id(session: AsyncSession) -> dict[str, Account]:
    result = await session.execute(
        select(Account).where(Account.quicken_id.is_not(None))
    )
    return {a.quicken_id: a for a in result.scalars().all() if a.quicken_id}


async def import_qfx(file_bytes: bytes, session: AsyncSession) -> ParseResult:
    """Parse a QFX/OFX file into transaction candidates.

    Accounts are mapped via ``Account.quicken_id``. Unmapped account ids are
    listed in ``ParseResult.unmapped_accounts`` so the UI can prompt the user.
    Currency mismatches (CURDEF != account.currency) skip the whole statement.
    """
    result = ParseResult()
    text = file_bytes.decode("utf-8", errors="replace")
    body = _ofx_strip_header(text)
    if "<OFX" not in body.upper():
        result.errors.append("Not an OFX/QFX document (no <OFX> root)")
        return result

    accounts = await _account_map_by_quicken_id(session)

    # Walk statements: each STMTRS / CCSTMTRS block has CURDEF, ACCTID,
    # and a BANKTRANLIST of STMTTRN entries.
    current_acctid: str | None = None
    current_curdef: str | None = None
    current_account: Account | None = None
    in_stmttrn = False
    txn: dict[str, str] = {}
    skip_stmt = False

    for closing, tag, inline in _ofx_tokenize(body):
        if closing:
            if tag == "STMTTRN" and in_stmttrn:
                if not skip_stmt:
                    _flush_qfx_txn(
                        txn, current_acctid, current_account, current_curdef, result
                    )
                in_stmttrn = False
                txn = {}
            elif tag in ("STMTRS", "CCSTMTRS"):
                current_acctid = None
                current_account = None
                current_curdef = None
                skip_stmt = False
            continue

        if tag == "STMTTRN":
            in_stmttrn = True
            txn = {}
            continue

        if in_stmttrn:
            if inline:
                txn[tag] = inline
            continue

        # Statement-level header tags
        if tag == "CURDEF" and inline:
            current_curdef = inline.upper()
        elif tag == "ACCTID" and inline:
            current_acctid = inline
            current_account = accounts.get(inline)
            if current_account is None:
                if inline not in result.unmapped_accounts:
                    result.unmapped_accounts.append(inline)
            elif current_curdef and current_account.currency.upper() != current_curdef:
                msg = (
                    f"Currency mismatch for account {inline}: "
                    f"file={current_curdef} account={current_account.currency}"
                )
                logger.warning(msg)
                result.errors.append(msg)
                skip_stmt = True

    return result


def _flush_qfx_txn(
    txn: dict[str, str],
    acctid: str | None,
    account: Account | None,
    curdef: str | None,
    result: ParseResult,
) -> None:
    if not txn:
        return
    try:
        posted_raw = txn.get("DTPOSTED") or txn.get("DTUSER") or ""
        amount_raw = txn.get("TRNAMT", "")
        if not posted_raw or not amount_raw:
            raise ValueError("missing DTPOSTED or TRNAMT")
        posted_at = _parse_ofx_datetime(posted_raw)
        amount_cents = _amount_to_cents(amount_raw)
        description = txn.get("NAME") or txn.get("MEMO") or txn.get("PAYEEID")
        fitid = txn.get("FITID")
    except Exception as exc:  # don't fail entire import on one bad row
        result.errors.append(f"QFX STMTTRN error: {exc}")
        return

    cand = TransactionCandidate(
        source_account_key=acctid or "",
        account_id=account.id if account else None,
        posted_at=posted_at,
        amount_cents=amount_cents,
        description=description,
        quicken_id=fitid,
        currency=curdef,
    )
    result.candidates.append(cand)


# ──────────────────────────────────────────────────────────────────────────────
# QIF parsing
# ──────────────────────────────────────────────────────────────────────────────


def _parse_transfer(value: str) -> tuple[str | None, str]:
    """Extract transfer account from QIF L field.

    ``[Account Name]`` → (transfer_account="Account Name", category="")
    ``Food:Groceries`` → (None, "Food:Groceries")
    """
    stripped = value.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        return stripped[1:-1], ""
    return None, stripped


_MEMORIZED_KIND = {"P": "payment", "D": "deposit", "C": "check", "T": "transfer"}


async def import_qif(file_bytes: bytes, session: AsyncSession) -> ParseResult:
    """Parse a QIF document including category definitions and memorized rules."""
    result = ParseResult()
    text = file_bytes.decode("utf-8", errors="replace")

    accounts_by_name = await _account_map_by_quicken_id(session)
    name_map = await session.execute(select(Account))
    by_name = {a.name: a for a in name_map.scalars().all()}

    current_account: Account | None = None
    current_account_key: str = ""
    # section_kind: 'account' | 'txn' | 'cat' | 'memorized' | 'security' | 'tag' | None
    section_kind: str | None = None
    record: dict[str, object] = {}

    def reset_record() -> None:
        nonlocal record
        record = {"splits": []}

    reset_record()

    for raw_line in StringIO(text):
        line = raw_line.rstrip("\r\n")
        if not line:
            continue

        if line.startswith("!"):
            header = line[1:].strip()
            hl = header.lower()
            if hl.startswith("account"):
                section_kind = "account"
            elif hl.startswith("type:cat"):
                section_kind = "cat"
            elif hl.startswith("type:memorized"):
                section_kind = "memorized"
            elif hl.startswith("type:security"):
                section_kind = "security"
            elif hl.startswith("type:tag"):
                section_kind = "tag"
            elif hl in ("option:autoswitch", "clear:autoswitch"):
                continue
            else:
                section_kind = "txn"
            reset_record()
            continue

        if line == "^":
            if section_kind == "account":
                acct_name = str(record.get("name", "")).strip()
                current_account_key = acct_name
                current_account = (
                    accounts_by_name.get(acct_name) or by_name.get(acct_name)
                )
                if current_account is None and acct_name:
                    if acct_name not in result.unmapped_accounts:
                        result.unmapped_accounts.append(acct_name)
            elif section_kind == "txn":
                _flush_qif_txn(
                    record, current_account_key, current_account, result
                )
            elif section_kind == "cat":
                _flush_qif_cat(record, result)
            elif section_kind == "memorized":
                _flush_qif_memorized(record, result)
            reset_record()
            continue

        code = line[0]
        value = line[1:]

        if section_kind == "account":
            if code == "N":
                record["name"] = value
            elif code == "T":
                record["type"] = value
            continue

        if section_kind == "cat":
            if code == "N":
                record["name"] = value
            elif code == "D":
                record["description"] = value
            elif code == "I":
                record["is_income"] = True
            elif code == "E":
                record["is_expense"] = True
            elif code == "T":
                record["tax_related"] = True
            elif code == "R":
                record["tax_schedule"] = value
            continue

        if section_kind == "memorized":
            if code == "K":
                record["kind"] = value
            elif code == "P":
                record["payee"] = value
            elif code == "L":
                record["category"] = value
            elif code == "T" or code == "U":
                record["amount"] = value
            elif code == "C":
                record["cleared"] = value
            continue

        if section_kind in ("security", "tag"):
            continue

        # txn block
        if code == "D":
            record["date"] = value
        elif code == "T" or code == "U":
            record["amount"] = value
        elif code == "P":
            record["payee"] = value
        elif code == "M":
            record["memo"] = value
        elif code == "L":
            record["category"] = value
        elif code == "N":
            record["ref"] = value
        elif code == "C":
            record["cleared"] = value
        elif code == "S":
            record["splits"].append({"category": value, "amount": None, "memo": None})  # type: ignore[union-attr]
        elif code == "E":
            splits = record["splits"]  # type: ignore[assignment]
            if splits:
                splits[-1]["memo"] = value  # type: ignore[index]
        elif code == "$":
            splits = record["splits"]  # type: ignore[assignment]
            if splits:
                splits[-1]["amount"] = value  # type: ignore[index]

    return result


def _flush_qif_cat(
    record: dict[str, object],
    result: ParseResult,
) -> None:
    name = str(record.get("name", "")).strip()
    if not name:
        return
    result.categories.append(
        CategoryDefinition(
            name=name,
            description=str(record["description"]) if record.get("description") else None,
            is_income=bool(record.get("is_income")),
            tax_related=bool(record.get("tax_related")),
            tax_schedule=str(record["tax_schedule"]) if record.get("tax_schedule") else None,
        )
    )


def _flush_qif_memorized(
    record: dict[str, object],
    result: ParseResult,
) -> None:
    payee = str(record.get("payee", "")).strip()
    cat_raw = str(record.get("category", "")).strip()
    if not payee and not cat_raw:
        return
    transfer_account, category_path = _parse_transfer(cat_raw) if cat_raw else (None, "")
    kind_code = str(record.get("kind", "P")).strip()
    kind = _MEMORIZED_KIND.get(kind_code, "payment")
    amount_cents: int | None = None
    if record.get("amount"):
        try:
            amount_cents = _amount_to_cents(str(record["amount"]))
        except ValueError:
            pass
    result.memorized_rules.append(
        MemorizedRule(
            payee=payee,
            category_path=category_path,
            amount_cents=amount_cents,
            transfer_account=transfer_account,
            kind=kind,
        )
    )


def _flush_qif_txn(
    record: dict[str, object],
    acct_key: str,
    account: Account | None,
    result: ParseResult,
) -> None:
    if not record.get("date") and not record.get("amount"):
        return
    try:
        posted_at = _parse_qif_date(str(record.get("date", "")))
        amount_cents = _amount_to_cents(str(record.get("amount", "")))
    except Exception as exc:
        result.errors.append(f"QIF record error: {exc}")
        return

    description = record.get("payee") or record.get("memo")
    cleared = str(record["cleared"]) if record.get("cleared") else None
    transfer_account: str | None = None

    cat_raw = str(record.get("category", "")).strip() if record.get("category") else ""
    if cat_raw:
        transfer_account, cat_raw = _parse_transfer(cat_raw)

    splits_raw = record.get("splits") or []
    splits: list[SplitCandidate] = []
    if isinstance(splits_raw, list) and splits_raw:
        for s in splits_raw:
            try:
                amt = (
                    _amount_to_cents(str(s.get("amount")))
                    if s.get("amount") is not None
                    else None
                )
            except Exception as exc:
                result.errors.append(f"QIF split amount error: {exc}")
                continue
            if amt is None:
                continue
            s_cat = str(s.get("category") or "")
            _, s_cat_path = _parse_transfer(s_cat) if s_cat else (None, "")
            splits.append(
                SplitCandidate(
                    category_path=s_cat_path,
                    amount_cents=amt,
                    description=str(s["memo"]) if s.get("memo") else None,
                )
            )
    elif cat_raw:
        splits.append(
            SplitCandidate(
                category_path=cat_raw,
                amount_cents=amount_cents,
                description=str(description) if description else None,
            )
        )

    result.candidates.append(
        TransactionCandidate(
            source_account_key=acct_key,
            account_id=account.id if account else None,
            posted_at=posted_at,
            amount_cents=amount_cents,
            description=str(description) if description else None,
            quicken_id=str(record["ref"]) if record.get("ref") else None,
            splits=splits,
            cleared=cleared,
            transfer_account=transfer_account,
        )
    )


def _parse_qif_date(raw: str) -> datetime:
    """QIF dates are typically MM/DD/YY or MM/DD'YYYY.

    Accepts a handful of common forms so we don't choke on Quicken UK /
    European variants.
    """
    s = raw.strip().replace("'", "/").replace(" ", "")
    fmts = ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%d/%m/%Y")
    for fmt in fmts:
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"unparseable QIF date: {raw!r}")


# ──────────────────────────────────────────────────────────────────────────────
# Duplicate / receipt matching
# ──────────────────────────────────────────────────────────────────────────────


async def match_candidates(
    session: AsyncSession,
    candidates: list[TransactionCandidate],
) -> None:
    """Annotate candidates in-place with match_status / match_transaction_id.

    Checks in priority order:
    1. quicken_id (FITID) exact match — definitive dedup for QFX imports.
    2. Same account + amount + date + description — strong dedup for QIF.
    3. Receipt match within ±2 days — links bank transactions to snapped receipts.
    4. Same account + amount + date (no description match) — flagged as
       'likely-duplicate' so the user can decide (could be two legit
       transactions at different payees for the same amount).
    """
    from datetime import timedelta

    for c in candidates:
        if c.account_id is None:
            continue

        # 1. Exact quicken_id / FITID match
        if c.quicken_id:
            fitid_match = await session.execute(
                select(Transaction).where(
                    Transaction.account_id == c.account_id,
                    Transaction.quicken_id == c.quicken_id,
                ).limit(1)
            )
            existing = fitid_match.scalar_one_or_none()
            if existing is not None:
                c.match_status = "duplicate"
                c.match_transaction_id = existing.id
                continue

        same_day_start = c.posted_at.replace(hour=0, minute=0, second=0, microsecond=0)
        same_day_end = same_day_start.replace(hour=23, minute=59, second=59)

        # 2. Amount + date + description (strong match for QIF)
        if c.description:
            desc_match = await session.execute(
                select(Transaction).where(
                    Transaction.account_id == c.account_id,
                    Transaction.amount_cents == c.amount_cents,
                    Transaction.description == c.description,
                    Transaction.posted_at >= same_day_start,
                    Transaction.posted_at <= same_day_end,
                ).limit(1)
            )
            existing = desc_match.scalar_one_or_none()
            if existing is not None:
                c.match_status = "duplicate"
                c.match_transaction_id = existing.id
                continue

        # 3. Receipt match within ±2 days
        window_start = c.posted_at - timedelta(days=2)
        window_end = c.posted_at + timedelta(days=2)
        receipt_match = await session.execute(
            select(Transaction).where(
                Transaction.account_id == c.account_id,
                Transaction.amount_cents == c.amount_cents,
                Transaction.receipt_id.is_not(None),
                Transaction.posted_at >= window_start,
                Transaction.posted_at <= window_end,
            ).limit(1)
        )
        rmatch = receipt_match.scalar_one_or_none()
        if rmatch is not None:
            c.match_status = "matched-receipt"
            c.match_transaction_id = rmatch.id
            continue

        # 4. Amount + date only — weaker signal, let user decide
        amount_date_match = await session.execute(
            select(Transaction).where(
                Transaction.account_id == c.account_id,
                Transaction.amount_cents == c.amount_cents,
                Transaction.posted_at >= same_day_start,
                Transaction.posted_at <= same_day_end,
            ).limit(1)
        )
        existing = amount_date_match.scalar_one_or_none()
        if existing is not None:
            c.match_status = "likely-duplicate"
            c.match_transaction_id = existing.id


# ──────────────────────────────────────────────────────────────────────────────
# Category path resolution
# ──────────────────────────────────────────────────────────────────────────────


async def _all_categories(session: AsyncSession) -> list[Category]:
    result = await session.execute(select(Category))
    return list(result.scalars().all())


def _build_category_paths(cats: list[Category]) -> dict[str, Category]:
    by_id = {c.id: c for c in cats}

    def path_of(c: Category) -> str:
        parts = [c.name]
        parent_id = c.parent_id
        while parent_id is not None:
            parent = by_id.get(parent_id)
            if parent is None:
                break
            parts.append(parent.name)
            parent_id = parent.parent_id
        return ":".join(reversed(parts))

    return {path_of(c): c for c in cats}


async def resolve_category_path(
    session: AsyncSession,
    path: str,
    *,
    create_missing: bool = False,
) -> Category | None:
    """Resolve "Food:Groceries:Costco" to a Category, optionally creating.

    Returns None when not found and create_missing is False. Created paths are
    flattened — `Food:Groceries:Costco` becomes a single category named after
    the full path (not nested), per the prompt's "flat path" instruction.
    """
    cats = await _all_categories(session)
    paths = _build_category_paths(cats)
    if path in paths:
        return paths[path]
    # Also tolerate matching the leaf only when the full path is missing
    leaf = path.rsplit(":", 1)[-1]
    for full, cat in paths.items():
        if full.rsplit(":", 1)[-1] == leaf:
            return cat
    if not create_missing:
        return None
    cat = Category(name=path)
    session.add(cat)
    await session.flush()
    return cat


# ──────────────────────────────────────────────────────────────────────────────
# Import confirmation
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class ConfirmAction:
    """One row of /api/import/confirm body."""

    candidate_index: int
    action: str  # 'create' | 'skip' | 'merge-with:<existing_tx_id>'


@dataclass
class ConfirmResult:
    created_ids: list[int] = field(default_factory=list)
    merged_ids: list[int] = field(default_factory=list)
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


async def apply_confirmations(
    session: AsyncSession,
    candidates: list[TransactionCandidate],
    actions: list[ConfirmAction],
    *,
    create_missing_categories: bool = False,
) -> ConfirmResult:
    """Apply the user's per-candidate decisions atomically.

    Anything that errors collects in ``result.errors`` and the transaction is
    rolled back so the user can fix and retry.
    """
    result = ConfirmResult()
    try:
        for action in actions:
            if action.candidate_index < 0 or action.candidate_index >= len(candidates):
                result.errors.append(f"bad index {action.candidate_index}")
                continue
            cand = candidates[action.candidate_index]
            if action.action == "skip":
                result.skipped += 1
                continue
            if cand.account_id is None:
                result.errors.append(
                    f"candidate {action.candidate_index} has no mapped account"
                )
                continue
            if action.action.startswith("merge-with:"):
                target_id = int(action.action.split(":", 1)[1])
                await _merge_candidate(session, cand, target_id, result, create_missing_categories)
            elif action.action == "create":
                await _create_from_candidate(session, cand, result, create_missing_categories)
            else:
                result.errors.append(f"unknown action {action.action!r}")
        if result.errors:
            await session.rollback()
        else:
            await session.commit()
    except Exception as exc:
        await session.rollback()
        result.errors.append(str(exc))
    return result


async def _resolve_splits(
    session: AsyncSession,
    splits: list[SplitCandidate],
    total_amount_cents: int,
    create_missing: bool,
    result: ConfirmResult,
) -> list[LineItem] | None:
    """Materialize SplitCandidates into LineItem rows (not yet attached)."""
    items: list[LineItem] = []
    for s in splits:
        cat = await resolve_category_path(
            session, s.category_path, create_missing=create_missing
        )
        if cat is None:
            result.errors.append(
                f"category path not found: {s.category_path!r} "
                "(enable create_missing_categories to auto-create)"
            )
            return None
        items.append(
            LineItem(
                category_id=cat.id,
                amount_cents=s.amount_cents,
                description=s.description,
            )
        )
    return items


async def _create_from_candidate(
    session: AsyncSession,
    cand: TransactionCandidate,
    result: ConfirmResult,
    create_missing_categories: bool,
) -> None:
    assert cand.account_id is not None
    txn = Transaction(
        account_id=cand.account_id,
        posted_at=cand.posted_at,
        amount_cents=cand.amount_cents,
        description=cand.description,
        quicken_id=cand.quicken_id,
        status="pending",
    )
    session.add(txn)
    await session.flush()

    if cand.splits:
        items = await _resolve_splits(
            session, cand.splits, cand.amount_cents, create_missing_categories, result
        )
        if items is None:
            return
        # Ensure splits sum to total; if not, surface as error.
        s_total = sum(i.amount_cents for i in items)
        if s_total != cand.amount_cents:
            result.errors.append(
                f"splits sum {s_total} != amount {cand.amount_cents} "
                f"for candidate quicken_id={cand.quicken_id}"
            )
            return
        for i in items:
            i.transaction_id = txn.id
            session.add(i)
        if len(items) > 1:
            txn.status = "split"
    else:
        uncat = await _get_or_create_uncategorized(session)
        session.add(
            LineItem(
                transaction_id=txn.id,
                category_id=uncat.id,
                amount_cents=cand.amount_cents,
                description=cand.description,
            )
        )
    result.created_ids.append(txn.id)


async def _merge_candidate(
    session: AsyncSession,
    cand: TransactionCandidate,
    target_id: int,
    result: ConfirmResult,
    create_missing_categories: bool,
) -> None:
    target = await session.get(Transaction, target_id)
    if target is None:
        result.errors.append(f"merge target {target_id} not found")
        return
    # Annotate the bank source onto our manual receipt-entered txn.
    if cand.quicken_id and not target.quicken_id:
        target.quicken_id = cand.quicken_id
    target.status = "final"  # Quicken-confirmed
    result.merged_ids.append(target.id)


async def _get_or_create_uncategorized(session: AsyncSession) -> Category:
    result = await session.execute(
        select(Category).where(Category.name == "Uncategorized")
    )
    cat = result.scalar_one_or_none()
    if cat is None:
        cat = Category(name="Uncategorized")
        session.add(cat)
        await session.flush()
    return cat


# ──────────────────────────────────────────────────────────────────────────────
# QIF export
# ──────────────────────────────────────────────────────────────────────────────


async def export_qif(
    session: AsyncSession,
    transaction_ids: list[int],
    account: Account,
) -> str:
    """Emit a QIF document for the given transactions belonging to ``account``.

    Format produced::

        !Account
        N<account name>
        T<account type>
        ^
        !Type:Bank
        D05/19/2026
        T-50.00
        PCostco
        LFood:Groceries
        SFood:Groceries
        $-30.00
        SHousehold
        $-20.00
        ^

    Categories use the full colon path (Quicken's native convention).
    """
    cats = await _all_categories(session)
    by_id = {c.id: c for c in cats}

    def path_for_category(cat_id: int) -> str:
        parts: list[str] = []
        cur: Category | None = by_id.get(cat_id)
        while cur is not None:
            parts.append(cur.name)
            cur = by_id.get(cur.parent_id) if cur.parent_id else None
        return ":".join(reversed(parts))

    out: list[str] = []
    out.append("!Account")
    out.append(f"N{account.name}")
    out.append(f"T{_qif_account_type(account.type)}")
    out.append("^")
    out.append(f"!Type:{_qif_account_type(account.type)}")

    if transaction_ids:
        txns_result = await session.execute(
            select(Transaction)
            .where(Transaction.id.in_(transaction_ids))
            .order_by(Transaction.posted_at)
        )
        txns = list(txns_result.scalars().all())
    else:
        txns = []

    for txn in txns:
        items_result = await session.execute(
            select(LineItem).where(LineItem.transaction_id == txn.id).order_by(LineItem.id)
        )
        items = list(items_result.scalars().all())

        out.append(f"D{txn.posted_at.strftime('%m/%d/%Y')}")
        out.append(f"T{_cents_to_amount(txn.amount_cents)}")
        if txn.description:
            out.append(f"P{txn.description}")
        if txn.merchant and txn.merchant.name and not txn.description:
            out.append(f"P{txn.merchant.name}")
        if txn.quicken_id:
            out.append(f"N{txn.quicken_id}")
        # Primary L line so single-line Quicken importers see a category.
        if items:
            out.append(f"L{path_for_category(items[0].category_id)}")
        # Always emit splits when there are 2+, and also emit a single split for
        # 1-item txns so that re-importing round-trips structure faithfully.
        for li in items:
            out.append(f"S{path_for_category(li.category_id)}")
            if li.description:
                out.append(f"E{li.description}")
            out.append(f"${_cents_to_amount(li.amount_cents)}")
        out.append("^")

    return "\n".join(out) + "\n"


def _qif_account_type(internal: str) -> str:
    """Map our account.type to a QIF !Type header.

    Anything we don't know about lands on "Bank" which is the safest default
    for Quicken to accept on import.
    """
    t = internal.lower()
    if t in ("checking", "savings", "bank"):
        return "Bank"
    if t in ("credit", "credit_card", "creditcard"):
        return "CCard"
    if t in ("cash",):
        return "Cash"
    if t in ("investment", "brokerage"):
        return "Invst"
    return "Bank"
