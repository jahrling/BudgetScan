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

## Phase 6 — Receipt OCR

### Key decisions

- **Ollama is called via `/api/generate` with `format=json`**, not the OpenAI-compatible `/v1/chat/completions` endpoint. `format=json` makes the model emit strict JSON without code fences in practice, but `extract_json` still strips fences and falls back to greedy `{...}` extraction in case the model ignores the format hint. One retry on parse failure.
- **Vision model is `qwen2.5vl:7b`; text categorizer is `qwen2.5:7b`.** Both configurable via env (`OLLAMA_VISION_MODEL`, `OLLAMA_TEXT_MODEL`). Set in `config.py`.
- **Pillow preprocessing always re-encodes as JPEG q=90 with long edge ≤ 2048px.** EXIF rotation is applied first (`ImageOps.exif_transpose`) so iPhone portraits don't go to the model sideways. Non-RGB inputs (HEIC, PNG with alpha) are converted to RGB.
- **Storage layout is `data/receipts/<yyyy>/<mm>/<sha256><ext>`**, dedupe is by SHA-256. Re-uploading the same image returns the existing row unchanged — `created=False`, no re-OCR triggered. Original file extension is kept when it's a recognized image type, otherwise content-type sniff → `.jpg` fallback.
- **Background OCR uses FastAPI `BackgroundTasks`** and opens its own session via the module-level `async_session_factory`. No Celery, no Redis. Tests monkeypatch `routers.receipts.async_session_factory` to the in-memory test factory so background work hits the right DB.
- **Categorizer is best-effort and cached in-process.** Cache key is `(normalized_description, category_set_hash)`. The category-set hash invalidates the cache automatically when categories are added/renamed. On any LLM error the categorizer falls back to merchant `default_category_id`, then to `Uncategorized` — it never raises.
- **`/to-transaction` reconciles drift with a single balancer line.** If parsed items sum within ±$1 of `total`, the difference becomes a "Tax / rounding" line under Uncategorized. If they're off by more than $1 (and the drift isn't explained by the reported tax), the items are discarded and a single Uncategorized line for the full total is created instead — guarantees `sum(line_items) == amount_cents` so the existing Phase 5 invariants hold.
- **Status mapping:** uploaded receipt = `pending`; OCR success = `done`; OCR failure = `failed` with `ocr_error` truncated to 500 chars. The router endpoint `POST /process?force=true` resets to `pending` and re-queues.

### Non-obvious implementation details

- **`SnapReceiptButton` uses XHR, not `fetch`.** Browser `fetch` does not surface upload-progress events; XHR does. Returns a typed `Receipt` on success.
- **The Snap button reuses one `<input type=file capture=environment>` per render.** Hidden, programmatically clicked. Always resets `e.target.value = ""` after a pick so the same file can be re-selected.
- **`ReceiptProcessing` polls via TanStack Query's `refetchInterval`** — it doesn't run its own timer. The query returns `false` for the interval once status is non-pending, which stops polling automatically.
- **Auto-to-transaction is account-gated.** If the user has exactly one account, it's selected silently; otherwise the processing screen blocks on an account picker once OCR is done.
- **Manual fallback wires through `?manual=<receipt_id>` on the Transactions route.** This opens the Add Transaction dialog pre-attached to the receipt; the dialog shows a thumbnail of the image so the user can transcribe by eye.
- **The split-editor navigation uses `?open=<txn_id>`.** Transactions.tsx reads it on mount, sets `selectedId`, and strips the param via `setSearchParams(..., {replace: true})` so back-button behaves.
- **`apiFetch` does not parse error JSON.** The receipt upload path uses XHR directly so it can surface the FastAPI `detail` field (e.g. "Receipt image exceeds 10 MB limit") on 4xx — a small divergence from the rest of the codebase where errors are just `HTTP <status>`.

### What tests don't cover

- **No real Ollama integration test.** OCR is mocked at `services.ocr.ocr_receipt_file`. The actual JSON shape that `qwen2.5vl:7b` returns hasn't been validated by code — the prompt is best-guess and only loosely constrained by `format=json`.
- **No frontend tests for the receipt flow.** SnapReceiptButton, ReceiptProcessing, and the manual-fallback wiring are untested. The only frontend test remains `Home.test.tsx`.
- **No test for >10MB upload at the HTTP layer with a real ASGI client.** The 413 test patches `max_receipt_upload_bytes` down to 100 to keep test images small.
- **No test for the categorizer cache.** The `_CACHE` dict is process-scoped; `clear_cache()` exists for tests but no test verifies that two consecutive identical descriptions hit the cache instead of the LLM.
- **No test for `force=true` actually re-running OCR.** The test triggers initial processing via `?force=true` for determinism; the "skip if already done" path is exercised only implicitly.
- **No test for storage path layout.** The yyyy/mm/sha256 layout is asserted only via the side effect that the file is readable; the path structure itself is not validated.

---

## Human-loop testing required

Things the automated suite and the stubbed-OCR smoke run (`backend/scripts/smoke_*`) can't validate. These need a person, real hardware, or a real receipt. Carry this list forward across phases — append, don't overwrite.

### Phase 6 — Receipt OCR

| # | What to verify | Why automation can't | How to test |
|---|---|---|---|
| H-6.1 | `qwen2.5vl:7b` returns the JSON shape our prompt asks for on a real receipt photo | OCR is mocked in every test; the prompt is best-guess | `ollama pull qwen2.5vl:7b`, run the real stack, snap a real receipt, inspect `receipts.ocr_raw_json` |
| H-6.2 | Cold-load + inference fits inside the 60 s frontend polling window on the target GPU | Depends on hardware (assumption #23) | First snap after `ollama serve` starts; watch the "Processing…" elapsed timer |
| H-6.3 | `qwen2.5:7b` categorizer suggestions are useful in practice (not just non-null) | Quality is subjective | Snap 5+ receipts across different merchants, count how many lines you have to re-categorize |
| H-6.4 | iPhone Safari opens the back camera on tap (not the file picker / front camera) | Browser-specific, device-specific | Install PWA on actual iPhone, tap **Snap receipt** on Home |
| H-6.5 | Photographed receipt orientation is corrected by `ImageOps.exif_transpose` | Depends on actual iPhone EXIF tags | Photograph a receipt in portrait, then landscape; confirm both OCR correctly |
| H-6.6 | Thermal-paper / faded / crumpled receipts produce usable output (or fail cleanly) | No corpus of bad receipts in CI | Try a fading CVS receipt, a crumpled gas receipt, a long Costco receipt |
| H-6.7 | The split editor renders well on iPhone SE (smallest current screen) — touch targets, scrolling, "Remove" affordance | Untested per assumption #35 | Open a 10+ line receipt on a real iPhone SE |
| H-6.8 | PWA install-to-home-screen works from Safari and the camera flow survives standalone mode | iOS PWA quirks per assumption #18 | Add to home screen, open from icon, try **Snap receipt** |
| H-6.9 | Re-categorization persists through QIF export later (Phase 8 cross-check) | Cross-phase | Defer until Phase 8 is done; revisit then |
| H-6.10 | 60 s timeout escape hatch reaches the manual-entry fallback with the receipt attached | UI flow; hard to assert without a real slow Ollama | Stop `ollama serve` mid-poll, wait 60 s, confirm "Enter manually" → Add dialog shows the image |
| H-6.11 | Ollama's `/api/generate` with `format=json` doesn't wrap output in prose on this model + version | Model-version-dependent | Add a debug log of raw `response` in `ocr.py` for one snap, eyeball it |

### Backlog from earlier phases (still open)

| # | What to verify | Notes |
|---|---|---|
| H-1.1 | Docker Compose stack starts cleanly on the home server (not just `docker compose build`) | Assumption #2 / #4 — GPU passthrough only works on native Linux |
| H-1.2 | Caddy / reverse-proxy setup once Phase 9 lands | Currently `secure=False` cookies; flips at Phase 9 |
| H-3.1 | 30-day session cookie actually expires after 30 days | Untested per LEARNINGS Phase 3 |
| H-3.2 | Single-user `/setup` 409 enforcement under concurrent requests | Race window noted in Phase 3 gaps |
| H-4.1 | Overlapping monthly budgets for the same category — observe the double-count and decide whether to constrain | Assumption #12 |
| H-5.1 | Costco-length receipt (50+ line items) doesn't choke the SplitEditor | Assumption #2 of Phase 5 |
| H-5.2 | Backend behavior when deleting an account or category that's referenced by line items | Phase 5 test gap |

### How to use this list

When you sit down to do real-device testing, work top-down. Append a date + outcome next to each item as you verify it. When something fails, file it back as a code change rather than leaving it on the list. The list shrinks over time; phases past close out their rows but stay visible so we don't repeat them.
