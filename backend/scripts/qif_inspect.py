"""Inspect a QIF file locally — no data leaves your machine.

Usage:
    python scripts/qif_inspect.py path/to/export.qif
    python scripts/qif_inspect.py path/to/export.qif --show-errors --show-categories --show-memorized
    python scripts/qif_inspect.py path/to/brokerage.qif --investments
"""

import asyncio
import argparse
import csv
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from finance.models import Base
from finance.services.quicken import import_qif


# ── Investment inspection (raw scan, bypasses import_qif) ────────────────────
#
# import_qif() routes !Type:Invst / !Type:Security / !Type:Prices into a
# "security" section and drops every record without recording an error, so
# running a brokerage QIF through it reports zero of everything. This scan
# reads the file directly so we can see what is actually in there.

# QIF investment action code -> the action vocabulary in
# docs/PLAN_INVESTMENTS.md §2.2. None means "recognised but no mapping decided".
QIF_ACTION_MAP: dict[str, str | None] = {
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
    "miscinc": "interest",
    "miscincx": "interest",
    "miscexp": "fee",
    "miscexpx": "fee",
    "margint": "fee",
    "marginx": "fee",
    "shrsin": "shares_in",
    "shrsout": "shares_out",
    "xin": "cash_in",
    "xout": "cash_out",
    "contribx": "cash_in",
    "withdrwx": "cash_out",
    "cash": "cash_in",
    "stksplit": "split",
    "rtrncap": "return_of_capital",
    "rtrncapx": "return_of_capital",
    "shtsell": None,
    "cvrshrt": None,
    "grant": None,
    "vest": None,
    "exercise": None,
    "exercisx": None,
    "expire": None,
    "reminder": None,
}


def _fmt_date_range(dates: list[str]) -> str:
    if not dates:
        return "none"
    parsed = sorted(d for d in dates if d)
    if not parsed:
        return "none"
    return f"{parsed[0]} -> {parsed[-1]}  ({len(parsed)} dated records)"


def _norm_qif_date(raw: str) -> str:
    """Best-effort MM/DD/YY' -> ISO. Returns '' if unrecognised.

    Two-digit years pivot at 69 to match ``%y`` in
    ``finance.services.quicken._parse_qif_date`` — a diagnostic that disagrees
    with the real parser is worse than no diagnostic. Three-digit years are the
    old ``tm_year`` form (100 == 2000) that Quicken and MS Money emitted around
    the millennium.
    """
    s = raw.strip().replace("'", "/").replace(" ", "")
    parts = [p for p in s.split("/") if p]
    if len(parts) != 3:
        return ""
    try:
        m, d, y = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return ""
    if y < 69:
        y += 2000
    elif y < 200:
        y += 1900
    if not 1900 <= y <= 2100:
        return ""
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return ""


def scan_investments(text: str, verbose: bool = False) -> None:
    section = None
    record: dict[str, str] = {}

    securities: list[dict[str, str]] = []
    prices: list[tuple[str, str, str]] = []
    invst: list[dict[str, str]] = []
    accounts: list[tuple[str, str]] = []
    bad_price_rows = 0

    def flush() -> None:
        nonlocal record
        if record:
            if section == "security":
                securities.append(record)
            elif section == "invst":
                invst.append(record)
            elif section == "account":
                accounts.append((record.get("N", ""), record.get("T", "")))
        record = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("!"):
            header = line[1:].strip().lower()
            # Match import_qif: the AutoSwitch markers are not section changes.
            if header in ("option:autoswitch", "clear:autoswitch"):
                continue
            flush()
            if header.startswith("account"):
                section = "account"
            elif header.startswith("type:security"):
                section = "security"
            elif header.startswith("type:prices"):
                section = "prices"
            elif header.startswith("type:invst"):
                section = "invst"
            else:
                section = "other:" + header
            continue

        if line == "^":
            flush()
            continue

        if section == "prices":
            # "SYM",price,"MM/DD/YY" — csv.reader so a quoted thousands
            # separator ("1,234.56") does not shift every field right.
            try:
                parts = next(csv.reader([line]))
            except (csv.Error, StopIteration):
                bad_price_rows += 1
                continue
            parts = [p.strip() for p in parts]
            if len(parts) >= 3 and parts[0]:
                prices.append((parts[0], parts[1], _norm_qif_date(parts[-1])))
            else:
                bad_price_rows += 1
            continue

        record[line[0]] = line[1:]

    flush()

    print("\n── Investment content (raw scan) ──")

    # "Oth A"/"Oth L" are Other Asset/Liability, not investment accounts.
    invst_accounts = [
        (n, t) for n, t in accounts if t.strip().lower() in ("invst", "invest", "port")
    ]
    if accounts:
        print(f"  !Account blocks:     {len(accounts)}  (investment-typed: {len(invst_accounts)})")
        if verbose:
            for n, t in accounts:
                print(f"    {n}  [T{t}]")

    print(f"  !Type:Security:      {len(securities)}")
    print(f"  !Type:Prices rows:   {len(prices)}")
    print(f"  !Type:Invst records: {len(invst)}")

    if not (securities or prices or invst):
        print("\n  No investment content found in this file.")
        print("  If this account has holdings in Quicken, re-export with")
        print("  'Investment transactions', 'Security lists' and 'Prices' checked.")
        return

    if securities:
        print(f"\n  ── Securities ({len(securities)}) ──")
        by_type: dict[str, int] = {}
        for s in securities:
            stype = s.get("T") or "(untyped)"
            by_type[stype] = by_type.get(stype, 0) + 1
        for t, n in sorted(by_type.items(), key=lambda kv: -kv[1]):
            print(f"    {t:<24} {n}")
        missing_symbol = [s for s in securities if not s.get("S")]
        if missing_symbol:
            print(
                f"    ! {len(missing_symbol)} security(ies) have no ticker symbol"
                f" — will need manual mapping for benchmark comparison"
            )
        if verbose:
            for s in securities:
                print(f"    {s.get('S', '(no sym)'):<10} {s.get('N', '')}  [{s.get('T', '')}]")

    if prices:
        syms = sorted({p[0] for p in prices})
        dates = [p[2] for p in prices]
        print(f"\n  ── Prices ({len(prices)} rows, {len(syms)} symbols) ──")
        print(f"    date range: {_fmt_date_range(dates)}")
        print(f"    symbols:    {', '.join(syms[:12])}{' …' if len(syms) > 12 else ''}")
        undated_prices = sum(1 for d in dates if not d)
        if undated_prices:
            print(f"    ! {undated_prices} price row(s) have an unparseable date")

    if bad_price_rows:
        print(f"\n  ! {bad_price_rows} price row(s) were malformed and skipped")

    if invst:
        print(f"\n  ── Investment transactions ({len(invst)}) ──")
        dates = [_norm_qif_date(r.get("D", "")) for r in invst]
        print(f"    date range: {_fmt_date_range(dates)}")

        by_action: dict[str, int] = {}
        for r in invst:
            action = r.get("N") or "(no action)"
            by_action[action] = by_action.get(action, 0) + 1

        unmapped, unmappable = [], []
        print(f"\n    {'QIF action':<16} {'count':>6}  maps to")
        print(f"    {'-' * 16} {'-' * 6}  {'-' * 24}")
        for action, count in sorted(by_action.items(), key=lambda kv: -kv[1]):
            key = action.strip().lower()
            if key in QIF_ACTION_MAP:
                target = QIF_ACTION_MAP[key]
                if target is None:
                    label = "RECOGNISED, no mapping"
                    unmappable.append(action)
                else:
                    label = target
            else:
                label = "*** UNKNOWN ***"
                unmapped.append(action)
            print(f"    {action:<16} {count:>6}  {label}")

        securities_used = {r.get("Y", "") for r in invst if r.get("Y")}
        print(f"\n    distinct securities referenced: {len(securities_used)}")
        with_qty = sum(1 for r in invst if r.get("Q"))
        with_price = sum(1 for r in invst if r.get("I"))
        with_amount = sum(1 for r in invst if r.get("T") or r.get("U"))
        # L holds a category for MiscExp/MiscInc; only the X-suffixed actions
        # put a transfer account there, written as [Account Name].
        with_xfer = sum(1 for r in invst if r.get("L", "").startswith("["))
        with_category = sum(1 for r in invst if r.get("L") and not r["L"].startswith("["))
        print(f"    records with quantity (Q):      {with_qty}")
        print(f"    records with price (I):         {with_price}")
        print(f"    records with amount (T/U):      {with_amount}")
        print(f"    records with transfer acct (L): {with_xfer}")
        print(f"    records with category (L):      {with_category}")

        if unmapped:
            print("\n    ! UNKNOWN action codes — plan §4.2 needs extending:")
            print(f"      {', '.join(sorted(set(unmapped)))}")
        if unmappable:
            print("\n    ! Recognised but unmapped (options/equity comp, plan §7 out-of-scope):")
            print(f"      {', '.join(sorted(set(unmappable)))}")

        undated = sum(1 for d in dates if not d)
        if undated:
            print(f"\n    ! {undated} record(s) have an unparseable date")

    print("\n  Verdict:", end=" ")
    if invst:
        print("QIF path is viable — transaction-level detail is present.")
        print("  Next: plan §4.2 (parse investment blocks). Phase 3 scope is parsing only.")
    elif securities or prices:
        print("securities/prices only, NO transactions.")
        print("  Next: plan §4.1 (manual statement entry) is the primary path;")
        print("  basis must come from statement lots, not replayed transactions.")


def _decode_qif(data: bytes) -> str:
    """Quicken writes cp1252; naive UTF-8 decoding is what mangles '\u00ae' in
    account names (see docs/PLAN_INVESTMENTS.md F7).

    utf-8-sig strips a BOM if present and is otherwise identical to utf-8.
    Without it, a BOM'd file leaves \ufeff on line 1, the leading "!Type:"
    header is not recognised, and every record before the next header is lost.
    latin-1 maps all 256 byte values and never raises, so the loop terminates.
    """
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise AssertionError("unreachable: latin-1 decodes any byte string")


async def inspect(path: Path, args: argparse.Namespace) -> None:
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        data = path.read_bytes()
        result = await import_qif(data, session)

    print(f"File: {path.name} ({len(data):,} bytes)")
    print(f"Transactions:     {len(result.candidates)}")
    print(f"Categories:       {len(result.categories)}")
    print(f"Memorized rules:  {len(result.memorized_rules)}")
    print(f"Unmapped accounts:{len(result.unmapped_accounts)}")
    print(f"Parse errors:     {len(result.errors)}")

    if result.unmapped_accounts:
        print(f"\nUnmapped accounts: {', '.join(result.unmapped_accounts)}")

    if args.show_errors and result.errors:
        print("\n── Errors ──")
        for e in result.errors:
            print(f"  {e}")

    if args.show_categories and result.categories:
        print(f"\n── Categories ({len(result.categories)}) ──")
        income = [c for c in result.categories if c.is_income]
        expense = [c for c in result.categories if not c.is_income]
        tax = [c for c in result.categories if c.tax_related]
        print(f"  Income: {len(income)}  Expense: {len(expense)}  Tax-related: {len(tax)}")
        if args.verbose:
            for c in result.categories:
                flags = []
                if c.is_income:
                    flags.append("income")
                if c.tax_related:
                    flags.append(f"tax:{c.tax_schedule or '?'}")
                suffix = f"  [{', '.join(flags)}]" if flags else ""
                print(f"    {c.name}{suffix}")

    if args.show_memorized and result.memorized_rules:
        print(f"\n── Memorized Rules ({len(result.memorized_rules)}) ──")
        by_kind = {}
        for r in result.memorized_rules:
            by_kind.setdefault(r.kind, []).append(r)
        for kind, rules in sorted(by_kind.items()):
            print(f"  {kind}: {len(rules)}")
        transfers = [r for r in result.memorized_rules if r.transfer_account]
        if transfers:
            print(f"  (of which {len(transfers)} are account transfers)")
        if args.verbose:
            for r in result.memorized_rules:
                cat = f"[{r.transfer_account}]" if r.transfer_account else r.category_path
                amt = f"  ${r.amount_cents / 100:.2f}" if r.amount_cents is not None else ""
                print(f"    {r.payee} -> {cat}{amt}  ({r.kind})")

    if args.show_transactions:
        print(f"\n── Transactions ({len(result.candidates)}) ──")
        cleared_counts = {"X": 0, "*": 0, None: 0}
        xfer_count = 0
        split_count = 0
        for c in result.candidates:
            cleared_counts[c.cleared] = cleared_counts.get(c.cleared, 0) + 1
            if c.transfer_account:
                xfer_count += 1
            if len(c.splits) > 1:
                split_count += 1
        print(f"  Reconciled (X): {cleared_counts.get('X', 0)}")
        print(f"  Cleared (*):    {cleared_counts.get('*', 0)}")
        print(f"  Uncleared:      {cleared_counts.get(None, 0)}")
        print(f"  Transfers:      {xfer_count}")
        print(f"  Multi-split:    {split_count}")

    if args.investments:
        scan_investments(_decode_qif(data), verbose=args.verbose)

    await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description="Inspect a QIF file locally")
    parser.add_argument("file", type=Path, help="Path to QIF file")
    parser.add_argument("--show-errors", action="store_true", help="Print parse errors")
    parser.add_argument("--show-categories", action="store_true", help="Print category summary")
    parser.add_argument(
        "--show-memorized", action="store_true", help="Print memorized rules summary"
    )
    parser.add_argument("--show-transactions", action="store_true", help="Print transaction stats")
    parser.add_argument(
        "--investments",
        action="store_true",
        help="Scan raw !Type:Invst/Security/Prices blocks (bypasses import_qif)",
    )
    parser.add_argument("--all", action="store_true", help="Show everything")
    parser.add_argument("--verbose", "-v", action="store_true", help="List individual items")
    args = parser.parse_args()

    if args.all:
        args.show_errors = args.show_categories = args.show_memorized = True
        args.show_transactions = args.investments = True

    if not args.file.exists():
        print(f"File not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    asyncio.run(inspect(args.file, args))


if __name__ == "__main__":
    main()
