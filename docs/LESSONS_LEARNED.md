# BudgetScan — Lessons Learned

What we discovered building BudgetScan — decisions, gotchas, and things that bit us.

---

## Architecture & Philosophy

**File-based Quicken sync was the right call.** A live connector (Plaid, cloud sync) would have meant a third party seeing the transaction stream, a subscription cost, and data leaving the box. Quicken also has no public write API, so pushing splits back live isn't actually possible. QFX/QIF file exchange is manual and low-tech, but it's the only path that's fully bidirectional and keeps everything local.

**Embeddings blur numbers — structured store is mandatory for finance.** RAG over transaction data produces hallucinated totals. "How much did I spend on groceries in July?" needs `SELECT SUM`, not semantic retrieval. Finance uses SQLite as the source of truth for all numeric queries. RAG is scoped strictly to unstructured text (receipt notes, merchant descriptions).

**Per-domain isolation pays for itself.** Finance and Health are completely separate stacks on the same box. No shared datastore, no shared auth, no shared UI. The cost is two frontends to maintain, but the benefit is: a schema migration in Finance can't break Health, and sensitive financial data doesn't leak into the Health stack's vector index.

**Single-user assumption simplifies everything — and is load-bearing.** Every endpoint requires auth but no endpoint filters by user. The session cookie model, the in-process rate limiter, the SQLite write serialization, and the Dropbox token lifecycle all assume one user on one box. This is fine and correct for the use case, but it's woven deeply — adding a second user isn't a config change, it's a rewrite.

---

## Money Handling

**Integer cents everywhere, enforced at every layer.** Schema (`BigInteger`), model, service, component (`MoneyInput` rounds on every change), and QFX/QIF parser all work in integer cents. String arithmetic (`_amount_to_cents`) avoids float drift at half-cent boundaries like `0.05`. This decision was made on day one and has never been revisited.

**The sign convention is still unresolved.** The QFX parser correctly preserves negative amounts from bank data, but the UI and budget logic assume everything is a positive expense. Income, refunds, and inter-account transfers have no representation. This needs a decision before Quicken import is used for real.

> **Implication:** budget status math may be wrong once real bank data (with credits) flows in.

---

## Quicken Interop

**Hand-rolled OFX parser — zero-dep, zero-regret.** The QFX subset we actually need (ACCTID, CURDEF, STMTTRN fields) is trivial to tokenize with regex. Avoiding `ofxparse` or `ofxtools` keeps the dependency surface at zero for a code path exercised once a week. The trade-off is no OFX 2.x (XML) support — that's a known gap.

**Stateless confirm was a good simplification.** Parse results go to the client and come back on confirm. No server-side staging table, no session state, no cleanup job. A page refresh resets. Saves a model, a migration, and a GC task — at the cost of a slightly larger confirm payload.

**Duplicate detection by date+amount, not FITID.** Banks are supposed to keep FITIDs stable, but in practice some banks (especially credit card pending-to-posted transitions) reassign them. Date+amount+account is coarser but more reliable. The downside: two legitimate same-day same-amount purchases collide.

**Currency mismatch should be a hard error.** When QFX `CURDEF` disagrees with the mapped account's currency, the entire statement is skipped. This is aggressive but correct — silently importing CAD transactions into a USD account would produce invisible rounding errors in every budget.

**QIF is the only round-trip format.** QFX is import-only (banks produce it, Quicken consumes it). QIF is the only format where both Quicken and BudgetScan can read and write, and the only format that carries split categories. Every other format is one-way.

---

## Receipt OCR

**Ollama's `format=json` isn't enough alone.** The flag makes the model *usually* emit JSON, but it's not guaranteed. The `extract_json` helper strips code fences, tries `json.loads`, then falls back to greedy `{...}` regex extraction. One retry on parse failure. This double-safety net has saved real runs.

**EXIF rotation must be applied before sending to the model.** iPhone photos carry EXIF orientation flags. Without `ImageOps.exif_transpose`, portrait-mode receipt photos arrive sideways at the vision model and OCR accuracy craters. Pre-process always: transpose, resize to <=2048px long edge, re-encode as JPEG q=90.

**The +/-$1 reconciler balancer is the right trade-off.** If parsed items sum within +/-$1 of the receipt total, the gap becomes a "Tax / rounding" line. If they're off by more, all item-level detail is discarded and a single Uncategorized line is created. This guarantees `sum(line_items) == amount_cents` always holds, preserving the Phase 5 split invariant.

**XHR for upload progress, not `fetch`.** Browser `fetch` doesn't surface upload-progress events. The `SnapReceiptButton` uses raw XHR so the user sees a real progress bar while the receipt image uploads. Minor API divergence from the rest of the app, worth it for the UX.

---

## Mobile & PWA

**iOS PWA install has no browser API — just a banner.** Safari doesn't fire `beforeinstallprompt`. The app shows a manual "tap Share → Add to Home Screen" toast on first visit, gated on `localStorage`. Detection uses `navigator.standalone` (iOS-only, untyped in TS — cast through `unknown`).

**`viewport-fit=cover` is required for translucent status bar.** Without it, iOS ignores `apple-mobile-web-app-status-bar-style: black-translucent` and leaves a white strip. Also required for `env(safe-area-inset-*)` padding to work on the bottom nav.

**Service worker: StaleWhileRevalidate for dashboard, NetworkFirst for everything else.** The budget status endpoint (`/api/budgets/status`) is cached so the dashboard paints instantly even if the server is momentarily unreachable. All other API calls use NetworkFirst with a 4-second timeout so writes don't get cached. This gives a usable offline-ish experience without the complexity of a real offline mode.

**Camera capture requires HTTPS.** `<input type="file" capture="environment">` only opens the camera when served over HTTPS. On plain HTTP (LAN dev), it silently downgrades to a file picker. This is why the Caddy TLS setup exists from Phase 1 — receipt capture doesn't work without it in prod.

---

## Infrastructure & Security

**`APP_ENV=production` is the master switch.** Required secrets fail-fast at startup only in production. CSRF enforcement, Secure cookies, SameSite=Strict — all gated on this flag. Tests and dev runs work with empty defaults. One env var, many consequences.

**Docker port publishing bypasses UFW.** Publishing a Docker port to `0.0.0.0` exposes it to the LAN regardless of UFW rules. Every service binds to `127.0.0.1` explicitly. Tailscale Serve is the only authorized path from outside. This is the #1 leak risk on the box.

**Receipt images are staging, not storage.** Local `data/receipts/` is a buffer. The flow is: upload → OCR writes JSON to SQLite → upload image to Dropbox → verify content_hash → delete local file. The JSON in SQLite is operational; the Dropbox image is audit trail. If Dropbox is offline, the local file is kept and the hourly cron retries. Never silently discard.

**Cron scripts shell into the running container.** The hourly sync and daily backup run `docker compose exec -T backend python -m ...` inside the backend container. This reuses the container's env vars and volume mounts. The risk: if the container is down when cron fires, the job silently fails. No alerting on the cron itself yet.

**Quicken browser authorization: use the system browser, not embedded.** Quicken's Fidelity EWC+ connection failed intermittently when authorized through Quicken's embedded Chromium (ERR_CONNECTION_RESET on the OAuth callback). Switching to the system browser (Safari/Chrome) for the authorization step resolved it. The embedded browser may be hitting rate limits or cookie-jar issues that the system browser doesn't.

> **Root cause identified Aug 2026.** The browser choice was the problem, not the connection type or Fidelity's side.

---

## Build Process

**Assumptions file is the most valuable doc in the repo.** `ASSUMPTIONS.md` captures every assumption baked into the codebase that hasn't been validated. It's the first place to look when something breaks in production — the answer is usually "we assumed X and X turned out to be wrong." Worth maintaining rigorously.

**ADRs prevent re-litigating decisions.** Five architecture decision records cover the non-obvious choices (file-based sync, structured store, domain isolation, interface ownership, Tailscale binding). Each one has been referenced multiple times to settle "why did we do it this way?" without reopening the debate.

**Single Alembic migration works until it doesn't.** Phase 1 created all tables in one migration. That was fine for greenfield, but every subsequent schema change (adding `is_pinned`, `dropbox_path`) needs an incremental migration. Don't regenerate from scratch — SQLite's `ALTER TABLE` limitations require Alembic's `batch_alter_table` for anything with a `NOT NULL DEFAULT`.

**Test coverage is concentrated in the backend.** Backend has meaningful test suites for auth, categories, transactions, budgets, receipts, quicken, aggregation, and finance QA. Frontend has exactly one test file (`Home.test.tsx`) from Phase 1. Every new frontend feature has shipped with zero test coverage. This is a known debt, not an oversight.

---

*Last updated Aug 2026*
