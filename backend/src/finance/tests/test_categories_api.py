import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from finance.db import get_session
from finance.main import app
from finance.models import Base


@pytest.fixture
async def client():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    await engine.dispose()


async def test_create_and_list(client: AsyncClient) -> None:
    resp = await client.post("/api/categories", json={"name": "Food"})
    assert resp.status_code == 201
    food = resp.json()
    assert food["name"] == "Food"
    assert food["parent_id"] is None

    resp = await client.get("/api/categories")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


async def test_get_by_id(client: AsyncClient) -> None:
    resp = await client.post("/api/categories", json={"name": "Transport"})
    cat_id = resp.json()["id"]
    resp = await client.get(f"/api/categories/{cat_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Transport"


async def test_get_not_found(client: AsyncClient) -> None:
    resp = await client.get("/api/categories/9999")
    assert resp.status_code == 404


async def test_create_with_parent(client: AsyncClient) -> None:
    parent = (await client.post("/api/categories", json={"name": "Food"})).json()
    child = (
        await client.post(
            "/api/categories",
            json={"name": "Groceries", "parent_id": parent["id"]},
        )
    ).json()
    assert child["parent_id"] == parent["id"]


async def test_update(client: AsyncClient) -> None:
    cat = (await client.post("/api/categories", json={"name": "Old"})).json()
    resp = await client.patch(
        f"/api/categories/{cat['id']}", json={"name": "New"}
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "New"


async def test_delete(client: AsyncClient) -> None:
    cat = (await client.post("/api/categories", json={"name": "Temp"})).json()
    resp = await client.delete(f"/api/categories/{cat['id']}")
    assert resp.status_code == 204
    resp = await client.get(f"/api/categories/{cat['id']}")
    assert resp.status_code == 404


async def test_self_parent_rejected(client: AsyncClient) -> None:
    cat = (await client.post("/api/categories", json={"name": "X"})).json()
    resp = await client.patch(
        f"/api/categories/{cat['id']}", json={"parent_id": cat["id"]}
    )
    assert resp.status_code == 400


async def test_cycle_rejected(client: AsyncClient) -> None:
    a = (await client.post("/api/categories", json={"name": "A"})).json()
    b = (
        await client.post(
            "/api/categories", json={"name": "B", "parent_id": a["id"]}
        )
    ).json()
    resp = await client.patch(
        f"/api/categories/{a['id']}", json={"parent_id": b["id"]}
    )
    assert resp.status_code == 400
