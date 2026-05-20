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

## Phase 7 — Mobile dashboard & PWA polish

### Key decisions

- **One round-trip for the dashboard.** Above-the-fold data comes from a single `GET /api/budgets/status?period=current_month` call. Below-the-fold sections fetch separately so the FCP isn't blocked. The status response was extended to carry everything the card needs (`budget_id`, `category_icon`, `category_color`, `days_remaining`, `percent_remaining`, `is_pinned`, `period_start`, `period_end`) so the dashboard never has to join client-side.
- **Top-N ranking is pure client-side.** Pinned budgets first, then sort by absolute `remaining_cents` desc, take top 6. This avoids a "sort key" round trip and lets the user re-prioritize instantly by tapping the pin on `/budgets`.
- **`is_pinned` migration uses `batch_alter_table`.** SQLite doesn't support `ALTER TABLE ADD COLUMN ... NOT NULL DEFAULT` directly via Alembic without batch mode. `server_default="0"` makes existing rows valid without a backfill step.
- **Color thresholds are based on percent remaining, not percent used.** Green > 50%, amber 20–50%, red < 20%, gray for over-budget. Inverting the polarity made the bars match the user's mental model ("how much can I still spend").
- **Service worker uses two strategies.** `/api/budgets/status` is `StaleWhileRevalidate` so the dashboard paints instantly from cache even if the LAN is briefly unreachable. Every other `/api/*` request is `NetworkFirst` with a 4s timeout so writes don't get cached and stale data only appears when truly offline. App shell (`index.html` and built assets) is precached via Workbox.
- **Routes are code-split with `React.lazy`.** Home stays eager (it's the entrypoint); Budgets, Transactions, Categories, ReceiptProcessing, and Login are dynamic imports. `manualChunks` in `vite.config.ts` carves out React, TanStack Query, and the forms stack so the initial bundle is small.
- **iOS install tip is a one-time banner.** Safari doesn't fire `beforeinstallprompt`, so the app shows a manual "tap Share → Add to Home Screen" toast 1.2s after first paint, gated on `localStorage["finance.installPromptDismissed"]`. Detection uses `navigator.standalone` (iOS) + the `display-mode: standalone` media query (every other browser).
- **Icons and splash images are generated by Python scripts.** `scripts/generate-icons.py` and `scripts/generate-splash.py` use Pillow to emit the iOS apple-touch-icon, Android 192/512 (regular + maskable), and four iPhone launch image sizes. Keeping the source as code means restyling is one font-and-color edit away.

### iOS quirks worth remembering

- **`apple-mobile-web-app-status-bar-style: black-translucent` requires `viewport-fit=cover`** in the viewport meta and `env(safe-area-inset-*)` padding on fixed nav. Without `viewport-fit=cover` iOS ignores the status-bar style and leaves a white strip.
- **Maskable icons are full-bleed by design.** The Pillow icon script paints the background to the edges and pulls the glyph into the central 80% safe area; the regular variant uses rounded corners. iOS auto-masks `apple-touch-icon.png`, so it's a plain opaque square.
- **`<input type="file" capture="environment">` only fires the camera when the page is served over HTTPS** (LAN dev over plain HTTP downgrades to a file picker). The Caddy TLS setup from Phase 1 covers this in prod.
- **iOS Safari does not fire `beforeinstallprompt`** and does not support push notifications for installed PWAs (out of scope per the brief).
- **`navigator.standalone` is iOS-only and TypeScript doesn't type it** — cast through `unknown` to avoid `@ts-expect-error`.
- **Service worker cache hits for `/api/budgets/status` survive across cold launches**, which means the first paint after re-opening the PWA can render real numbers before the network responds. The `expiration.maxAgeSeconds: 86400` cap stops stale-day-old data from sticking around forever.

### What's still untested

- **No real-iPhone screenshot in this commit.** Validation against a physical device, including the install-to-home-screen flow, the launch image on cold start, and the FAB safe-area inset, needs to happen on the user's hardware before this is considered "done."
- **No frontend tests for the dashboard's data wiring.** `Home.test.tsx` only checks the heading and FAB render; the budget-card sorting, the merchant aggregation, and the week-window logic have no assertions.
- **No backend test for the new `is_pinned` field.** The migration and the schema fields are typed but unverified — needs a test that creates a budget with `is_pinned=true`, reads it back via `GET /api/budgets/status`, and asserts pinned-first ordering once the UI relies on it.
- **The performance target (FCP < 1.5s on cold-cache iPhone over LAN) is unmeasured.** Code-splitting and the precache should make it achievable, but the actual number depends on bundle sizes and server speed.

## Phase 8 — Quicken interop

### Key decisions

- **Hand-rolled OFX 1.x tokenizer, no library.** QFX is OFX SGML preceded by a
  text header. The subset we actually consume (`ACCTID`, `CURDEF`, `STMTTRN`,
  `DTPOSTED`, `TRNAMT`, `FITID`, `NAME`/`MEMO`) is trivial to walk with a regex
  that tolerates unclosed value tags. Avoiding `ofxparse` or `ofxtools` keeps
  the dep surface zero — important since this code path is exercised maybe
  once a week.
- **Stateless confirm endpoint.** Parse results are sent to the client and
  echoed back into `/api/import/confirm`. No server-side session/staging
  table — the import button on the UI is the only consumer and a quick page
  refresh resets everything. Saves a model + migration we don't need.
- **Match heuristic is `account + amount + same day` for duplicates and
  `account + amount + ±2 days + has-receipt` for receipt merges.** The two
  rules are evaluated in that order, so a same-day receipt-attached txn
  reports as `duplicate` (default Skip) rather than `matched-receipt`. This
  is intentional — if the day already matches, Quicken's data and ours
  already agree on the date, no merge is needed.
- **Merge action sets `status='final'` and copies `quicken_id` onto the
  existing receipt-entered transaction.** No new row is created. This is how
  receipts get their bank-side FITID; the splits the user already entered
  stay untouched.
- **Currency mismatch is a per-statement hard error.** When QFX `CURDEF`
  disagrees with the mapped account's `currency`, every transaction in that
  statement is skipped and an error is logged. A single bad row never aborts
  the whole import — errors collect per-row in `ParseResult.errors`.
- **`create_missing_categories` defaults to off.** Per the brief: missing
  categories on import should error so the user is aware. The checkbox on
  the import page flips it to true and any unknown colon-path is created as
  a single flat category whose name is the full path (Quicken's convention).
- **QIF account block uses display name as the key.** Quicken's QIF
  `!Account` block carries the human-readable account name (`Main Checking`),
  not a stable id. We try to match on `quicken_id` first, then fall back to
  `Account.name`. Users still get prompted to map if neither matches.
- **`_amount_to_cents` does string arithmetic, not float.** `12.345` is
  rejected; `12.34` and `1,234.56` parse exactly. Float-then-round drops
  cents on values like `0.05` on some platforms — string math avoids the
  whole class of bug.
- **Export emits both a primary `L<category>` and a full `S` split block,
  even for single-line transactions.** Quicken accepts both; emitting the
  splits unconditionally makes the QIF round-trip lossless when the same
  file is re-imported into the app.

### Non-obvious implementation details

- **`Account.quicken_id` is the join key for QFX.** It maps to OFX `ACCTID`.
  The import UI lets you patch it onto an existing account when the file
  references an unmapped id — that PATCH persists so the next import doesn't
  re-prompt.
- **`_ofx_strip_header` finds the first `<OFX` tag and treats everything
  before it as the SGML header.** Some banks emit Windows line endings and
  charset headers; this just skips past the lot.
- **`_parse_ofx_datetime` ignores the TZ suffix.** OFX dates like
  `20240315[-5:EST]` get truncated to `20240315`; we treat all imported
  dates as UTC midnight since the app's own posted_at semantics already
  collapse to a date for budgeting.
- **QIF round-trip is verified end-to-end in
  `test_qif_roundtrip_preserves_splits`.** Import → confirm with
  create-missing → export → re-import — assertion is that the two parsed
  candidate lists are equal once normalized to `(amount, description,
  sorted(splits))` tuples.

### What tests don't cover

- **No frontend tests for `/import` or `/export`.** The pages mount React
  Query + multipart upload + a downloadable link target; none of that has a
  Vitest case. The only frontend test in the repo is still `Home.test.tsx`.
- **No real Quicken-exported QFX has been validated.** Tests use hand-built
  fixtures that exercise the OFX subset we care about; bank-specific quirks
  (e.g., Chase's inline `<MEMO>...</MEMO>` blocks, Vanguard's nested
  `INVSTMTRS`) haven't been seen.
- **No test for the actual round-trip into and out of Quicken itself.**
  The reconciliation workflow in README.md is documented but unverified
  against a real Quicken installation.
- **No test for the unmapped-account UI flow.** The backend marks unmapped
  ACCTIDs, the frontend lets you map or create — but there's no
  integration test that re-importing the same file after mapping resolves
  cleanly.
- **No test for very large files.** Parsing is single-pass regex so it
  should be fine into the tens of MB, but no benchmark exists.
- **No test for `merge-with:<id>` outside the same-day duplicate path.** The
  test suite exercises `create` and `skip`; the merge branch is logically
  covered by `match_status='matched-receipt'` annotation but the end-to-end
  POST flow that ships `merge-with:<id>` and then asserts the target txn
  has `status='final'` and the new `quicken_id` is missing.
- **No test for the `create_missing_categories=False` failure mode.** The
  default is False (per the brief: "error so user is aware") but tests only
  exercise the True path. A QIF with an unknown colon-path under the
  default setting should surface in `result.errors` — currently
  unverified.
- **No test for the QFX→QFX round-trip.** We test QIF round-trip but
  there's no export-as-QFX, so an inbound QFX → confirm → outbound QIF →
  re-import path may quietly drop fields like `FITID` reuse semantics if
  the user re-imports the same week twice.

## Phase 9 — Hardening & deploy

### Storage philosophy

- **Receipt images never accumulate locally.** Local `data/receipts/` is a staging buffer. The flow is: upload → OCR writes JSON to SQLite → upload image to Dropbox → verify content_hash → delete local file. The JSON in SQLite is the permanent operational record; the Dropbox image is the audit trail. If Dropbox is offline, the local file is *kept* and the hourly cron retries — never silently discarded.
- **Dropbox content_hash is computed in 4 MiB blocks.** Not a plain sha256 — see `dropbox_content_hash()`. Verification compares the API's `content_hash` from `files_get_metadata`. The receipt's row stores `dropbox_path` after a successful verify; `NULL` means "pending or failed."
- **Purge is dry-run by default.** `purge_old_receipts(months=36, confirm=False)` only lists what *would* go. Real deletes require an explicit operator call with `confirm=True` — there is no automated purge.

### Config & env

- **`APP_ENV=production` is the master switch.** Required secrets (`SECRET_KEY`, `DROPBOX_ACCESS_TOKEN`) fail-fast at startup only when `APP_ENV=production`. Tests + dev runs keep working with empty defaults. The same flag turns on `Secure + SameSite=Strict` cookies and CSRF enforcement.
- **Env-var aliases for renamed keys.** `OLLAMA_BASE_URL` and `RECEIPT_STAGING_DIR` are the documented names in `.env.example`; the old `OLLAMA_URL` / `RECEIPTS_DIR` still work. `model_post_init` copies the alias into the legacy field so existing call sites (`settings.ollama_url`, `settings.receipts_dir`) are unchanged.

### Security

- **CSRF is double-submit cookie + `X-CSRF-Token` header.** Middleware enforces on every state-changing `/api/*` request **only when `APP_ENV=production`** so the test suite (which doesn't echo the token) keeps passing. Exempt routes: `/api/auth/setup`, `/api/auth/login`, `/api/auth/needs-setup` (no session cookie yet on first request). The `csrf_token` cookie is non-HttpOnly by design so the SPA can read it.
- **Login rate limit is per-process, in-memory.** A `deque` of timestamps per IP, 5/min. Reset on container restart. Good enough for a single-user LAN app; would need Redis if ever multi-process.
- **Image validation is Pillow `verify()` on the raw bytes** *before* writing to staging. Catches corrupt uploads and non-images with a clean 400. `verify()` is destructive on the stream — we don't reuse the object after, so no re-open needed.

### Reverse proxy

- **Caddy's admin API is bound to `0.0.0.0:2019`** so phones on the LAN can fetch the root CA cert at `http://<server-ip>:2019/pki/ca/local/certificate`. Default binding is `127.0.0.1:2019` which would 404 from any other host. This is fine for LAN-only deployment but **must** be removed if Caddy is ever exposed outside the LAN.
- **`tls internal` is the LAN-only mode.** When zero-trust ingress is added later, swap Caddy out; the app needs no changes because the session cookie still works the same and `APP_ENV=production` already forces Secure cookies.
- **The prod compose profile is opt-in.** `docker compose up` keeps the dev experience: backend on :8000, frontend on :80, no TLS. `docker compose --profile prod up -d` adds the Caddy service and removes the need to expose backend/frontend ports directly (though they remain exposed for ops convenience).

### Background jobs

- **The cron scripts shell into the running backend container.** They run `python -m finance.scripts.sync_pending` / `backup_db` inside the same environment that has `.env` and the SQLite volume mounted. This avoids duplicating env loading in shell scripts.
- **DB backup is a `shutil.copy2` of the live SQLite file.** At personal scale, hot-copying SQLite is reliable enough — there is no `.backup` API call. If write contention ever becomes a concern, switch to `sqlite3 .backup` against the live DB.
- **Backup retention is hash-sorted, server-modified-time-sorted on Dropbox.** `prune_old_backups(keep=30)` lists, sorts desc by `server_modified`, deletes everything past index 30.

### Observability

- **JSON logging is opt-in via `python-json-logger`.** Falls back to plain `basicConfig` if the package isn't installed — keeps test environments friction-free. Uvicorn's three loggers (`uvicorn`, `uvicorn.access`, `uvicorn.error`) are explicitly rewired so the access log is also JSON.
- **`/api/admin/stats` is auth-gated but not role-gated.** Single-user app, so any authenticated user sees it. If multi-tenancy is ever added, this endpoint needs a role check.