# 0002. Quicken integration is file-based (QFX/QIF), never a live connector

**Status:** accepted
**Date:** 2026-07-18
**Supersedes:** —
**Superseded by:** —
**Related:** 0003 (SQLite as source of truth), 0004 (interface ownership)

## Context

Quicken remains the system of record for bank data — it handles institution
connections, reconciliation, and security well. BudgetScan needs Quicken's
transaction data to work against, and needs to hand its own line-item splits back
so Quicken stays authoritative.

The options are a live connector (an aggregation service such as Plaid, or
scripting Quicken's cloud sync) versus file exchange. A live connector means a
third party sees the transaction stream, adds a subscription cost, and pulls data
off the box. Quicken also has no public write API, so pushing splits back through
a live path isn't actually available.

## Decision

Quicken integration is **file-based**: export from Quicken as **QFX**, import into
BudgetScan; export **QIF** with splits from BudgetScan, import back into Quicken.
The exchange is manual and runs on the user's cadence (typically weekly). No live
connector, no third-party aggregation, no cloud round-trip.

## Consequences

- Bank data never leaves the box through a third party; no Plaid subscription.
- QFX/QIF is the historical lingua franca — well understood, and the only path
  Quicken actually supports for writing splits back.
- Sync is manual and point-in-time, not continuous; the user drives it.
- QFX/QIF files contain real financial data and must never enter git — they are
  gitignored alongside the SQLite DB and receipts (see 0003, standing constraints).
