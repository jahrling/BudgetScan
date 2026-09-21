"""Find probable duplicate account pairs and report what merging would touch.

For each candidate pair, shows: account names, types, IDs, and row counts in
every table that references accounts.id (transactions, investment_transactions,
lots, position_snapshots, statement_scans).  Also flags when both accounts have
rows in the same table — those need FK reassignment before the empty one can
be deleted.

Usage (inside the backend container):
    python -m finance.scripts.find_duplicate_accounts             # report only
    python -m finance.scripts.find_duplicate_accounts --merge      # dry run
    python -m finance.scripts.find_duplicate_accounts --merge --apply  # execute
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys

from sqlalchemy import func, select, update

from finance.db import async_session_factory
from finance.models.account import Account
from finance.models.investment_transaction import InvestmentTransaction
from finance.models.lot import Lot
from finance.models.position_snapshot import PositionSnapshot
from finance.models.statement_scan import StatementScan
from finance.models.transaction import Transaction


def _extract_account_numbers(name: str) -> set[str]:
    """Pull Quicken-style account suffixes: XX1234, XXXXX988, ...217."""
    nums: set[str] = set()
    for m in re.finditer(r"(?:XX|XXXXX|\.\.\.)\s*(\d{3,})", name):
        nums.add(m.group(1))
    return nums


def _name_tokens(name: str) -> set[str]:
    """Meaningful words from an account name, after stripping numbers and noise."""
    s = name.lower()
    s = re.sub(r"(?:xx|xxxxx|\.\.\.)?\s*\d+", "", s)
    s = re.sub(r"[^a-z]+", " ", s)
    tokens = set(s.split())
    tokens -= {"the", "a", "an", "of", "and", "inc", "co", "corp"}
    return tokens


def _numbers_overlap(a_nums: set[str], b_nums: set[str]) -> set[str]:
    """Check for shared account numbers, allowing truncation (XX297 vs XX2970)."""
    shared: set[str] = a_nums & b_nums
    for a_n in a_nums:
        for b_n in b_nums:
            if a_n != b_n and (a_n.startswith(b_n) or b_n.startswith(a_n)):
                shared.add(f"{min(a_n, b_n, key=len)}*")
    return shared


def _token_similarity(a: set[str], b: set[str]) -> float:
    """Jaccard similarity of two token sets."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# Also match abbreviated company names: if the shorter name's tokens are all
# present as prefixes of the longer name's tokens, that's a match.
def _prefix_match(shorter: set[str], longer: set[str]) -> bool:
    """True if every token in `shorter` is a prefix of some token in `longer`."""
    if not shorter:
        return False
    for s_tok in shorter:
        if not any(l_tok.startswith(s_tok) for l_tok in longer):
            return False
    return True


def find_candidates(accounts: list[Account]) -> list[tuple[Account, Account, str]]:
    """Return (keep, merge, reason) triples for probable duplicates.

    Reports all plausible matches — the user decides which are real via
    --merge with explicit pair IDs.
    """
    pairs: list[tuple[Account, Account, str]] = []
    seen: set[int] = set()

    for i, a in enumerate(accounts):
        if a.id in seen:
            continue
        a_nums = _extract_account_numbers(a.name)
        a_toks = _name_tokens(a.name)
        for b in accounts[i + 1 :]:
            if b.id in seen:
                continue
            if a.type != b.type:
                continue
            b_nums = _extract_account_numbers(b.name)
            b_toks = _name_tokens(b.name)

            shared_nums = _numbers_overlap(a_nums, b_nums)
            sim = _token_similarity(a_toks, b_toks)
            shorter, longer = (a_toks, b_toks) if len(a_toks) <= len(b_toks) else (b_toks, a_toks)
            prefix = _prefix_match(shorter, longer) and len(shorter) >= 2

            if shared_nums:
                reason = f"shared account number(s): {', '.join(sorted(shared_nums))}"
            elif sim >= 0.6 or (prefix and sim >= 0.4):
                reason = f"name similarity ({sim:.0%}, prefix_match={prefix})"
            else:
                continue
            pairs.append((a, b, reason))
            seen.update((a.id, b.id))
    return pairs


def _redact(name: str) -> str:
    """Replace account numbers with XX*** for safe display."""
    s = re.sub(r"(XX|XXXXX)\d{3,}", r"\1***", name)
    s = re.sub(r"\.\.\.\d{3,}", "...***", s)
    s = re.sub(r"\b\d{5,}\b", "***", s)
    return s


def _redact_reason(reason: str) -> str:
    """Strip actual digits from match reasons."""
    return re.sub(r"\d{3,}", "***", reason)


FK_TABLES = [
    ("transactions", Transaction),
    ("investment_transactions", InvestmentTransaction),
    ("lots", Lot),
    ("position_snapshots", PositionSnapshot),
    ("statement_scans", StatementScan),
]


async def count_rows(session, model, account_id: int) -> int:
    result = await session.execute(
        select(func.count()).where(model.account_id == account_id)
    )
    return result.scalar_one()


async def main() -> int:
    parser = argparse.ArgumentParser(description="Find and optionally merge duplicate accounts")
    parser.add_argument("--merge", action="store_true", help="Reassign rows from the emptier account to the other")
    parser.add_argument("--pairs", nargs="+", metavar="KEEP,MERGE",
                        help="Only merge these pairs (e.g. --pairs 41,40 30,31 32,35 34,36)")
    parser.add_argument("--apply", action="store_true", help="Actually write changes (default: dry run)")
    args = parser.parse_args()

    async with async_session_factory() as session:
        accounts = list(
            (await session.execute(select(Account).order_by(Account.type, Account.name))).scalars()
        )
        pairs = find_candidates(accounts)

        if not pairs:
            print("No duplicate candidates found.")
            return 0

        print(f"Found {len(pairs)} probable duplicate pair(s):\n")
        print("=" * 90)

        merges: list[tuple[Account, Account]] = []

        for keep, merge, reason in pairs:
            keep_counts: dict[str, int] = {}
            merge_counts: dict[str, int] = {}
            for label, model in FK_TABLES:
                keep_counts[label] = await count_rows(session, model, keep.id)
                merge_counts[label] = await count_rows(session, model, merge.id)

            keep_total = sum(keep_counts.values())
            merge_total = sum(merge_counts.values())

            if merge_total > keep_total or (
                merge_total == keep_total and len(merge.name) > len(keep.name)
            ):
                keep, merge = merge, keep
                keep_counts, merge_counts = merge_counts, keep_counts
                keep_total, merge_total = merge_total, keep_total

            keep_label = _redact(keep.name)
            merge_label = _redact(merge.name)
            print(f"\n  KEEP  (id={keep.id:>3})  {keep_label}")
            print(f"  MERGE (id={merge.id:>3})  {merge_label}")
            print(f"  Type: {keep.type}  |  Reason: {_redact_reason(reason)}")
            print()
            print(f"  {'table':<25} {'KEEP':>8} {'MERGE':>8}  notes")
            print(f"  {'-'*25} {'-'*8} {'-'*8}  {'-'*20}")
            for label, _ in FK_TABLES:
                kc = keep_counts[label]
                mc = merge_counts[label]
                note = ""
                if kc > 0 and mc > 0:
                    note = "<-- BOTH HAVE ROWS"
                elif mc > 0:
                    note = "<-- reassign to KEEP"
                print(f"  {label:<25} {kc:>8} {mc:>8}  {note}")
            print(f"  {'TOTAL':<25} {keep_total:>8} {merge_total:>8}")
            print()

            merges.append((keep, merge))

        print("=" * 90)

        if not args.merge:
            print("\nReport only. Re-run with --merge for a dry run of the merge.")
            return 0

        if args.pairs:
            requested: set[tuple[int, int]] = set()
            for spec in args.pairs:
                parts = spec.split(",")
                if len(parts) != 2 or not all(p.isdigit() for p in parts):
                    print(f"ERROR: bad --pairs value {spec!r}, expected KEEP_ID,MERGE_ID", file=sys.stderr)
                    return 1
                requested.add((int(parts[0]), int(parts[1])))
            filtered: list[tuple[Account, Account]] = []
            for keep, merge in merges:
                if (keep.id, merge.id) in requested:
                    filtered.append((keep, merge))
                    requested.discard((keep.id, merge.id))
            if requested:
                print(f"WARNING: these pairs were not found in candidates: {requested}", file=sys.stderr)
            merges = filtered

        if not merges:
            print("No pairs selected for merge.")
            return 0

        print("\n--- Merge plan ---\n")
        for keep, merge in merges:
            print(f"  {_redact(merge.name)} (id={merge.id}) -> {_redact(keep.name)} (id={keep.id})")
            for label, model in FK_TABLES:
                mc = await count_rows(session, model, merge.id)
                if mc > 0:
                    print(f"    UPDATE {label} SET account_id={keep.id} WHERE account_id={merge.id}  ({mc} rows)")
            print(f"    DELETE accounts WHERE id={merge.id}")

        if not args.apply:
            print("\nDry run. Re-run with --merge --apply to execute.")
            return 0

        for keep, merge in merges:
            for label, model in FK_TABLES:
                mc = await count_rows(session, model, merge.id)
                if mc > 0:
                    await session.execute(
                        update(model).where(model.account_id == merge.id).values(account_id=keep.id)
                    )
                    print(f"  Reassigned {mc} {label} rows: {merge.id} -> {keep.id}")
            await session.delete(merge)
            print(f"  Deleted account {merge.id} ({_redact(merge.name)})")

        await session.commit()
        print(f"\nMerged {len(merges)} pair(s).")
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
