# BudgetScan — Open Items

Running list of work to do. Items added as they surface.

---

## Investigate

- [ ] **Fidelity brokerage transaction detail** — Open one Fidelity brokerage account in Quicken and check whether individual buys, sells, and dividends land in the register, or just holdings/positions. If it's just holdings, that's the EWC+ scope limitation — and a CSV ingestion path for Fidelity becomes the fallback.
  *Surfaced: browser bug investigation (Aug 2026)*

- [ ] **Does this Quicken version accept our QIF for bank accounts?** — Modern Quicken (Premier 2023+) deprecates QIF import for bank/credit card accounts and may only accept it for cash/asset accounts. Need to test the actual File → File Import → QIF flow on the installed version.
  *Surfaced: ASSUMPTIONS.md — Quicken interop*

- [ ] **Negative amounts (income, refunds, credits)** — The QFX parser handles negative `TRNAMT` values, but the UI and budget logic assume all amounts are positive (expenses). Income, refunds, and transfers have no representation. Need to decide on sign convention before relying on imported data for budget math.
  *Surfaced: ASSUMPTIONS.md — money representation*

## Validate

- [ ] **Test QFX import against real bank exports** — Current tests use hand-built fixtures. Real QFX files from Chase, Capital One, etc. each have quirks (inline `<MEMO>` blocks, nested `INVSTMTRS`, variant ACCTID locations). Import a real file from each institution and verify parsing.
  *Surfaced: LEARNINGS.md — Phase 8, ASSUMPTIONS.md*

- [ ] **QIF round-trip through actual Quicken** — Export from BudgetScan, import into Quicken, verify splits land correctly. Also test whether emitting both `L` and `S`/`$` lines causes complaints or silent drops.
  *Surfaced: LEARNINGS.md — Phase 8*

- [ ] **Real-device iPhone test** — Install PWA on the actual iPhone, verify: home screen icon, launch image, camera capture, safe-area insets, Caddy TLS trust, FCP target (<1.5s cold cache). No physical-device validation exists yet.
  *Surfaced: LEARNINGS.md — Phase 7, ASSUMPTIONS.md — mobile/PWA*

- [ ] **Ollama + RTX 5070 Ti smoke test** — Verify `qwen2.5vl:7b` loads into VRAM (not CPU fallback) on the actual GPU. Check `size_vram > 0` after load. Run a real receipt through OCR end-to-end.
  *Surfaced: ASSUMPTIONS.md — OCR, RUNBOOK §1.6*

- [ ] **`docker compose --profile prod up -d` full stack** — The healthchecks were written by hand. Bring up the full prod stack (backend + frontend + Ollama + Caddy) and verify everything comes up healthy. Includes testing the hourly cron's container-exec model.
  *Surfaced: ASSUMPTIONS.md — Phase 9*

- [ ] **CSRF + frontend integration** — Frontend hasn't been wired to read the `csrf_token` cookie and echo it as `X-CSRF-Token` on POST/PUT/DELETE. Enforcement only kicks in when `APP_ENV=production`. A prod deploy will 403 every write until this is done.
  *Surfaced: ASSUMPTIONS.md — Phase 9*

- [ ] **Dropbox end-to-end upload-verify-delete cycle** — The `content_hash` match (4 MiB-block sha256-of-sha256s) is the only confirmation before deleting the local file. Untested end-to-end. If Dropbox changes hash semantics, local files get silently destroyed.
  *Surfaced: ASSUMPTIONS.md — Phase 9*

## Build

- [ ] **Fidelity CSV ingestion path** — If Fidelity brokerage detail doesn't come back through Quicken's EWC+ connection, build a CSV import for Fidelity's downloadable activity export. Separate from the QFX/QIF pipeline — different column layout, different account types (`brokerage` / `investment`).
  *Contingent on: Fidelity investigation above*

- [ ] **OFX 2.x (XML) parser** — Current parser only handles OFX 1.x SGML. Banks that ship XML-format QFX will fail silently. Add XML path or at minimum a clear error message.
  *Surfaced: ASSUMPTIONS.md — Quicken interop*

- [ ] **Frontend test coverage beyond `Home.test.tsx`** — Import, Export, Transactions, SplitEditor, ReceiptProcessing, SnapReceiptButton, MerchantCombobox, and the dashboard budget cards all have zero test coverage. The only frontend test in the repo is the Phase 1 smoke test.
  *Surfaced: LEARNINGS.md — Phases 5, 6, 7, 8*

- [ ] **Tailscale Serve exposure for Health stack** — Health stack hardening and Tailscale Serve exposure is listed as "open / next" in ARCHITECTURE.md. Not blocked by finance work but on the list.
  *Surfaced: ARCHITECTURE.md §5*

- [x] **Move Docker data root to `/home`** — The root partition (`/dev/nvme0n1p1`, 92G) is nearly full, mostly from Docker images and build cache. `/home` has 1.6T free. Moved Docker to `/home/docker` via `/etc/docker/daemon.json` and containerd to `/home/containerd` via `/etc/containerd/config.toml`.
  *Surfaced: disk-full during first `docker compose up` (Aug 2026)*

## Fix

- [ ] **UTC date shift on evening receipts** — Export uses `txn.posted_at.strftime('%m/%d/%Y')` which emits UTC. Receipts entered in the evening of a US timezone appear a day later in the QIF. Needs timezone-aware formatting or a date-only stored field.
  *Surfaced: ASSUMPTIONS.md — Quicken interop*

- [x] **Two same-amount same-day purchases collapse** — ~~Duplicate detection uses account + amount + same calendar day.~~ Fixed: dedup now checks FITID, then amount+date+description (strong match), then amount+date only (flagged as `likely-duplicate` in orange so user decides). Two coffees at different places no longer auto-skip.
  *Surfaced: ASSUMPTIONS.md — Quicken interop. Fixed: Aug 2026*

- [ ] **Caddy admin API bound to `0.0.0.0:2019`** — Needed for iPhone cert download, but must be locked down if Caddy is ever exposed beyond LAN. Either bind to `127.0.0.1:2019` and document a manual cert-copy step, or gate on Tailscale-only access.
  *Surfaced: LEARNINGS.md — Phase 9*

## Receipt → Transaction Reconciliation

- [ ] **Receipt holding pool with transaction suggestions** — Scanned receipts need a staging area that surfaces candidate transaction matches. Match first by date + amount, then by merchant name. UI should show the receipt alongside the top suggestions and let the user confirm, reject, or manually link.
  *Surfaced: planning session Aug 2026*

- [ ] **Transaction tagging / categorization from receipts** — Before budgeting can work, transactions need categories. Receipts already carry merchant and line-item data from OCR — use that to suggest or auto-assign categories.
  *Surfaced: planning session Aug 2026*

- [ ] **Split transactions from receipt line items** — Receipts with multiple line items (e.g. Costco run with groceries + household) should be able to generate split transactions. The split editor exists but isn't wired to receipt OCR data yet.
  *Surfaced: planning session Aug 2026*

## LLM-Powered Categorization

- [ ] **Auto-categorize transactions via local LLM + Quicken knowledge base** — The 149 imported Quicken categories and 391 memorized payee→category rules are a ready-made training set. The local Qwen model could use these as few-shot context to guess categories for new/untagged transactions. Challenges: (1) bank transaction descriptions are often cryptic abbreviations (e.g. "SQ *JOES COFF" = Square / Joe's Coffee), (2) the LLM may need web lookup to resolve merchant names, but that lives in the harness not the model, (3) need to figure out prompt engineering, context window management for 391 rules, and confidence thresholds for auto-assign vs. suggest. See `docs/DESIGN_LLM_CATEGORIZATION.md` for the proposed architecture.
  *Surfaced: planning session Aug 2026*

## Budget

- [ ] **Budget suggestion engine** — Once transactions are tagged with categories, suggest monthly budget amounts based on historical spending patterns. The imported Quicken categories and memorized rules provide a strong starting point — most historical transactions already have categories via the memorized rules. New/unmatched transactions get categorized by the LLM pipeline above.
  *Surfaced: planning session Aug 2026. Depends on: LLM categorization pipeline*

## Ship

- [ ] **First real weekly reconciliation cycle** — Run the full README workflow end-to-end: pull bank data in Quicken, export QFX, import to BudgetScan, review + confirm, export QIF back, import into Quicken. Document what breaks.
  *Surfaced: README.md § Weekly Quicken reconciliation workflow*

- [ ] **Install cron jobs on TheRig** — The hourly sync and daily backup cron entries are documented in RUNBOOK §3 but not yet installed. Both shell into the backend container.
  *Surfaced: RUNBOOK.md §3*

---

*Last updated Aug 2026*
