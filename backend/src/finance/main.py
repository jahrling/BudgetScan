from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI

from finance.db import init_db
from finance.routers.budgets import router as budgets_router
from finance.routers.categories import router as categories_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await init_db()
    yield


app = FastAPI(title="Finance", lifespan=lifespan)
app.include_router(categories_router)
app.include_router(budgets_router)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
