# Learnings

Decisions, gotchas, and non-obvious implementation details accumulated during the build. Each phase adds a section so future sessions don't re-discover the same things.

---

## Phase 1 — Bootstrap

- Chose `uv` for Python dependency management but the dev machine doesn't have `uv` installed globally; `pip install -e ".[dev]"` works as the fallback.
- Vite proxy (`/api` → `localhost:8000`) is the only glue between frontend and backend during dev; no CORS config needed.
- `vite-plugin-pwa` is included from day one but the service worker is minimal — just an offline shell. Real offline support is deferred to phase 9.

## Phase 2 — DB & Models

- All money is `BigInteger` cents. No floats anywhere in the money path — this is enforced at schema, model, and component level (`MoneyInput` rounds to integer cents on every change).
- `Base` provides `id`, `created_at`, `updated_at` automatically. Every model inherits these; no model defines its own PK.
- SQLAlchemy `selectin` lazy loading is used on all FK relationships (merchant, category, receipt on Transaction; category on LineItem). This prevents N+1 queries within a single request but means every query eagerly loads related objects whether you need them or not. Acceptable at personal scale.
- The single Alembic migration creates all tables in one shot. Future schema changes need incremental migrations — don't regenerate from scratch.

## Phase 3 — Auth

- Single-user, session-cookie auth using `itsdangerous` signed tokens. No JWT, no refresh tokens, no RBAC. The cookie is named `session`.
- The `/api/auth/setup` endpoint is one-shot: creates the user and auto-logs-in. After that it returns 409. There is no password-reset flow.
- Test fixtures use `client.post("/api/auth/setup", ...)` to bootstrap auth in every test file's fixture. This pattern must be copied into new test files.

## Phase 4 — Categories & Budgets

- Categories are hierarchical (self-referencing `parent_id` FK). Cycle detection walks the parent chain in Python, not via DB constraint. This is fine at expected category counts (<100) but wouldn't scale to thousands.
- `get_budget_status` joins `line_items` through `transactions` to sum spending per category. This is the real spending query — it uses `posted_at` date range filtering on the transaction, not the line item.
- Budget periods are validated as string literals (`monthly` | `weekly`). There's no enum at the DB level — just a service-layer check.

## Phase 5 — Transactions & Splits

### Key decisions

- **Whole-set replacement for splits.** `PUT /api/transactions/{id}/line_items` deletes all existing line items and re-creates them atomically. This avoids the complexity of per-item add/edit/delete endpoints and their ordering/conflict edge cases. The frontend always sends the complete split set.
- **Auto-Uncategorized.** When a transaction is created without `line_items`, the service creates a single line item for the full amount under an "Uncategorized" category (auto-created if missing). This means every transaction always has at least one line item — the budget status query doesn't need special-casing.
- **Merchant normalization.** `normalized_name` is `.strip().lower()` of the display name. Search uses SQL `LIKE` on the normalized column. No stemming, no fuzzy matching. Good enough for personal use; may need revisiting for receipt-OCR merchants with inconsistent names.
- **Merchant learning threshold = 3.** After a merchant has 3+ transactions, the most-common category across all their line items is set as `default_category_id`. The learning runs after every transaction create and every line-item replace — it's re-evaluated each time, not incremental.
- **Transaction status lifecycle:** `pending` → `split` (set automatically when >1 line item is saved) → `final` (not yet used; reserved for Quicken reconciliation). The status toggles back to `pending` if you replace splits with a single item.

### Non-obvious implementation details

- The `list_transactions` endpoint returns `{items, total}` (not a bare list) to support pagination. All other list endpoints return bare arrays — this inconsistency is intentional since only transactions are expected to grow large enough to need pagination.
- Category filtering on the transaction list uses a subquery: `WHERE id IN (SELECT transaction_id FROM line_items WHERE category_id = ?)`. This means filtering by category scans line_items. No index on `(category_id, transaction_id)` exists yet — add one if this gets slow.
- The `TransactionRead` and `TransactionDetail` schemas are separate: list returns `TransactionRead` (no line items), detail returns `TransactionDetail` (with line items). This avoids loading all splits for the list view.
- `MerchantRead` includes `default_category_name` as a computed field from the `selectin`-loaded relationship. Same pattern for `merchant_name` on `TransactionRead`.

### What tests don't cover

- **No frontend tests for phase 5.** The Transactions page, SplitEditor, and MerchantCombobox have zero test coverage. The only frontend test in the repo is `Home.test.tsx` from phase 1.
- **No test for the "Uncategorized" category idempotency.** The auto-creation of the Uncategorized category is tested implicitly (the transaction-without-splits test passes), but there's no test that creating two transactions without splits reuses the same Uncategorized category rather than creating a duplicate.
- **No test for concurrent split replacement.** Two simultaneous `PUT` calls to the same transaction's line_items could race. SQLite's write lock likely prevents corruption, but the test suite doesn't verify this.
- **No test for cascade delete behavior.** Deleting a transaction deletes its line items (via explicit `DELETE` in the service), but deleting an account with transactions, or a category referenced by line items, is untested and would likely fail with an FK constraint error.
- **No test for merchant learning with mixed categories.** The test only checks that 3 transactions with the same category sets the default. It doesn't test the "most common" tiebreaker when a merchant has mixed category usage.
- **No test for pagination.** The offset/limit logic in `list_transactions` is exercised only with 2 records. Edge cases (offset beyond total, limit=0) are untested.
- **No auth enforcement test for new endpoints.** The auth tests only verify categories require auth. Accounts, merchants, and transactions endpoints are assumed protected by the router-level `dependencies=[Depends(current_user)]` but this isn't explicitly tested.
- **Budget status integration with real transactions is only tested in `test_budgets_api.py`** using direct model insertion, not through the transaction API. No test verifies that creating a transaction via POST actually shows up in budget status.
