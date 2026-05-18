from fastapi import FastAPI

app = FastAPI(title="Finance")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
