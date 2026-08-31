# Finance App

A self-hosted, mobile-first personal finance webapp with receipt OCR, line-item splitting, active budgeting, and Quicken interop. See [ARCHITECTURE.md](ARCHITECTURE.md) for the full design.

## Prerequisites

- Docker & Docker Compose
- (Optional) NVIDIA GPU + nvidia-container-toolkit for local vision LLM

## Quick Start

```bash
cp .env.example .env
# Edit .env — at minimum change APP_SECRET to a random string

docker compose up
```

- **Frontend:** http://localhost (port 80)
- **Backend API:** http://localhost:8000
- **Health check:** http://localhost:8000/api/health
- **Ollama:** http://localhost:11434

## Development (without Docker)

### Backend

```bash
cd backend
uv sync --all-extras
uv run pytest
uv run uvicorn finance.main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm test
npm run dev
```

The Vite dev server proxies `/api` requests to `http://localhost:8000`.

## Weekly Quicken reconciliation workflow

Quicken stays your system of record for bank data; this app owns receipt
splits and at-the-moment budgeting. The two stay in sync via QIF
file exchange — about five minutes a week.

1. **Pull bank data in Quicken** the usual way (One Step Update or manual
   import). Let Quicken auto-match what it can.
2. **Export the week as QIF** from Quicken: *File → File Export → QIF*.
   Pick the account and the date range you want to bring into the app.
3. **Import in the app** at `/sync`. The candidate review table flags
   each row:
   - `new` — no existing transaction matches. Default action: **Create**.
   - `duplicate` — same account + amount + day already exists. Default
     action: **Skip** (you already entered it in the app, e.g. from a
     receipt that hasn't been merged yet).
   - `matched-receipt` — there's a receipt-entered transaction within ±2
     days at the same amount. Default action: **Merge** — the bank's
     FITID is annotated onto your existing receipt-split transaction and
     it's marked `final`. Your line-item splits survive.

   Click **Apply**. Unmapped account ids we've never seen are surfaced
   inline so you can map them once and they stick.
4. **Export QIF back to Quicken** from `/export`. Pick the same date range
   and accounts and download. In Quicken: *File → File Import → QIF File*,
   choose "all accounts", and uncheck duplicates. This backfills the
   per-category splits onto the rows Quicken pulled flat, so your Quicken
   reports get the same line-item resolution the app has.

The whole loop is purely file-based — the app never talks to Quicken
directly. If something goes wrong, nothing gets written until you click
**Apply**, and per-row errors collect in a list rather than failing the
whole batch.

### Categories on the QIF boundary

Categories in QIF use Quicken's colon syntax (`Food:Groceries:Costco`).
On export we always emit the full path of the category leaf. On import,
unknown paths can either error out (default — surface to the user) or be
auto-created as flat categories with the full colon path as the name
(checkbox on the import page). Either way the app's own hierarchy stays
intact; only inbound paths that don't match get the flat fallback.

## GPU Support

To enable GPU passthrough for Ollama, uncomment the `deploy.resources` block in `docker-compose.yml`. Requires nvidia-container-toolkit.
