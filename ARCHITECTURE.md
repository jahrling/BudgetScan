# BudgetScan — Codebase Architecture

Compressed code map — enough for an LLM (or a new contributor) to navigate the
codebase without reading every file. Updated 2026-09-01.

> System-level topology (TheRig, Tailscale, network) lives in `INFRA.private.md`
> (gitignored). App build plan and ADRs are in `docs/`.

## Entities

```
Account (name, type, quicken_id, account_number, currency)
  └─< Transaction (account_id FK)
        ├── merchant_id FK → Merchant (nullable)
        ├── category_id FK → Category (nullable, denormalized from single line item)
        ├── receipt_id FK → Receipt (nullable)
        ├── transfer_pair_id (links two txns as a transfer)
        ├── status: "pending" | "split" | "confirmed"
        ├── needs_review, category_source, category_confidence
        └─< LineItem (transaction_id FK)
              ├── category_id FK → Category (required)
              ├── description, quantity, unit_price_cents, amount_cents
              └── ocr_confidence, user_modified

Category (name, parent_id FK → self, color, icon, is_income)
  └─< Budget (category_id FK, year_month, period, amount_cents, is_pinned)
       UniqueConstraint(category_id, year_month)

Merchant (name, normalized_name, default_category_id FK → Category)

Receipt (file_path, sha256 unique, ocr_status, ocr_raw_json)

MemorizedRule (payee, normalized_payee, category_id, status: active|draft|inactive)

Security (symbol, name, security_type, is_cash_equivalent, benchmark_security_id FK → self)
  └─< PriceHistory (security_id FK, as_of, close_micros, source)

Account
  └─< InvestmentTransaction (account_id FK, security_id FK → Security)
        ├── action: buy|sell|dividend|reinvest_dividend|... (see INVESTMENT_ACTIONS)
        ├── trade_date, quantity_micros, price_micros, amount_cents, fee_cents
        ├── external_id (unique per account), source, memo
        └── linked_transaction_id FK → Transaction (cash boundary crossing)
  └─< Lot (account_id FK, security_id FK)
        ├── opened_by_id FK → InvestmentTransaction, open_date, quantity_micros, cost_basis_cents
        ├── is_reinvestment, is_closed
        └─< LotDisposal (lot_id FK, closed_by_id FK → InvestmentTransaction, quantity_micros, proceeds_cents)
  └─< PositionSnapshot (account_id FK, security_id FK, as_of, quantity_micros, market_value_cents, source)

InvestmentSettings (key unique, value — portfolio-level config like benchmark)

StatementScan (file_path, sha256 unique, account_id FK nullable, as_of, ocr_status, ocr_raw_json)
  — input: image (JPG/PNG) or PDF; PDF pages rendered to images via PyMuPDF before OCR
```

LineItems have no account — inherited from parent Transaction. Transaction.category_id is denormalized from its single LineItem (null when split).

## Directory Layout

```
backend/src/finance/
  main.py              — FastAPI app, mounts routers, CSRF + rate-limit middleware
  db.py                — async engine + session factory
  models/              — SQLAlchemy models (base, account, transaction, line_item, category,
                         budget, merchant, receipt, annotation, memorized_rule, user)
  schemas/             — Pydantic DTOs (read/create/update per entity)
  routes/              — API routers per domain
  services/
    transaction.py     — CRUD, replace_line_items (validates sum, manages status transitions)
    categorization_pipeline.py — cascading: regex → merchant lookup → exact rule → substring → embedding → LLM
    receipt.py         — upload (dedupe by sha256), OCR via Ollama vision, materialize to txn
    budget.py          — status computation (spent via LineItem join), seed, income/unbudgeted/comparison
    transfer_detector.py — same amount ±3 days, different accounts
    quicken.py         — QIF/QFX parse, candidate matching, import confirm
    finance_qa.py      — RAG: numeric → SQL, free-text → vector retrieval + generation
    market_data.py     — fetch S&P 500 prices (Stooq) and T-bill risk-free rate (FRED)

frontend/src/
  main.tsx             — BrowserRouter, QueryClient (30s staleTime), AuthGuard, lazy routes
  lib/api.ts           — fetch wrapper: apiFetch<T>, api.get/post/patch/put/delete, authApi
  types/models.ts      — TypeScript interfaces mirroring backend schemas
  hooks/               — TanStack Query wrappers per domain (one file per entity)
  routes/
    Home.tsx           — dashboard: budget cards, recent txns, top merchants
    Transactions.tsx   — list + filters + TransactionDetailView (inline, ~line 1099) + CategorizationReviewModal (~line 744)
    Budgets.tsx        — plan (slider adjust) + track (progress bars) views, MonthSelector
    Categories.tsx     — hierarchical CRUD tree
    ReceiptProcessing.tsx — OCR polling → redirect to review
    ReceiptReview.tsx  — editable OCR preview → materialize to transaction
    QuickenSync.tsx    — QIF/QFX import with candidate review + QIF export
    Login.tsx, Docs.tsx
  components/
    Layout.tsx         — responsive shell: desktop sidebar (48/56px) + mobile bottom tabs
    CategoryPicker.tsx — searchable combobox, hierarchical categories
    SplitEditor.tsx    — multi–line-item editor with balance tracking
    MoneyInput.tsx     — cents ↔ dollar input, exports formatCents()
    MerchantCombobox.tsx — typeahead search + create-new
    MonthSelector.tsx  — ‹ Month Year › navigation
    SnapReceiptButton.tsx — camera/file upload → receipt processing
    GlobalDropZone.tsx — drag-and-drop: .qif → sync, images → receipt upload
    ui/                — Button, Dialog, Input, Label, Select, SegmentedControl
```

## Feature Flows

### Transaction Edit
```
TransactionDetailView (Transactions.tsx:~1099)
  → useTransaction(id) → GET /transactions/{id} → TransactionDetail {account_name, line_items[]}
  → renders: merchant/description header, date + account badge, amount, receipt thumbnail
  → SplitEditor (SplitEditor.tsx)
      → per item: CategoryPicker + MoneyInput + description Input
      → balance tracking: sum(items) vs txn.amount_cents
  → Save: useReplaceLineItems → PUT /transactions/{id}/line_items
      → backend replace_line_items(): validates sum == total, deletes all, creates new
      → 1 item: status="pending", copies category to txn, source="user"
      → N items: status="split", txn.category_id=null
      → also: maybe_update_default_category on merchant
  → Confirm: useUpdateTransaction({status: "confirmed"})
```

### Receipt → Transaction
```
SnapReceiptButton or GlobalDropZone
  → uploadReceipt(file) → POST /receipts (FormData, XHR with progress)
      → backend: dedupe by sha256, validate image, store to disk
      → background: OCR via Ollama vision → ocr_raw_json
      → on success: archive to Dropbox, delete local file
  → navigate to /receipts/:id/processing

ReceiptProcessing (ReceiptProcessing.tsx)
  → useReceipt(id) with auto-poll (refetchInterval while ocr_status=="pending")
  → done → /receipts/:id/review
  → timeout 60s → retry (POST /:id/process) or manual entry (/transactions?manual=<id>)

ReceiptReview (ReceiptReview.tsx)
  → useOcrPreview(receiptId) → GET /receipts/{id}/ocr-preview
      → {merchant, date, total_cents, items[], drift_cents}
  → editable: merchant picker, date, per-item (description + CategoryPicker + MoneyInput)
  → Submit: useReviewToTransaction → POST /receipts/{id}/review-to-transaction
      → creates Transaction + LineItems → navigate to /transactions?open=<txn.id>
```

### AI Categorization
```
Transactions page → "Categorize" button
  → useCategorizeTransactions → POST /transactions/categorize
      → categorization_pipeline.py (cascading):
          Identity: regex cleanup → Merchant table → LLM merchant-name guess
          Category: exact rule → substring/token → embedding similarity → LLM
          → confidence ≥ 0.92 auto-confirms (needs_review=false)
      → returns {results[], processed, skipped}
  → CategorizationReviewModal (Transactions.tsx:~744)
      → user checks/unchecks suggestions
      → useApplyCategories → POST /transactions/apply-categories
          → applies confirmed, auto-creates MemorizedRules
```

### Budgets
```
Plan view:
  → useBudgets(month) + useSpendingSuggestions(3) + useIncomeSummary(month)
  → PlanRow: slider to adjust, sparkle = apply suggestion, pin/edit/delete
  → AutoBudgetPanel: unbudgeted categories with "Add" / "Add all"

Track view:
  → useBudgetStatus(month) → backend joins LineItem→Transaction for date range + category
      → {spent_cents, percent_used, days_remaining} per budget
  → useMonthComparison + useUnbudgetedSpend
  → TrackRow: progress bar, remaining, trend vs prior month
  → click category → BudgetTransactionPanel: useTransactions({category_id, dates})

Seed: POST /budgets/seed?month= (copies pinned budgets from prior month)
```

### Quicken Sync
```
Import:
  → file drop or picker → POST /api/import/qif
      → ParseResult {candidates[], unmapped_accounts[], errors[], rules[]}
  → CandidateReview: per-row action (create/skip/merge/overwrite) vs existing txn
  → POST /api/import/confirm → applies actions

Export:
  → account checkboxes + date range → GET /api/export/qif (downloads file)
```

### Transfer Detection
```
POST /transfers/detect → same |amount|, different accounts, posted_at ±3 days
  → links pair via transfer_pair_id (= smaller txn.id)
```

### Statement OCR (image or PDF)
```
Upload:
  → file picker (JPG/PNG/PDF) → POST /api/statement-scans
      → store_upload: validate (Pillow for images, PyMuPDF for PDFs), dedupe by sha256
      → background processing → ocr_raw_json:
        - Images: preprocess → Ollama vision call
        - PDFs (text-based, ≥200 chars): extract text via PyMuPDF → Ollama text model
        - PDFs (scanned/image): render pages to JPEG → vision call per page → merge
  → StatementProcessing: poll ocr_status → redirect to review on "done"
  → StatementReview: editable holdings table, account/date pickers
      → POST /api/statement-scans/{id}/materialize → PositionSnapshot rows (source="ocr")
```

### Investment QIF Import
```
Import:
  → file drop or picker → POST /api/investments/import-qif
      → parse !Account blocks → auto-create/retype accounts
      → parse investment transactions → dedupe by external_id per account
      → rebuild lots via lot engine (FIFO)
  → response: created/skipped/error counts
```

### Performance Analytics
```
Performance tab:
  → usePerformance() → GET /api/investments/performance
      → get_performance(): aggregate PositionSnapshots by date → portfolio value series
      → gather cash flows (cash_in/cash_out/shares_in/shares_out) from InvestmentTransaction
      → monthly_return_series() via Modified Dietz
      → benchmark returns from PriceHistory (keyed by InvestmentSettings.benchmark_security_id)
      → compute_risk_metrics(): beta, alpha, R², Sharpe, volatility, max drawdown (requires ≥12 months)
      → xirr(): money-weighted annualized return
      → decompose_return(): contributions + income + price appreciation
  → frontend: stat tiles (TWR, XIRR, benchmark), decomposition row, risk metrics grid, monthly returns table
```

### Holdings CSV Import (Fidelity, extensible)
```
Import:
  → file drop or picker (.csv) → POST /api/investments/import/holdings-csv
      → parse_holdings_csv(): detect brokerage from headers (Fidelity first)
      → per row: resolve Security by symbol (create if new),
        resolve Account by account_number → name → create
      → upsert PositionSnapshot (account_id + security_id + as_of),
        record PriceHistory per security
  → response: counts (snapshots created/updated, securities, accounts, prices)
```

## API Routes

| Prefix | Key endpoints |
|---|---|
| `/api/accounts` | CRUD, `POST /merge` |
| `/api/categories` | CRUD (flat list, tree built client-side from parent_id) |
| `/api/transactions` | CRUD, `PUT /:id/line_items`, `POST /categorize`, `POST /apply-categories`, `POST /:id/confirm-category` |
| `/api/budgets` | CRUD, `GET /status`, `GET /suggestions`, `GET /income-summary`, `GET /unbudgeted-spend`, `GET /comparison`, `POST /seed` |
| `/api/merchants` | CRUD, `GET /search?q=` |
| `/api/receipts` | `POST /` upload, `GET /:id/image`, `POST /:id/process`, `GET /:id/ocr-preview`, `POST /:id/to-transaction`, `POST /:id/review-to-transaction` |
| `/api/rules` | CRUD, `POST /preview`, `POST /reindex` |
| `/api/transfers` | `POST /detect`, `GET /`, `GET /:pair_id`, `POST /link`, `DELETE /:pair_id` |
| `/api/ask` | `POST /` (RAG), `POST /reindex` |
| `/api/import` | `POST /qif`, `POST /qfx`, `POST /confirm` |
| `/api/export` | `GET /qif` |
| `/api/auth` | `GET /needs-setup`, `POST /setup`, `POST /login`, `POST /logout`, `GET /me` |
| `/api/investments` | `GET /overview`, `GET /holdings`, `GET /performance`, `POST /import-qif`, `POST /import/holdings-csv`, `POST /benchmark/refresh`, `POST /risk-free-rate/refresh`, `GET /accounts`, lot rebuild, analytics |
| `/api/statement-scans` | `POST /` upload, `GET /:id`, `GET /:id/file`, `GET /:id/preview`, `POST /:id/reprocess`, `POST /:id/materialize` |

## Query Cache Keys

Mutations invalidate these TanStack Query keys to keep the UI in sync:

| Key | Invalidated by |
|---|---|
| `["transactions", ...]` | create/update/delete txn, replace line items, apply categories, confirm category |
| `["budgets", ...]` | create/update/delete budget, seed, create/delete txn, replace line items |
| `["categories"]` | create/update/delete category |
| `["merchants", ...]` | create merchant |
| `["accounts"]` | create account |
