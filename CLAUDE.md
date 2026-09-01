# BudgetScan — Claude Code Instructions

## Before exploring the codebase

Read `ARCHITECTURE.md` first. It has entity relationships, directory layout, and
compressed call-chain flows for every feature. This should tell you WHERE to look
without needing to scan the repo.

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

## Conventions

- All money values are stored and passed as integer cents (`amount_cents`, `unit_price_cents`).
- `formatCents()` from `MoneyInput.tsx` for display.
- Hooks in `frontend/src/hooks/` are thin TanStack Query wrappers — one file per domain entity.
- Components use Tailwind utility classes directly, no CSS modules.
- Backend schemas split into Read/Create/Update DTOs in `backend/src/finance/schemas/`.

## Public repo — sensitive data rules

This is a public GitHub repo. Never commit:
- `.env`, database files, QFX/QIF exports, receipt images
- API keys, tokens, Tailscale hostnames beyond what's already in ARCHITECTURE.md
- Real transaction data or financial details
