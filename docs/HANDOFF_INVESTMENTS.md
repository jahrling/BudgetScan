# Handoff — Investments section, resuming at Phase 1 (part 2)

Paste the block below into a fresh `claude` session started from the repo root.

---

We're building the Investments section of BudgetScan, following `docs/PLAN_INVESTMENTS.md`.
Read that plan first — especially §9, which holds the Phase 0 findings and the
decisions already taken. Then read `docs/adr/0006-investments-separate-domain.md`.
Don't scan the rest of the repo; `ARCHITECTURE.md` tells you where things live.

Work is on the `investments` branch, three commits in, nothing pushed. Phase 0 is
complete and Phase 1 is about half done.

## What already exists (don't rebuild it)

- `docs/PLAN_INVESTMENTS.md` — the full plan. §9 has findings F1-F13 and decisions
  D1-D8. §8 has the phase table.
- `docs/adr/0006-investments-separate-domain.md` — why investments are a separate
  table family rather than reusing Transaction/LineItem.
- Seven models in `backend/src/finance/models/`: `security.py` (Security,
  PriceHistory), `investment_transaction.py`, `position_snapshot.py`, `lot.py`
  (Lot, LotDisposal), `investment_settings.py`. All registered in `models/__init__.py`.
- Migration `backend/alembic/versions/i9j0k1l2m3n4_create_investment_tables.py`.
  Verified against a copy of the live DB: 7 tables created, 5885 transactions and
  44 accounts preserved, downgrade clean, and every column/type/nullable/unique/FK
  matches the model metadata.
- `backend/src/finance/schemas/investment.py` — Read/Create/Update DTOs, registered
  in `schemas/__init__.py`.
- `backend/src/finance/services/account.py` — `ACCOUNT_TYPES`,
  `INVESTMENT_ACCOUNT_TYPES`, `TAX_ADVANTAGED_ACCOUNT_TYPES`, `is_investment_type()`,
  and `excludes_investment_accounts()` (a correlated-subquery WHERE clause).
- `backend/src/finance/scripts/retype_accounts.py` — one-off retype driven by
  Quicken's `!Account` type letters. Dry run against real data retypes 40 of 44
  accounts, classifies all 13 investment accounts, 0 unresolved. **Not yet applied
  to the live database.**
- `backend/scripts/qif_inspect.py --investments` — raw QIF investment scanner.

## Your environment

The user does **not** have `uv` installed. Use `backend/.venv/bin/python` and
`backend/.venv/bin/ruff` directly. Tests: `cd backend && .venv/bin/python -m pytest -q`
(118 passing). There are 20 pre-existing ruff errors in files unrelated to this
work — don't fix them, and don't let them mask new ones; lint only the files you touch.

Real Quicken exports are in `backend/data/investments/` (gitignored). The live
database is in Docker volume `budgetscan_db-data`, reachable via
`docker exec budgetscan-backend-1`. The `deploy-*` containers are a different,
near-empty stack — ignore them.

## Finish Phase 1

1. Wire `excludes_investment_accounts()` into the 9 query sites that currently
   filter only on `Transaction.excluded.is_(None)`:
   `services/budget.py` lines 143, 209, 264, 321, 336, 368, 446 and
   `services/aggregation.py` lines 88, 129. Line numbers are from commit 8e3eb40.
2. Add `backend/src/finance/tests/test_investments.py` covering: the account-type
   vocabulary is closed and the two subsets don't overlap; a transaction on a
   `brokerage` account is excluded from budget status, spend-by-category, and
   total spend, while an identical one on `checking` is included; `resolve()` in
   the retype script maps Quicken's Bank/CCard/Oth A/Port/Invst/401(k)/0x01 types
   correctly and returns None rather than guessing when it can't tell.
3. Run `pytest`, lint only your files, then the `code-reviewer` subagent, then
   commit to `investments`. Don't push without asking.

## Then Phase 2 (the part that matters most)

`services/investment_math.py` (pure functions, no DB) and `services/lot_engine.py`,
per plan §3. Every formula gets a hand-checkable unit test **before** it's wired to
an endpoint. The XIRR fixture and the beta/alpha identity fixture are specified in
§3.3 and §3.4. Don't rush this to get to the charts — it's where correctness lives.

## Facts from the real data that shape the work

- Quicken holds full transaction-level detail: 238 records in the main brokerage
  account, 37 months, 9 action codes, all mapped. The QIF path is the import route.
- A second export set (`QuickenInvest1-4.QIF`) carries 35 securities with 33
  tickers, 4019 price rows across 33 symbols back to 2020, and all 45 `!Account`
  blocks. Four of those securities are market indexes, including `INX` (S&P 500) —
  candidate benchmark seed, though note D6 chose **total return**, and INX is
  price-only, so it likely needs a separate total-return series.
- Two securities have no ticker: a money-market sweep and a pending-distribution
  pseudo-security. Both should be `is_cash_equivalent=True` and excluded from
  positions and lots.
- `Cash` is not one action. Of 58 records: 38 carry `LInterest Inc` (interest
  income), 13 reference the sweep pseudo-security (cash movement, not a holding),
  4 have an amount only, 3 have no amount at all. Map by sign plus `L`/`Y`, and
  skip amount-less records with a warning.
- Half of all dividends are reinvested (62 vs 63). This is the source of the
  allocation-versus-growth confusion the section exists to resolve.
- 8 `ShrsIn` records are transferred-in positions with no purchase history, which
  is why D5 lets statement lots override derived ones.
- The portfolio is bond-heavy. Per-holding beta against the S&P will be near zero
  for several holdings — correct but useless — so `Security.benchmark_security_id`
  exists for overrides, and portfolio-level beta should be the headline number.
- Four probable duplicate account pairs (HSA XX0882 twice, HSA XX9728 twice, Watts
  Water 401k twice, Cash Management twice). Merging them **gates Phase 3** or the
  portfolio double-counts.
- The user wants the price/quote fetcher built (confirms D7's opt-in design, and
  they've asked for it to actually exist). All holdings are exchange-traded.

## Open decisions

- Whether to apply `retype_accounts.py --apply` to the live database, and what to
  do about the four duplicate account pairs. Ask before either — both mutate real data.
- Benchmark seeding: D6 says S&P 500 total return, but the export's `INX` is the
  price index. Needs a total-return source, via the fetcher or a CSV.
