# Personal Finance App — Architecture & Build Plan

A self-hosted, mobile-first personal finance webapp with receipt OCR, line-item splitting, active budgeting, and Quicken interop. Designed to run on a home server with a GPU (~16GB VRAM) for local vision-LLM inference.

---

## 1. Vision

Quicken handles bank data ingestion and security well, but is passive at the moment of decision and clumsy with mixed-category receipts (CostCo, Target, Amazon). This app fills those gaps:

1. **Active budgeting at point-of-decision.** Open the app at the store, see what's left in each category before swiping the card.
2. **Effortless receipt splitting.** Photograph the receipt, vision LLM extracts and categorizes line items, you tap to confirm.
3. **Quicken interop.** Generate QIF files with split transactions that you import back into Quicken so it remains your system of record for bank reconciliation.
4. **All local.** Inference, storage, and data on your hardware. (Remote access via zero-trust is a separate project.)

---

## 2. Assumptions & Key Decisions

| Topic | Decision | Why |
|---|---|---|
| VRAM | Assume **16GB** | 16GB runs a 7B vision LLM at Q4 comfortably |
| OCR strategy | **Local vision LLM** (e.g. Qwen2.5-VL-7B via Ollama) | Vastly better than Tesseract+regex on real-world receipts; outputs structured JSON; can also category-guess in the same pass |
| Frontend | **React PWA** (Vite + TS + Tailwind) | iPhone-installable from Safari, no App Store, camera access, single codebase |
| Backend | **Python 3.11+ / FastAPI** | Best ML/LLM ecosystem, async I/O, Pydantic typing, easy Ollama integration |
| DB | **SQLite via SQLAlchemy async** | Personal-scale data; trivial backup (one file); zero ops; can migrate to Postgres later if needed |
| Quicken sync | **QIF/QFX file exchange**, not API | Quicken has no public write API; QIF is the historical lingua franca |
| Bank data source | Quicken's existing data, exported as QFX/QIF and imported into the app | Avoids re-doing what Quicken does well; no Plaid subscription |
| Auth | Session-based, single-user, from day 1 | Lays groundwork for the future zero-trust remote access work |
| Hosting | Docker Compose on home server | One `docker compose up`; portable; fits the future reverse-proxy setup |
| LLM runtime | **Ollama** | Easiest local-model server; OpenAI-compatible API; supports vision models |

If you'd rather use 8GB VRAM, swap in a smaller model (MiniCPM-V 2.6 or Qwen2.5-VL-3B); the rest of the architecture is unchanged.

---

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    iPhone Safari (PWA installed)                 │
│                            │                                     │
└────────────────────────────┼─────────────────────────────────────┘
                             │ HTTPS (LAN now, zero-trust later)
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                       Home Server (Docker)                       │
│                                                                  │
│   ┌──────────────┐    ┌──────────────────┐   ┌──────────────┐  │
│   │  Caddy/Nginx │───▶│  React PWA       │   │  Ollama      │  │
│   │  (TLS, LAN)  │    │  (static build)  │   │  Qwen2.5-VL  │  │
│   └──────┬───────┘    └──────────────────┘   └──────▲───────┘  │
│          │                                          │           │
│          │ /api/*                                   │ HTTP      │
│          ▼                                          │           │
│   ┌─────────────────────────────────────────────────┴────────┐ │
│   │  FastAPI Backend                                          │ │
│   │  • Auth (session cookies)                                 │ │
│   │  • Transactions / Splits / Categories / Budgets           │ │
│   │  • Receipt upload → vision LLM → structured line items    │ │
│   │  • QIF/QFX import & export                                │ │
│   └────────────┬──────────────────────────────────────────────┘ │
│                ▼                                                 │
│   ┌────────────────────────┐  ┌──────────────────────────────┐ │
│   │  SQLite (mounted vol)  │  │  Receipt images (mounted)    │ │
│   └────────────────────────┘  └──────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

**Key user flow — at the store:**
1. Open PWA on iPhone (already on home screen).
2. Dashboard shows: Groceries $187/$400, Dining $92/$150, Household $30/$100…
3. Decide whether to buy the thing.
4. After purchase: tap "+", photograph receipt.
5. Vision LLM extracts line items + guessed categories within ~5–15s.
6. Review, swipe to adjust categories, hit save.
7. Budget updates immediately.

**Quicken reconciliation flow (weekly):**
1. Quicken pulls bank transactions as usual.
2. Export the week's transactions from Quicken as QFX.
3. Import to app — it matches receipts you've already photographed and merges line-item splits.
4. Export QIF from app, import to Quicken to backfill the splits & categories.

---

## 4. Tech Stack

### Backend
- **Python 3.11+** managed by `uv`
- **FastAPI** + **Uvicorn**
- **SQLAlchemy 2.0 (async)** + **Alembic**
- **Pydantic v2** for schemas
- **httpx** for calling Ollama
- **Pillow** for image preprocessing
- **pytest** + **pytest-asyncio**

### Frontend
- **Vite + React 18 + TypeScript**
- **Tailwind CSS** + **shadcn/ui** components
- **React Router v6**
- **TanStack Query** for server state
- **vite-plugin-pwa** for service worker, install prompt, offline shell
- **react-hook-form** + **zod** for forms
- **Vitest** + **React Testing Library**

### Infra
- **Docker Compose** orchestrating: backend, frontend (static), Ollama, Caddy (reverse proxy)
- **Caddy** for local HTTPS via internal CA (or self-signed); will be swapped for the zero-trust ingress later

### Local LLM
- **Ollama** serving a vision model (start with `qwen2.5vl:7b`, fall back to `minicpm-v` if quality issues)

---

## 5. Project Structure

```
finance-app/
├── ARCHITECTURE.md           ← This document, committed to repo
├── README.md
├── docker-compose.yml
├── .env.example
├── .gitignore
├── backend/
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── alembic.ini
│   ├── alembic/
│   ├── src/
│   │   └── finance/
│   │       ├── __init__.py
│   │       ├── main.py
│   │       ├── config.py
│   │       ├── db.py
│   │       ├── auth/
│   │       ├── models/
│   │       ├── schemas/
│   │       ├── routers/
│   │       ├── services/
│   │       │   ├── ocr.py
│   │       │   ├── categorizer.py
│   │       │   ├── budget.py
│   │       │   └── quicken.py
│   │       └── tests/
│   └── Dockerfile
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── tailwind.config.ts
│   ├── index.html
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── routes/
│   │   ├── components/
│   │   ├── hooks/
│   │   ├── lib/
│   │   └── types/
│   └── Dockerfile
├── caddy/
│   └── Caddyfile
└── data/                     ← gitignored; mounted as volume
    ├── finance.db
    └── receipts/
```

---

## 6. Database Schema (high-level)

```
users(id, username, password_hash, created_at)

accounts(id, name, type, quicken_id?, currency)        -- e.g. "Chase Checking"

categories(id, parent_id?, name, color, icon)          -- hierarchical
                                                       -- e.g. Food > Groceries > Costco

budgets(id, category_id, period, amount_cents,         -- period: 'monthly' | 'weekly'
        start_date, end_date?)

merchants(id, name, normalized_name, default_category_id?,
          notes)                                       -- learns from history

transactions(id, account_id, merchant_id?, posted_at,
             amount_cents, description, quicken_id?,
             receipt_id?, status)                      -- status: 'pending'|'split'|'final'

line_items(id, transaction_id, category_id, description,
           quantity, unit_price_cents, amount_cents,
           ocr_confidence?, user_modified)             -- splits within a transaction

receipts(id, file_path, original_filename, sha256,
         captured_at, ocr_raw_json?, ocr_model,
         ocr_status, ocr_error?)                       -- status: pending|done|failed
```

Money stored as integer cents everywhere. No floats for money, ever.

---

## 7. Phased Build Plan (9 sessions)

Each phase is a discrete Claude Code session with a self-contained prompt below.

| # | Phase | Output |
|---|---|---|
| 1 | **Bootstrap** | Repo, Docker, FastAPI skeleton, React PWA skeleton |
| 2 | **DB & models** | Schema, migrations, base CRUD, tests |
| 3 | **Auth** | Single-user session auth, login UI |
| 4 | **Categories & budgets** | Hierarchical categories, budget math, UI |
| 5 | **Transactions & splits** | Manual entry, splitting, UI |
| 6 | **Receipt OCR** | Upload, Ollama integration, line-item extraction, review UI |
| 7 | **Mobile dashboard** | "What can I spend" view, PWA install polish |
| 8 | **Quicken interop** | QFX import, QIF export with splits |
| 9 | **Polish & deploy** | Offline shell, Caddy, production compose, runbook |