"""One-off: give every Account a real ``type``.

Every account in the database was created as ``checking`` (the QIF import path
hardcodes it), including credit cards, loans, and all thirteen investment
accounts. ``INVESTMENT_ACCOUNT_TYPES`` cannot exclude anything until this is
fixed — see docs/PLAN_INVESTMENTS.md F6 and ADR 0006.

Source of truth is the ``!Account`` block in a Quicken QIF export, which carries
Quicken's own type letter. Accounts absent from the export fall back to a
name-based guess, and anything still unresolved is reported rather than guessed.

Usage (from backend/):
    .venv/bin/python -m finance.scripts.retype_accounts EXPORT.QIF            # dry run
    .venv/bin/python -m finance.scripts.retype_accounts EXPORT.QIF --apply
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

from sqlalchemy import select

from finance.db import async_session_factory
from finance.models.account import Account
from finance.services.account import ACCOUNT_TYPES, INVESTMENT_ACCOUNT_TYPES

# Quicken's !Account T<type> letter -> our vocabulary. "Port" and "Invst" both
# mean a securities account but not which tax wrapper, so they resolve by name.
QUICKEN_TYPE_MAP: dict[str, str] = {
    "bank": "checking",
    "cash": "cash",
    "ccard": "credit",
    "oth a": "asset",
    "oth l": "loan",
    # Quicken writes a 0x01 control byte, not a letter, for liability accounts
    # (every loan and the mortgage in the real export). Refined by name below.
    "\x01": "loan",
    "401(k)/403(b)": "401k",
    "invst": "brokerage",
    "port": "brokerage",
}

# Applied to the account NAME, in order, for securities accounts (and for any
# account missing from the export). First match wins.
NAME_RULES: list[tuple[str, str]] = [
    (r"\broth\b", "roth_ira"),
    (r"\b(401\s*\(?k\)?|403\s*\(?b\)?)\b", "401k"),
    (r"\b529\b|brightstart", "529"),
    (r"\bhsa\b|health savings", "hsa"),
    (r"\bira\b|contributory", "ira"),
    (r"cash management|brokerage|individual - tod", "brokerage"),
    (r"\bmortgage\b", "mortgage"),
    (r"\bloan\b|direct grad|direct loan|subsidized", "loan"),
    (r"\bsavings\b|\bcd\d|\bmembership\b", "savings"),
    (r"\bchecking\b", "checking"),
    (r"visa|card|credit", "credit"),
]


def parse_account_types(qif_text: str) -> dict[str, str]:
    """name -> Quicken type letter, from !Account blocks."""
    out: dict[str, str] = {}
    section = None
    name = qtype = ""
    for raw in qif_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("!"):
            header = line[1:].strip().lower()
            if header in ("option:autoswitch", "clear:autoswitch"):
                continue
            section = "account" if header.startswith("account") else "other"
            name = qtype = ""
            continue
        if line == "^":
            if section == "account" and name:
                out[name] = qtype
            name = qtype = ""
            continue
        if section == "account":
            if line[0] == "N":
                name = line[1:]
            elif line[0] == "T":
                qtype = line[1:]
    return out


def guess_from_name(name: str) -> str | None:
    low = name.lower()
    for pattern, account_type in NAME_RULES:
        if re.search(pattern, low):
            return account_type
    return None


def resolve(name: str, quicken_type: str | None) -> tuple[str | None, str]:
    """Return (account_type, reason). None means unresolved — report, don't guess."""
    qt = (quicken_type or "").strip().lower()
    mapped = QUICKEN_TYPE_MAP.get(qt)

    # Securities accounts: Quicken says "it holds securities", the name says
    # which tax wrapper, and the wrapper is what matters for lot terms.
    if mapped == "brokerage":
        guessed = guess_from_name(name)
        if guessed in INVESTMENT_ACCOUNT_TYPES:
            return guessed, f"Quicken T{quicken_type} + name"
        return "brokerage", f"Quicken T{quicken_type}"

    if mapped:
        # Quicken's coarse types split further by name: Bank is checking or
        # savings, and a liability is a loan or a mortgage.
        refine = {"checking": ("savings", "checking"), "loan": ("loan", "mortgage")}
        if mapped in refine:
            guessed = guess_from_name(name)
            if guessed in refine[mapped]:
                label = "T\\x01" if qt == "\x01" else f"T{quicken_type}"
                return guessed, f"Quicken {label} + name"
        return mapped, f"Quicken T{quicken_type}"

    # No type letter in the export (Quicken writes loans with an empty T line),
    # or the account is not in the export at all.
    guessed = guess_from_name(name)
    if guessed:
        return guessed, "name" if not qt else f"name (Quicken T{quicken_type!r} unmapped)"
    return None, f"UNRESOLVED (Quicken T{quicken_type!r})"


async def main() -> int:
    parser = argparse.ArgumentParser(description="Set Account.type from a Quicken QIF export")
    parser.add_argument("qif", type=Path, nargs="?", help="QIF export with !Account blocks")
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry run)")
    args = parser.parse_args()

    quicken_types: dict[str, str] = {}
    if args.qif:
        if not args.qif.exists():
            print(f"File not found: {args.qif}", file=sys.stderr)
            return 1
        data = args.qif.read_bytes()
        for encoding in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                text = data.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        quicken_types = parse_account_types(text)
        print(f"Read {len(quicken_types)} account blocks from {args.qif.name}\n")

    async with async_session_factory() as session:
        accounts = list((await session.execute(select(Account).order_by(Account.name))).scalars())

        changes: list[tuple[Account, str, str]] = []
        unresolved: list[tuple[Account, str]] = []
        for account in accounts:
            new_type, reason = resolve(account.name, quicken_types.get(account.name))
            if new_type is None:
                unresolved.append((account, reason))
            elif new_type != account.type:
                changes.append((account, new_type, reason))

        width = max((len(a.name) for a in accounts), default=10)
        for account, new_type, reason in changes:
            flag = " *" if new_type in INVESTMENT_ACCOUNT_TYPES else "  "
            print(f"{flag}{account.name:<{width}}  {account.type:>10} -> {new_type:<10}  ({reason})")

        if unresolved:
            print("\nUNRESOLVED — set these by hand:")
            for account, reason in unresolved:
                print(f"  {account.name:<{width}}  {reason}")

        invest = sum(1 for _, t, _ in changes if t in INVESTMENT_ACCOUNT_TYPES)
        print(
            f"\n{len(changes)} change(s), {invest} investment account(s) marked *, "
            f"{len(unresolved)} unresolved, {len(accounts)} total"
        )

        bad = [t for _, t, _ in changes if t not in ACCOUNT_TYPES]
        if bad:
            print(f"ERROR: produced types outside the vocabulary: {sorted(set(bad))}", file=sys.stderr)
            return 1

        if not args.apply:
            print("\nDry run. Re-run with --apply to write.")
            return 0

        for account, new_type, _ in changes:
            account.type = new_type
        await session.commit()
        print(f"\nApplied {len(changes)} change(s).")
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
