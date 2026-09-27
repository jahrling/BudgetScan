# BudgetScan Changelog

## 2026-09-27

- Redesign **manual transfer linking UX**: instead of asking for a raw transaction ID, the flow now starts with an account picker, then shows candidate counterpart transactions (matched by amount and sorted by date proximity) that can be linked with one click.
- Add **account-only transfer marking** for transfers where the counterpart hasn't posted yet — records the target account and assigns the Transfer category without requiring a paired transaction.
- Add `transfer_target_account_id` to the Transaction model to persist the intended transfer account independently of a linked pair.
- Add `GET /api/transfers/candidates` endpoint to find matching unlinked transactions by account and amount.
- Add `POST /api/transfers/mark` endpoint for account-only transfer marking.

## 2026-09-24

- Add **Accounts tab** to the Sync page: full account management with expandable detail rows showing all fields (name, type, institution name, institution address, routing number, Quicken ID). All fields are inline-editable.
- Add **Add Account** form on the Accounts tab.
- Add `routing_number`, `institution_name`, and `institution_address` fields to the Account model so accounts carry their bank identity.
- Add ABA routing number validation (checksum) and lookup endpoint (`GET /api/accounts/routing-lookup/{rtn}`) with a static table of ~100 common US bank routing numbers.
- SimpleFIN compatibility check now searches by `institution_name` when set, falling back to parsing account names. Searches are deduplicated by institution so multiple accounts at the same bank share one search.
- Improve SimpleFIN error handling: fail-fast probe on startup, typed `SimpleFINError` exceptions, and frontend messages that explain what went wrong instead of showing raw HTTP status codes.
- Rename nav tab from "Sync" to "Sync Accts".

## 2026-09-23

- Add bank compatibility checkers for SimpleFIN and Teller on the Sync page. Each checks BudgetScan accounts against the provider's supported institution list and archives a JSON report to `data/bank-compatibility/`. No provider signup required to run the check.
- Add backend proxy for Teller institutions API (avoids browser CORS) with disk caching and manual refresh.
- Add SimpleFIN institution search via server-side scraping of their search page (no bulk list API available).

## 2026-09-22

- Add email gateway with Gmail API integration for automated receipt ingestion. Multi-account support with OAuth2 authorization flow, per-account scoping (read-only vs send-capable).
- Add Amazon order confirmation email processor: parses order ID, total, and line items using template regex extraction with Ollama LLM fallback, stores structured EmailReceipt records.
- Add email receipt-to-transaction matching: candidate finder by amount and date window, manual match confirmation linking email receipts to imported Quicken transactions.
- Add policy-gated email sending: outbound emails require an active EmailPolicy with defined recipient, template, and frequency limit. Rate limiting, template rendering via Jinja2, and full audit logging (EmailLog). Global kill switch (GMAIL_SEND_ENABLED) defaults to off.
- Add transfer counterpart display in transaction detail view: shows a violet banner with the other account name, direction (to/from), and a "View counterpart" button to navigate to the paired transaction.
- Add manual transfer linking: "Link as transfer" action in the transaction detail view lets users manually pair two transactions as a transfer, complementing the existing auto-detection.
- Add `GET /api/transfers/{pair_id}` endpoint for direct transfer pair lookup.
- Add `POST /api/transfers/link` endpoint for manually linking two transactions as a transfer pair.
- Fix unlink behavior: clearing a transfer pair now also reverts the "Transfer" category and flags the transactions for re-categorization.
- Fix `get_transaction_with_items` missing fields: detail view now returns `transfer_pair_id`, `account_name`, `category_id/name/source/confidence`, `needs_review`, `is_recurring`, `recurrence_cadence`, `recurrence_group_id`, and `transfer_account_name`.
- Add inline account type editing in the Investments overview: click the type column to change an account between brokerage, IRA, 401k, etc.
- Add account merge API (`POST /api/accounts/merge`): reassigns all transactions, investment transactions, lots, position snapshots, and statement scans from the source to the target account, then deletes the source.
- Add account merge UI in the Investments overview: select source and target accounts to consolidate duplicates.

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
