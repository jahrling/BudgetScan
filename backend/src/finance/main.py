from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI

from finance.db import init_db
from finance.routers.accounts import router as accounts_router
from finance.routers.auth import router as auth_router
from finance.routers.budgets import router as budgets_router
from finance.routers.categories import router as categories_router
from finance.routers.merchants import router as merchants_router
from finance.routers.receipts import router as receipts_router
from finance.routers.transactions import router as transactions_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await init_db()
    yield


app = FastAPI(title="Finance", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(accounts_router)
app.include_router(categories_router)
app.include_router(budgets_router)
app.include_router(merchants_router)
app.include_router(transactions_router)
app.include_router(receipts_router)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
