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

## GPU Support

To enable GPU passthrough for Ollama, uncomment the `deploy.resources` block in `docker-compose.yml`. Requires nvidia-container-toolkit.
