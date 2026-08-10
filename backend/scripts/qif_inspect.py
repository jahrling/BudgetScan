"""Inspect a QIF file locally — no data leaves your machine.

Usage:
    python scripts/qif_inspect.py path/to/export.qif
    python scripts/qif_inspect.py path/to/export.qif --show-errors --show-categories --show-memorized
"""

import asyncio
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from finance.models import Base
from finance.services.quicken import import_qif


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

    await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description="Inspect a QIF file locally")
    parser.add_argument("file", type=Path, help="Path to QIF file")
    parser.add_argument("--show-errors", action="store_true", help="Print parse errors")
    parser.add_argument("--show-categories", action="store_true", help="Print category summary")
    parser.add_argument("--show-memorized", action="store_true", help="Print memorized rules summary")
    parser.add_argument("--show-transactions", action="store_true", help="Print transaction stats")
    parser.add_argument("--all", action="store_true", help="Show everything")
    parser.add_argument("--verbose", "-v", action="store_true", help="List individual items")
    args = parser.parse_args()

    if args.all:
        args.show_errors = args.show_categories = args.show_memorized = args.show_transactions = True

    if not args.file.exists():
        print(f"File not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    asyncio.run(inspect(args.file, args))


if __name__ == "__main__":
    main()
