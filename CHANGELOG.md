# BudgetScan Changelog

## 2026-09-20

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
