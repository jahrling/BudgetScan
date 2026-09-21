# BudgetScan — Claude Code Instructions

## Before exploring the codebase

Read `ARCHITECTURE.md` first. It has entity relationships, directory layout, and
compressed call-chain flows for every feature. This should tell you WHERE to look
without needing to scan the repo.

Privacy and data-handling rules live in `SECURITY.md`. Read it before any
session that touches financial data, imports, or scripts that query the database.

System-level topology (TheRig, Tailscale, network config) lives in
`INFRA.private.md` (gitignored). Only read it for infra/deploy questions.

## Stack

- Backend: FastAPI + SQLAlchemy 2.0 (async) + SQLite. Lives in `backend/`.
- Frontend: React 18 + TypeScript + Vite + TanStack Query + Tailwind CSS. Lives in `frontend/`.
- AI: Ollama (host systemd service, not Docker). Vision OCR + embeddings + LLM categorization.
- Deploy: Docker Compose. Backend :8000, frontend nginx :8080, Ollama :11434.

## Development

- Frontend dev server: `cd frontend && npx vite` — proxies `/api` to `localhost:8000`.
- Backend must be running (Docker or direct) for the frontend to work.
- Type check: `cd frontend && npx tsc --noEmit`
- Build: `cd frontend && npx vite build`
- No test suite yet.

## Documentation requirements

Every meaningful change must be documented before reporting the task as done:

- **CHANGELOG.md** — append an entry for every feature, fix, or refactoring.
  Group entries under a date header (`## YYYY-MM-DD`). Each entry is one line:
  what changed and why, not how. Keep it human-readable, not a git log mirror.
- **ARCHITECTURE.md** — update when a change adds/removes entities, endpoints,
  or alters the directory layout or call-chain flows. Small bug fixes don't
  need an architecture update.
- **GitHub Issues** — use only for deferred work: bugs noticed but not fixed now,
  features to come back to. Don't create an Issue for work being done in the
  current session. Close Issues in the commit message (`Fixes #N`) when resolved.

## Conventions

- All money values are stored and passed as integer cents (`amount_cents`, `unit_price_cents`).
- `formatCents()` from `MoneyInput.tsx` for display.
- Hooks in `frontend/src/hooks/` are thin TanStack Query wrappers — one file per domain entity.
- Components use Tailwind utility classes directly, no CSS modules.
- Backend schemas split into Read/Create/Update DTOs in `backend/src/finance/schemas/`.

## Security & privacy

This is a public GitHub repo. Full rules live in `SECURITY.md` — read it before
any session that touches financial data, scripts, or imports. Key points:

- **Never commit** `.env`, database files, QFX/QIF exports, receipt images, API
  keys, tokens, or real transaction data.
- **Never read** financial data files directly (QIF, QFX, `.db`, receipts,
  statements, anything under `data/` or `data-root/`). Use scripts that redact
  output before printing.
- **Scripts must redact** account numbers and names before any `print()` that
  Claude might see. Follow the `_redact()` pattern in
  `find_duplicate_accounts.py`.
- **Test fixtures must be synthetic.** No real account names or numbers.
- **Docs and findings** describe account *types* and *counts*, not real names.
