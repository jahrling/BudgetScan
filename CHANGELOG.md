# BudgetScan Changelog

## 2026-09-21

- Add S&P 500 benchmark auto-download: fetches monthly SPY prices from Stooq, creates the security, stores price history, and sets it as portfolio benchmark — all in one click from Investment Settings.
- Add risk-free rate auto-refresh: fetches current 6-month US T-bill yield from FRED and saves it for Sharpe ratio calculations. Both refresh buttons are in the Investment Settings dialog.
- Add brokerage holdings CSV import (Fidelity format first). Parses positions with cost basis, creates securities by symbol, matches/creates accounts by number or name, upserts PositionSnapshots and PriceHistory. Frontend drop zone on Import tab.
- Add `account_number` field to Account model for matching brokerage accounts across imports.
- Add Performance tab to Investments page: alpha, beta, Sharpe ratio, volatility, R², max drawdown, XIRR (personal return), TWR (strategy return), return decomposition (contributions/income/appreciation), and monthly returns table with benchmark comparison.
- Upgrade return decomposition display to include a stacked bar visualization showing proportional breakdown of contributions, income, and price appreciation alongside the stat tiles.
- Add info tooltips to Performance tab metrics (TWR, XIRR, alpha, beta, Sharpe, volatility, R², max drawdown, and decomposition tiles) explaining what each concept means on hover.
- Add Investment Settings dialog accessible from Performance tab (gear icon + "Configure" link on the no-benchmark banner). Lets you pick a benchmark security and set the risk-free rate.
- Improve OCR error messages: backend now distinguishes model-not-found, connection failures, timeouts, empty responses, and JSON parse errors with actionable messages including model name. Frontend shows contextual hints for each error type.
- Fix vision OCR returning empty responses with qwen3.5 models: remove `format: "json"` from Ollama vision calls (constrained JSON decoding breaks multimodal input on some models). The `extract_json` parser already handles freeform replies.

## 2026-09-20

- Fix Holdings view not showing statement-OCR data: `get_holdings` now falls back to the latest PositionSnapshot when no lots exist for an (account, security) pair; detail view does the same. Also fix stale cache after materialize (query key mismatch).
- Fix Statement Review table: column headers now align with columns (`table-fixed` + `colgroup`); shorten "Market Value" to "Mkt Value" so columns fit.
- Fix MoneyInput blocking copy/paste: replace keystroke-interception approach with standard focus/blur editing so Ctrl+C/V and text selection work everywhere (Statement Review, Budgets, SplitEditor, Transactions, Receipt Review).
- Statement materialize now writes per-share prices to PriceHistory so lot-based holdings show market values without a separate price CSV upload.
- Statement OCR now accepts PDF uploads: text-based PDFs (downloaded from brokerage) are parsed via text extraction + LLM; scanned/image PDFs fall back to vision OCR.
- Add `find_duplicate_accounts.py` script to identify and merge duplicate account pairs in the database.
- Apply `retype_accounts.py` to reclassify 32 accounts from their import-default types to correct types (HSA, 401k, IRA, etc.).
- Add SECURITY.md with data-handling and privacy rules for Claude sessions; consolidate PII guidance from CLAUDE.md.
- Add documentation requirements to CLAUDE.md (changelog, architecture updates, issue policy).

## 2026-09-19

- Investment statement OCR via local Ollama vision model for parsing brokerage PDFs.

## 2026-09-18

- Fix holdings not displaying; move Import into its own tab for cleaner navigation.
- Handle Quicken fractional notation (e.g. `31 31/32`) in QIF price/amount parsing.
- Auto-create investment accounts from QIF data on import instead of requiring manual setup.
- Add Import QIF button to Investments page header.
- Fix GlobalDropZone intercepting QIF drops meant for the Investments page.

## 2026-09-16

- Investment QIF import UI with banking-account skip detection.
- Aggregate portfolio views and Investments UI (Phase 4 of investments feature).

## 2026-09-15

- Investment import layer, router, and API endpoints (Phase 3).
- Investment math and lot-tracking engine with tests (Phase 2).
- Investments domain: models, migration, account types, budget exclusion (Phases 0-1).
- QIF PII safeguards added to CLAUDE.md; deploy script fix.

## 2026-09-05

- Rules management, recurring transaction detection, and categorization tools.
- Dark mode fixes across all pages, iOS safe-area support, budget reset.

## 2026-09-03

- Color-coded amounts in budget detail panel to match Transactions page styling.
