# 0006. Investments are a separate domain from cash-flow transactions

**Status:** accepted
**Date:** 2026-09-15
**Supersedes:** —
**Superseded by:** —
**Related:** 0002 (file-based Quicken sync), 0003 (structured store as source of truth)

## Context

BudgetScan's `Transaction` / `LineItem` model describes cash-flow spending: a
signed amount on a date, categorised, optionally split. Budget maths joins
`LineItem` to `Transaction` by date range and category and sums `amount_cents`.

Investment activity has a different shape. A buy has a quantity, a price, a
security, and a cash effect that is not spending. A reinvested dividend is
income and a purchase in one record with a net cash effect of zero. A share
transfer has quantity but no cash at all. Answering the questions that motivate
the section (how much of a holding's value is contributed capital versus growth;
beta and alpha against a benchmark) requires lots, position valuations over
time, and a price series per security. None of that maps onto line items, and
forcing it to would put investment cash flows into budget totals.

The existing QIF importer already illustrates the cost of *not* separating the
two: it routes `!Type:Invst`, `!Type:Security` and `!Type:Prices` blocks into
a section that is never flushed, so every investment record was silently
discarded and the thirteen investment accounts sat empty (see
`docs/PLAN_INVESTMENTS.md` §9.1, finding F1).

## Decision

Investment data lives in its own table family — `securities`, `price_history`,
`position_snapshots`, `investment_transactions`, `lots`, `lot_disposals`,
`investment_settings` — with no foreign keys *from* the cash-flow tables into
it. The only link in the other direction is
`investment_transactions.linked_transaction_id`, a nullable pointer to the
bank-side `Transaction` when a cash transfer crosses the boundary (a QIF `XIn` /
`XOut`, or an OFX `TRANSFER`).

`Account` remains the shared parent. `Account.type` gains a closed vocabulary
(`services/account.py`), of which a subset is `INVESTMENT_ACCOUNT_TYPES`. Every
budget and spend aggregation excludes transactions on accounts of those types
explicitly, rather than relying on nothing having written rows there.

Money stays in integer cents. Share quantities and prices use integer
millionths (`*_micros`) because mutual funds carry up to six decimal places.
`amount_cents` on an investment transaction is authoritative; `quantity ×
price` is display-only.

Derived lots (`lots.source = "derived"`) are a rebuildable cache computed by
replaying the transaction ledger. Statement-sourced lots (`source =
"statement"`) are user-entered truth and take precedence for that holding.

## Consequences

- Budget totals are provably free of investment cash flows, by construction
  rather than by accident.
- The investment importer, lot engine and performance maths can be built and
  tested without touching the categorisation pipeline or the receipt flow.
- Two parallel "transaction" concepts exist and the UI must keep them visually
  distinct. Transfers between a bank account and a brokerage appear in both
  ledgers, linked, and must not be double-counted in net-worth views.
- `Account.type` values already in the database are wrong (every account was
  created as `checking`) and must be corrected by a one-off script before the
  exclusion has any effect.
