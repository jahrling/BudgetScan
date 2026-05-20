# Assumptions

Every assumption currently baked into the codebase that has not been validated against real data, real hardware, or real usage patterns. Each should be validated or removed before relying on the behavior it enables.

---

## Data scale

- **Transaction volume fits SQLite comfortably.** The app assumes hundreds to low-thousands of transactions per year. No write-ahead log tuning, no connection pooling, no read replicas. If a household generates >10k transactions/year (e.g., via Quicken import of all bank transactions), query performance is unvalidated.
- **Line items per transaction stay small.** The split editor loads all line items into React state as an array and re-sends the full set on save. A receipt with 50+ line items (e.g., a long Costco receipt) has not been tested for UI responsiveness or payload size.
- **Category count stays under ~100.** The CategoryPicker renders all categories in a flat `<select>` with indentation. The cycle-detection walk is O(depth). Neither has been tested with deep hierarchies or wide flat lists.
- **Merchant count stays under ~1000.** Merchant search uses SQL `LIKE '%query%'` with no full-text index. This will do a full table scan on every keystroke (debounce-free).

## Money representation

- **All amounts are positive integers (cents).** The schema and UI both treat `amount_cents` as a positive number. Negative transactions (refunds, credits, income) are not handled — no test, no UI affordance, no sign convention established. This will need a decision before Quicken import.
- **Single currency (USD).** The Account model has a `currency` field defaulting to `"USD"` but nothing in the transaction or budget logic respects it. Multi-currency math is completely absent.
- **Integer cents are sufficient precision.** No sub-cent amounts. This is fine for consumer transactions but would break for things like per-unit gas prices ($3.459/gal) if unit_price_cents is ever displayed or used in calculations.

## Authentication & security

- **Single user only.** Every endpoint requires `current_user` but no endpoint filters data by user. If a second user were created (not possible via UI, but possible via direct DB insert), they'd see all data. The model is "single-user app" not "multi-tenant with one user."
- **Session cookie security is adequate for LAN.** The cookie is signed but not encrypted, has no explicit `Secure` flag, no `SameSite` attribute set, and no CSRF protection. Assumed safe because the app runs on a home LAN. This assumption breaks the moment zero-trust remote access is added.
- **No rate limiting.** Login, setup, and all API endpoints are unlimited. An attacker on the LAN could brute-force the password.

## Merchant learning

- **The ≥3 transaction threshold is a guess.** The learning threshold was chosen without data. With real usage, 3 transactions might be too few (leading to premature/wrong defaults) or too many (user has to manually categorize 3 times before it kicks in). Needs validation against actual spending patterns.
- **Most-common category is the right heuristic.** The learning picks the category with the most line items across all transactions for a merchant. It doesn't weight by recency, amount, or user-modified flag. A merchant where you buy groceries 10 times then start buying gas would keep suggesting Groceries until gas overtakes it.
- **Learning runs on every save.** `maybe_update_default_category` re-queries the full history on every transaction create and every split save. At personal scale this is fine but it's O(all_line_items_for_merchant) each time.

## Mobile / PWA

- **iPhone Safari is the primary browser.** The UI is designed mobile-first for iPhone. Android Chrome, desktop browsers, and iPad have not been tested. The bottom nav uses `safe-area-pb` for iPhone home indicator but the actual inset behavior hasn't been validated on a real device.
- **Touch targets are large enough.** The split editor uses standard Tailwind sizing (h-10 inputs, text-sm). One-thumb usability on a real iPhone SE (smallest current screen) has not been tested. The "Remove" button on split items is small text, not a proper touch target.
- **PWA install works from Safari.** `vite-plugin-pwa` generates a manifest and service worker, but the install-to-home-screen flow has never been tested on a real iPhone. Safari PWA behavior is notoriously quirky (no push notifications, limited background sync, different cookie handling).
- **No offline support.** The app assumes constant LAN connectivity. The service worker caches the shell but not API responses. Opening the app with the server unreachable shows a broken UI, not a useful offline state.

## Backend runtime

- **Python 3.11+ features are available.** Type syntax uses `X | None` (3.10+) and other modern Python. The dev machine has 3.13; the Docker image target hasn't been validated.
- **SQLite async via aiosqlite is reliable.** The app uses `aiosqlite` which wraps synchronous sqlite3 in a thread. Under Uvicorn's single-worker default, concurrent requests serialize at the DB level. This hasn't been stress-tested.
- **The `data/` directory exists and is writable.** The backend expects `data/finance.db` relative to CWD. In Docker this is a mounted volume; in dev, the directory must be manually created. There's no startup check or helpful error message — it just crashes with `sqlite3.OperationalError: unable to open database file`.

## Transaction model

- **Transactions are always expenses.** The UI and backend don't distinguish between debits and credits. Amount is always positive with no sign. Income, transfers between accounts, and refunds have no representation.
- **posted_at is a full datetime with timezone.** The frontend sends ISO strings and the date picker only captures a date (no time). The time component defaults to midnight in the browser's local timezone. Filtering by date range may miss or include transactions at day boundaries depending on timezone offset.
- **Status values are unenforced strings.** The status field accepts any string — `pending`, `split`, `final` are conventions, not constraints. A typo in status (e.g., from a future API caller) would silently succeed.
- **Deleting a transaction hard-deletes.** No soft delete, no trash, no undo. The line items are explicitly deleted first, then the transaction. There is no audit trail.

## Quicken interop (future phases)

- **QIF format will be sufficient.** The architecture assumes QIF as the interchange format with Quicken. QIF is ancient and lossy — it doesn't support split categories well in all Quicken versions. This hasn't been validated against a modern Quicken import.
- **Bank transaction matching is solvable.** Phase 8 assumes imported bank transactions can be matched to manually-entered receipt transactions. The matching strategy (by date + amount? by Quicken ID?) hasn't been designed.

## OCR (Phase 6 — now active, still mostly untested)

- **16GB VRAM is enough for Qwen2.5-VL-7B.** The architecture doc states this but it hasn't been tested on the target hardware. Quantization level (Q4 assumed) and actual memory footprint with real receipt images are unvalidated.
- **Receipt photos will be well-lit and readable.** The OCR pipeline assumes phone camera photos of receipts. Crumpled, faded, or thermal-printed receipts haven't been considered.
- **`qwen2.5vl:7b` returns the JSON shape our prompt asks for.** Prompt requests `{merchant, date, total, subtotal, tax, items[]}`. No real receipt has been run through the model in CI — tests mock the OCR layer entirely. The `_to_cents` helper tolerates string→float coercion ("$12.34"), but unknown/renamed keys silently drop.
- **Ollama's `format=json` flag actually returns valid JSON.** Version-dependent. `extract_json` falls back to fence stripping + greedy `{...}` matching, with one retry. A model that returns prose-wrapped JSON twice in a row produces `OCRError` → receipt status `failed`.
- **Vision/text timeout = 120s.** Covers cold model loads (~30s+ for weights) plus inference. Marginal on slow GPUs.
- **Receipt items sum to approximately `total`.** The reconciler accepts ±$1 drift via a balancer "Tax / rounding" line. Larger unexplained drift collapses to a single Uncategorized line for the whole total. Multi-tax receipts, post-total tips, or item-level discounts not folded into `amount` will hit the fallback path and lose item-level detail.
- **The user's category tree is informative enough for the categorizer.** The text categorizer sends every category in the DB. If categories are sparse or generic, suggestions degrade — but the fallback chain (merchant default → Uncategorized) keeps the flow usable.
- **In-process categorizer cache is fine.** Survives only until the Uvicorn process restarts. Multi-worker deployments would each maintain their own cache. Not relevant at single-user scale.

## Mobile capture (Phase 6)

- **`<input type=file accept=image/* capture=environment>` opens the back camera on iPhone Safari.** True for iOS 14.5+ but unverified on the target device. Desktop falls back to a file picker.
- **XHR upload-progress events fire in all target browsers.** Drives the upload % UI. Safari/iOS support has been stable for years but isn't tested here.
- **10 MB upload cap is enough.** Modern iPhone photos are 2–4 MB JPEG/HEIC. Burst frames or PNG screenshots could push past it; the server returns 413 with a clear message.
- **Background-task OCR finishes within the 60s frontend polling window.** Warm Qwen2.5-VL-7B on a strong GPU clears this. Cold loads on weaker GPUs may not. After 60s the UI offers "Keep waiting" or "Enter manually."
- **Polling at 2s is gentle enough at single-user scale.** No exponential backoff, no rate-limit, no debounce. With one user this is ~30 hits per OCR; trivial. Would need rethinking at multi-user scale.
