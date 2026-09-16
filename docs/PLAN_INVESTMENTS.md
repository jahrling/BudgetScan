# BudgetScan — Investments Section: Build Plan

**Status:** Phase 0 complete; ready for Phase 1 · **Date:** 2026-09-09 · **Runs in:** Claude Opus, interactive
**Author:** drafted by Claude Fable 5.1 from Conrad's brief; reviewed by Conrad before execution.

This plan adds a separate **Investments** domain to BudgetScan. It answers three
questions Quicken doesn't:

1. **Basis.** For each holding, how much of today's value is money I put in
   versus growth (price appreciation + income), and what is the tax cost basis?
2. **Risk.** What is each holding's beta (and the portfolio's) against the S&P 500?
3. **Broker skill.** What is the portfolio's alpha against the S&P 500 once beta
   and cash-flow timing are removed from the picture?

---

## 0. Instructions for the executing agent (Opus)

- Read `ARCHITECTURE.md` first, then this document, then only the files named in
  each phase. Do not scan the repo.
- Follow `CLAUDE.md` conventions: integer cents for money, Read/Create/Update
  DTOs, one hook file per entity, Tailwind utilities, dark-mode pairs from the
  design vocabulary memory.
- This is a public repo. Statement exports, QIF/QFX/CSV files, and any real
  numbers go under `backend/data/` (gitignored — verify before writing). Test
  fixtures must be synthetic.
- After each phase: `cd backend && uv run pytest`, `cd frontend && npx tsc --noEmit
  && npx vite build`, then run the `code-reviewer` subagent on the diff. Commit
  per phase on a feature branch (`investments`); do not push without asking.
- Financial math is the risky part of this work. Every formula in §3 gets a unit
  test with a hand-checkable fixture before it is wired to an endpoint.
- Where this plan says "decide," make the call, state it in the commit message,
  and move on. Where it says "ask Conrad," stop and ask.

---

## 1. Phase 0 — Discovery (ask Conrad; half a session)

Resolve these before writing code. They change the data model.

| # | Question | Why it matters |
|---|---|---|
| 1 | Which broker(s), and which export formats are actually available: QFX download, CSV activity/positions, Quicken QIF export, PDF statement only? | Picks the import path. `docs/OPEN_ITEMS.md` already suspects Fidelity detail may not come through Quicken EWC+. |
| 2 | Does Quicken hold **transaction-level** detail (buys, sells, dividends) for these accounts, or only positions? Export one account as QIF with "Investment transactions", "Security lists", and "Prices" checked and look at it. | If yes, a single QIF gives transactions, securities, *and* price history — the fastest bootstrap. The parser already recognizes those blocks and throws them away. |
| 3 | Account types: taxable brokerage, IRA, 401k, 529? | Lot term (short/long) and realized-gain reporting only matter in taxable accounts. |
| 4 | Basis method: FIFO, average cost (typical for mutual funds), or "use the broker's lots as printed on the statement"? | Determines whether lots are derived from transactions or seeded from statements. Transferred-in positions usually *need* statement lots. |
| 5 | Benchmark: S&P 500 **total return** (dividends reinvested) or price index? Risk-free rate: fixed number or a T-bill series? | Portfolio returns include dividends, so a price-only index understates the bar. Recommend total return (SPY adjusted close or `^SP500TR`) and a fixed annual risk-free setting, default 0, editable. |
| 6 | How many months of history are available? | Beta/alpha on fewer than ~24 monthly points is noise. UI must show `n` and warn. |
| 7 | Is an outbound HTTP call for benchmark prices acceptable, given the stack is host-only isolated (ADR 0001)? | If no, benchmark data arrives only by CSV upload. Recommend: CSV upload always works; fetcher is opt-in via setting, default off. |

Deliverable: a short "Decisions" block appended to this file, plus the sample
export(s) saved under `backend/data/investments/` (gitignored).

---

## 2. Domain model

### 2.1 Why a separate domain

Investment activity is not cash-flow spending. Reusing `Transaction`/`LineItem`
would pollute budget math (`budget.py` joins LineItem→Transaction by date and
category) and the shape is wrong (quantity, price, security, lot). Keep a
separate table family and link to bank-side `Transaction` rows only where a cash
transfer crosses the boundary. Record this as **ADR 0006**.

### 2.2 Entities

```
Account (existing; type ∈ {"investment","brokerage","ira","401k",...})
  └─< InvestmentTransaction (account_id FK)
        ├── security_id FK → Security (nullable: cash-only actions)
        ├── action: buy | sell | dividend | reinvest_dividend | capital_gain_dist |
        │           reinvest_capital_gain | interest | fee | shares_in | shares_out |
        │           cash_in | cash_out | split | return_of_capital | other
        ├── trade_date, settle_date?
        ├── quantity_micros?, price_micros?, amount_cents (signed cash effect), fee_cents
        ├── source: qif | ofx | csv | manual;  external_id (OFX FITID / hash) — unique per account
        ├── linked_transaction_id FK → transactions (bank side of a transfer, nullable)
        └── memo

Security (symbol? unique, cusip?, name, security_type: stock|etf|mutual_fund|bond|cash|index|other)
  ├─< PriceHistory (security_id, date, close_micros, source)   Unique(security_id, date)
  └─< PositionSnapshot (account_id, security_id, as_of, quantity_micros, market_value_cents,
                        price_micros?, cost_basis_cents?, source)  Unique(account_id, security_id, as_of)

Lot (account_id, security_id, opened_at, opened_by_txn_id?, quantity_micros_original,
     quantity_micros_remaining, cost_basis_cents, is_reinvestment, source: derived|statement)
  └─< LotDisposal (lot_id, sell_txn_id, quantity_micros, proceeds_cents, basis_cents,
                   realized_gain_cents, term: short|long)

InvestmentSettings (singleton row): benchmark_security_id, risk_free_annual_bps,
                    default_lot_method: fifo|average|specific, price_fetch_enabled
```

Conventions:
- Money: integer cents (`BigInteger`), as everywhere else.
- Share quantities: `*_micros` = value × 1,000,000 as `BigInteger` (mutual funds
  carry 3–6 decimals). Prices: `price_micros` = dollars × 1,000,000.
  `amount_cents` is authoritative; `quantity × price` is display-only and may
  differ by rounding.
- Signed `amount_cents`: negative = cash left the account (buy, fee, cash_out),
  positive = cash arrived (sell, dividend, cash_in). `reinvest_*` actions are
  net-zero cash (income received and immediately spent) but create a lot.
- `Lot` rows with `source=derived` are a **cache** rebuilt from transactions by
  replaying the ledger; `source=statement` rows are user-entered truth and take
  precedence for that holding. Provide `POST /investments/lots/rebuild`.
- The benchmark is a `Security` of type `index` so it reuses `PriceHistory`.

### 2.3 Migration

One Alembic revision (`i9j0k1l2m3n4_create_investment_tables.py`, following the
hand-assigned id pattern in `backend/alembic/versions/`). Add an `INVESTMENT_ACCOUNT_TYPES`
constant in `services/account.py` and make budget/spend queries exclude those
account types explicitly (today they are excluded only by accident, because
nothing writes `Transaction` rows for them).

---

## 3. Financial math (backend `services/investment_math.py`, pure functions, no DB)

Everything below is pure Python (no numpy dependency; data volumes are tiny).
Each function gets a test in `tests/test_investment_math.py`.

### 3.1 Basis and lots (`services/lot_engine.py`)

- Replay `InvestmentTransaction` rows per (account, security) in trade-date order.
- `buy`, `reinvest_*`, `shares_in`, `split` open or adjust lots. `reinvest_*`
  lots set `is_reinvestment=True`.
- `sell`, `shares_out` close lots per method: FIFO (default), average cost
  (pool basis, one synthetic lot), specific (only from statement lots).
- `return_of_capital` reduces basis pro-rata across open lots.
- Realized gain = proceeds − basis; term = long if held > 365 days.
- Output per holding: open lots, `cost_basis_cents` (tax basis, includes
  reinvested income), `invested_capital_cents` (external money only:
  `sum(lots where not is_reinvestment)`), realized gains, income received.

**This distinction is the answer to the "allocation vs growth" confusion.**
Reinvested dividends raise the tax cost basis but are *growth*, not new money.
Show both numbers, labeled.

### 3.2 Return decomposition (per holding, per account, over a window)

```
ending_value − beginning_value
    = net_contributions            (external cash: buys funded from outside − sale proceeds withdrawn; XIn − XOut at account level)
    + income                       (dividends, interest, cap-gain distributions — whether reinvested or not)
    + price_appreciation           (realized + unrealized change in market value net of the above)
```

Computed from lots + snapshots + price history. This is the stacked-bar chart
the Overview page shows per year and per month.

### 3.3 Performance series

Valuation points come from `PositionSnapshot` (monthly statements or OFX
`INVPOSLIST`) and/or `PriceHistory × quantity`. **Design requirement: everything
in §3.3–3.4 must work from monthly statement values plus known cash flows alone,
with no external price feed for the holdings.** Only the benchmark needs an
external series.

- **Modified Dietz** sub-period return between two valuation dates:
  `R = (EMV − BMV − CF) / (BMV + Σ wᵢ·CFᵢ)`, `wᵢ = (D − dᵢ)/D`.
- **Time-weighted return (TWR):** chain-link `Π(1+Rₜ) − 1` across sub-periods.
  This is the broker-skill number — it removes the effect of *when* money went in.
- **Money-weighted return (XIRR):** solve `Σ CFᵢ/(1+r)^(tᵢ/365) = 0` with BMV as
  an outflow and EMV as an inflow. Bracketed bisection then Newton polish; test
  against the standard Excel example (−10000 on 2008-01-01, 2750 on 2008-03-01,
  4250 on 2008-10-30, 3250 on 2009-02-15, 2750 on 2009-04-01 → 37.34%).
  This is what Conrad actually experienced.
- Produce a **monthly return series** for each holding, each account, the whole
  portfolio, and the benchmark (from `PriceHistory` month-end closes).

### 3.4 Risk and alpha (monthly excess returns, `rf` = annual setting / 12)

- `β = Cov(Rᵢ−rf, Rₘ−rf) / Var(Rₘ−rf)`
- Jensen's `α_monthly = mean(Rᵢ−rf) − β·mean(Rₘ−rf)`; annualize as `(1+α)^12 − 1`.
- `R²`, annualized volatility `σ·√12`, Sharpe `mean(Rᵢ−rf)/σ·√12`, max drawdown
  from the cumulative TWR series, `n` months used.
- Tests: series with `Rᵢ = 0.5·Rₘ + 0.01` must return β=0.5, α_monthly=0.01, R²=1.
- Report rules: refuse to show β/α when `n < 12`; show a "low confidence" badge
  when `n < 24`. Bond/cash holdings will show β≈0 against the S&P; that is
  correct, not a bug — allow a per-holding benchmark override later (§7).

---

## 4. Import paths (`services/investment_import.py`, extend `services/quicken.py`)

Build in this order; stop after the one that covers Conrad's data (Phase 0 tells you which).

1. **Manual statement entry (always build).** Form: account, as-of date, then
   rows of security / quantity / market value / (optional) cost basis. Writes
   `PositionSnapshot` rows and, if basis is given, `Lot(source=statement)`.
   This is the fallback that works from a paper or PDF statement and is enough
   for TWR and decomposition.
2. **QIF investment blocks.** `quicken.py` already routes `!Type:Invst`,
   `!Type:Security`, `!Type:Prices` to a `security` section and drops them
   (`import_qif`, ~line 370). Parse them:
   - `!Type:Security`: `N` name, `S` symbol, `T` type → `Security`.
   - `!Type:Prices`: CSV lines `"SYM",price,"date"` → `PriceHistory`.
   - `!Type:Invst`: `D` date, `N` action (Buy, BuyX, Sell, SellX, Div, DivX,
     ReinvDiv, ReinvLg, ReinvSh, ReinvInt, CGLong(X), CGShort(X), IntInc(X),
     ShrsIn, ShrsOut, XIn, XOut, MiscExp, MiscInc, StkSplit, Cash, ContribX,
     WithdrwX, RtrnCap), `Y` security, `I` price, `Q` quantity, `T` amount,
     `O` commission, `L` transfer account, `M` memo. Map to §2.2 actions; the
     `X` suffix means the cash side is in another account → try to link to an
     existing bank `Transaction` (reuse `transfer_detector` matching: same
     |amount|, ±3 days) and set `linked_transaction_id`.
   - Surface unknown action codes in `ParseResult.errors` instead of dropping.
3. **OFX/QFX `INVSTMTRS`.** Extend `import_qfx` (today only `BANKTRANLIST`/`STMTTRN`):
   `SECLIST/SECINFO` → `Security`; `INVTRANLIST` (`BUYSTOCK`, `BUYMF`, `BUYOTHER`,
   `SELLSTOCK`, `SELLMF`, `SELLOTHER`, `INCOME`, `REINVEST`, `TRANSFER`, `SPLIT`,
   `INVBANKTRAN`) → transactions keyed by `FITID`; `INVPOSLIST` (`POSSTOCK`,
   `POSMF`: `UNITS`, `UNITPRICE`, `MKTVAL`, `DTPRICEASOF`) → `PositionSnapshot`.
4. **Fidelity CSV** (activity + positions). Only if Phase 0 shows Quicken lacks
   detail. Column layout to be captured from a real file in Phase 0.
5. **Stretch — PDF statement extraction** via the existing Ollama vision path
   (`services/ocr.py`), page by page, into the manual-entry form for review.
   Same "extract → review → commit" pattern as receipts. Do not auto-commit.

Dedupe on `(account_id, external_id)`; for QIF (no ids) hash
`(date, action, security, quantity, amount)`. Reuse the candidate-review UX from
`QuickenSync.tsx` only if it fits cheaply; otherwise a plain "N imported, M
skipped as duplicates, K errors" summary is fine for v1.

### Benchmark prices

- `POST /investments/prices/upload` — CSV with `date,close` (Yahoo Finance and
  Stooq download formats). Always available.
- `PriceProvider` protocol in `services/price_provider.py` with one implementation
  (Stooq daily CSV, no API key) behind `InvestmentSettings.price_fetch_enabled`,
  default **off**. Before implementing, verify the endpoint and its terms at
  build time — do not rely on memory for URL formats or availability. Fetch only
  tickers, never account data.

---

## 5. API (`routers/investments.py`, prefix `/api/investments`)

| Method | Path | Returns |
|---|---|---|
| GET | `/accounts` | investment accounts with current value, invested capital, gain, TWR/XIRR for selected window |
| GET | `/holdings?account_id=&as_of=` | per-security: qty, price, market value, cost basis, invested capital, unrealized gain, income to date, β, α, n |
| GET | `/holdings/{security_id}?account_id=` | lots, disposals, transactions, decomposition, monthly returns vs benchmark |
| GET | `/performance?scope=portfolio|account:{id}|holding:{sid}&from=&to=` | TWR, XIRR, β, α, R², σ, Sharpe, max drawdown, monthly series (own + benchmark), decomposition |
| GET/POST/PATCH/DELETE | `/transactions` | CRUD on `InvestmentTransaction` |
| POST | `/snapshots` | manual statement entry (batch) |
| POST | `/lots/rebuild` | replay ledger |
| POST | `/import/qif`, `/import/qfx`, `/import/csv` | `ParseResult`-style summary |
| POST | `/prices/upload`; POST `/prices/fetch` (if enabled) | rows written |
| GET/PATCH | `/settings` | `InvestmentSettings` |
| GET/POST | `/securities` | list / create (manual entry needs this) |

Schemas in `schemas/investment.py` (Read/Create/Update per entity). Register the
router in `main.py`. Add TS interfaces to `types/models.ts` and hooks in
`hooks/useInvestments.ts` with query keys `["investments", ...]`; every mutation
invalidates that prefix.

---

## 6. Frontend (`routes/Investments.tsx` + `components/investments/`)

Add `{ to: "/investments", label: "Invest", icon: TrendingUp }` to `Layout.tsx`.
The nav already has 7 items; verify the mobile bottom tab bar still fits at
375px. If it doesn't, fold `Docs` into an overflow rather than shrinking tap targets.

Sub-views (segmented control, like Budgets plan/track):

1. **Overview** — total value, invested capital, growth (income + appreciation),
   window selector (YTD / 1y / 3y / all). Two charts: cumulative growth line,
   portfolio TWR vs benchmark; stacked bars per period, contributions vs income
   vs appreciation. Stat tiles: TWR, XIRR, β, α (annualized), with `n` and the
   low-confidence badge.
2. **Holdings** — table per account: symbol, qty, value, cost basis, invested
   capital, unrealized gain %, income, β, α. Tap → detail.
3. **Holding detail** — decomposition bars, monthly return vs benchmark, lots
   table (open/closed, term), transaction list.
4. **Import** — manual statement entry form, file upload (QIF/QFX/CSV), benchmark
   price CSV upload, last-import summary.
5. **Settings** — benchmark security, risk-free rate, lot method, price fetch toggle.

Charts: no chart library is in `package.json`. Decide between two small
hand-rolled SVG components (line, stacked bar; theme-aware via the design
vocabulary tokens) and adding `recharts`. Recommendation: hand-rolled — two
chart types, small bundle, full dark-mode control. Load the `dataviz` skill
before writing them. Add `formatShares()` and `formatPrice()` next to
`formatCents()` in `MoneyInput.tsx`.

---

## 7. Out of scope for v1 (note in `docs/OPEN_ITEMS.md`)

- Tax reporting: wash sales, 1099-B reconciliation, cost-basis elections at sale time.
- Options, bonds held to maturity with accrued interest, multi-currency.
- Real-time quotes; per-holding benchmark overrides (e.g. AGG for bond funds);
  factor models beyond single-index CAPM.
- Automated Quicken export (already an open item).

---

## 8. Phases, order, and acceptance

| Phase | Deliverable | Done when |
|---|---|---|
| 0 | Decisions block in this file; sample exports under `backend/data/investments/` | Conrad has answered §1 |
| 1 | ADR 0006; models, migration, schemas, settings; `INVESTMENT_ACCOUNT_TYPES` excluded from budget math | `pytest` green; migration applies to a copy of the real DB |
| 2 | `investment_math.py` + `lot_engine.py` with tests (XIRR fixture, β/α identity fixture, FIFO/average lot fixtures, Modified Dietz worked example) | Every formula in §3 has a passing hand-checked test |
| 3 | Import: manual snapshots + whichever of QIF/QFX/CSV Phase 0 selected; benchmark CSV upload | Conrad's real export imports with zero unexplained errors; re-import is idempotent |
| 4 | Router + hooks + Overview + Holdings + Holding detail | `tsc` and `vite build` clean; numbers on Overview reconcile to the latest statement's total within rounding |
| 5 | Import page, Settings page, optional price fetcher | Round trip: upload statement → see TWR/β/α |
| 6 | `ARCHITECTURE.md` (entities, layout, an "Investments" feature flow, routes table, cache keys), `OPEN_ITEMS.md` updates | Docs match code; `code-reviewer` pass on the full branch; PR opened |

Estimated size: roughly the same as the rules/recurring work (PR #23), split
across 6 commits. Phases 2 and 3 are where correctness lives; do not rush them
to get to the charts.

---

## 9. Phase 0 — Findings and Decisions

### 9.1 Evidence gathered 2026-09-09 (Opus, from the live dev database)

The dev stack (`budgetscan-backend-1`, volume `budgetscan_db-data`) holds the real
data: 44 accounts, 5,885 transactions, 1985-04-04 to 2026-09-08. The `deploy-*`
stack has a different, near-empty DB (`acctbud.db`) and is not the system of record.

**F1 — Investment transactions are silently dropped on QIF import.** Confirmed by
running a synthetic brokerage QIF (one `!Type:Security`, one `!Type:Prices`, four
`!Type:Invst` records: Buy, ReinvDiv, Sell, XIn) through `import_qif`:

```
candidates:        0
unmapped_accounts: ['Synthetic Brokerage']
errors:            []
```

Zero candidates, **zero errors**. `import_qif` routes `!Type:Invst`, `!Type:Security`
and `!Type:Prices` to `section_kind = "security"` and the `^` record terminator has
no flush branch for it (`services/quicken.py:~370-450`). The user sees "nothing to
import" with no indication that anything was lost.

**F2 — The 13 investment accounts exist but are empty.** Accounts 29-41 all have a
transaction count of zero, which is F1 observed in production. They are:

| Kind | Accounts |
|---|---|
| 529 | BrightStart 529 - Leavitt; Iowa 529 - Archer x02; Iowa 529 - Leavitt x01 |
| HSA | Conrad's HSA Fidelity Go XX0882; HSA Fidelity Go XX0882; Health Savings Account XX9728; HSA XX9728 |
| IRA | Contributory ...988; Roth Contributory IRA ...217 |
| 401(k) | WATTS WATER TECH 401(k) XX7263; WATTS WATER TECHNOLOGIES, INC. 401K SAVI |
| Brokerage | Cash Management (Individual - TOD) XX297; Cash Management XX2970 |

**F3 — Only one account is taxable.** `Cash Management (Individual - TOD)` is the
only taxable holding. 529 / HSA / IRA / 401(k) need basis for the
allocation-vs-growth question but never need short/long lot terms or realized-gain
reporting. Phase 2 must still build lots (basis is the whole point) but
`LotDisposal.term` and realized-gain reporting can stay minimal for v1.

**F4 — Four probable duplicate account pairs.** `XX0882` appears twice (ids 32, 35),
`XX9728` twice (34, 36), Watts Water 401(k) twice (40, 41), Cash Management twice
(30, 31 — though 30 is "Individual - TOD" and 31 may be a genuinely different
registration). Importing positions before merging these will double-count the
portfolio. **Resolve before Phase 3.**

**F5 — No investment activity has leaked into the bank ledger.** `Edward Jones -
9483 XX3975` (account 11, 37 transactions) looked like a brokerage but is a credit
card: annual membership fee, late fees, "Interest Charge On Purchases", "Payment
Thank You". So the separate-domain design in §2.1 needs no data cleanup or
back-migration. Confirmed clean.

**F6 — Account types are wrong across the board.** All 44 accounts are typed
`checking`, including credit cards, mortgages, student loans, and every investment
account. `services/account.py` has no type vocabulary and nothing validates the
field. Phase 1 must set real types before `INVESTMENT_ACCOUNT_TYPES` can exclude
anything, otherwise the constant matches nothing.

**F7 — Encoding damage in imported names.** "Fidelity� Rewards Visa
Signature� Card" and "Citi Simplicity��Card" show mojibake from the
QIF import decoding cp1252 bytes as UTF-8. Cosmetic, unrelated to investments,
worth a separate one-line fix.

### 9.2 Decisions taken without Conrad

- **D1. Fix F1 before anything else in Phase 3.** Even if the QIF turns out to carry
  no usable investment detail, dropping records without an error is a bug. Minimum
  change: count skipped investment records and surface them in `ParseResult.errors`.
- **D2. Phase 1 gains an account-type cleanup step.** Add a type vocabulary
  (`checking, savings, credit, loan, mortgage, cash, brokerage, ira, roth_ira,
  401k, 529, hsa, asset`), a one-off retype script under `backend/src/finance/scripts/`,
  and only then `INVESTMENT_ACCOUNT_TYPES`. Per F6 this is a prerequisite, not a nicety.
- **D3. Duplicate-account merge is a Phase 3 gate** (F4), not a later cleanup.
- **D4. Realized-gain/term reporting is minimal for v1** (F3): compute and store it,
  but do not build tax-lot UI beyond the lots table in the holding detail view.

### 9.3 Decisions taken with Conrad (2026-09-09)

- **D5 (Q4) — Basis: FIFO derived from transactions, statement lots override.**
  `Lot.source = "statement"` wins over `"derived"` for any (account, security) where
  statement lots exist. Handles transferred-in positions that have no purchase
  history. Average cost is *not* implemented in v1; `default_lot_method` still ships
  as a settings field so it can be added without a migration.
- **D6 (Q5) — Benchmark: S&P 500 total return, risk-free 0%.** Dividends reinvested,
  because portfolio returns include income and a price-only index understates the
  bar by roughly 2%/yr. `risk_free_annual_bps` defaults to `0` and is editable, so
  Jensen's alpha initially reads as excess return over the market. Seed the benchmark
  as a `Security(symbol="SP500TR", security_type="index")`.
- **D7 (Q7) — Price fetching: opt-in, ships disabled.** CSV upload is the always-
  available path. `InvestmentSettings.price_fetch_enabled` defaults to `False`;
  the provider sends ticker symbols only and never account data. Consistent with
  ADR 0001 (host-only isolated stacks).
- **D8 (Q1/Q2) — Pursuing the Quicken QIF path.** Conrad exports
  `Cash Management (Individual - TOD)` (the taxable account, so the most demanding
  test) with *Investment transactions*, *Security lists* and *Prices* checked, into
  `backend/data/investments/`.

### 9.4 Phase 0 tooling delivered

`backend/scripts/qif_inspect.py --investments` answers Q2/Q6 mechanically. The new
`scan_investments()` reads the QIF text directly rather than going through
`import_qif`, because per F1 the parser reports zero of everything for a brokerage
file. It reports: investment-typed `!Account` blocks, securities (by type, flagging
any with no ticker), price rows with date range, and investment transactions broken
down by QIF action code — each mapped to the §2.2 action vocabulary, with unknown
codes flagged as `*** UNKNOWN ***` and recognised-but-out-of-scope codes (equity
comp: Vest, Grant, Exercise) called out separately. It ends with a verdict naming
which §4 import path applies. Also decodes cp1252 before UTF-8, per F7.

Run it on the export:

```
cd backend && uv run python scripts/qif_inspect.py data/investments/<file>.qif --investments
```

Verified against a synthetic fixture: 7 investment records, 2 securities (1 without a
ticker), 3 price rows, 1 unknown action, 1 out-of-scope action — all correctly
classified, while the `import_qif` summary in the same run showed
`Transactions: 0 / Parse errors: 0`.

### 9.5 Export results (2026-09-15) — Q2 and Q6 answered

Conrad exported one brokerage account. Inspector summary (no amounts recorded here):

| | |
|---|---|
| `!Type:Invst` records | 238 |
| Date range | 2023-08-30 to 2026-09-04 (37 months) |
| Distinct securities | 16, referenced by name only |
| `!Type:Security` / `!Type:Prices` | 0 / 0 |
| `!Account` header | none |
| Unknown action codes | none |

Action mix: Div 63, ReinvDiv 62, Cash 58, Buy 31, Sell 12, ShrsIn 8, ShrsOut 2,
XOut 1, StkSplit 1.

**F8 — Quicken holds full transaction-level detail.** Q2 is a yes. The QIF path is
the import route; Phase 3 is parsing, not manual entry. §4.1 manual snapshots still
get built, but as the valuation source (see F11), not the transaction source.

**F9 — 37 months of history** clears the 24-month bar for beta and alpha (Q6).

**F10 — Half of all dividends are reinvested** (62 ReinvDiv against 63 Div). This is
the concrete source of the allocation-vs-growth confusion the whole section exists
to resolve; §3.1's `invested_capital_cents` vs `cost_basis_cents` split is the
right cut. 8 `ShrsIn` records are transferred-in positions with no purchase history
in this file, which is exactly the case D5's statement-lot override exists for.

**F11 — No security list, no price history, no account header.** Every security is
identified only by a broker-feed display name; there are no tickers. The 105
transaction-date prices are sparse points, not a valuation series. Consequences:

- Re-export with **Security Lists** and **Account List** checked to get `!Type:Security`
  (name → ticker) and the `!Account` header. If Quicken cannot emit `!Type:Prices`
  (the checkbox may not exist in current versions), that is fine.
- Month-end valuations must then come from one of: manual statement snapshots
  (§4.1), or the opt-in price fetcher (D7) once tickers are known. All 16 holdings
  are exchange-traded, so the fetcher is the low-effort route; per-ticker CSV
  upload for 16 symbols is not. Conrad decides whether to enable it.
- Until an `!Account` header is present, the import UI must let the user pick the
  target account.

**F12 — `Cash` is not one action.** 58 records split three ways: 38 carry
`LInterest Inc` (interest income, positive), 13 reference a money-market sweep
pseudo-security (`Y` set, cash movement between sweep and settlement, not a
holding), 4 have an amount and nothing else, and 3 have no amount at all. Phase 3
must map `Cash` by sign plus `L`/`Y`, treat the sweep security as cash-equivalent
rather than a position, and skip amount-less records with a warning. The inspector's
label for `Cash` now says so.

**F13 — Bond-heavy ETF mix.** Several of the largest-by-activity holdings are bond
ETFs. Beta against the S&P will be near zero for them, which is correct but not
useful. Promote per-holding benchmark override from §7 (out of scope) to a v1.5
item, and show portfolio-level beta prominently since that is the number that
answers "how risky is this, really".

### 9.6 Still open — gates Phase 3 only

- **Re-export with Security Lists + Account List checked** (F11). Phase 1 and 2 do
  not depend on it; Phase 3 does.
- **Enable the price fetcher, or plan on entering monthly statement values?** (F11).
  Affects Phase 5 only.
