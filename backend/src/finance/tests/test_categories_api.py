import pytest
from httpx import AsyncClient


@pytest.fixture
async def authed_client(client: AsyncClient):
    await client.post("/api/auth/setup", json={"username": "admin", "password": "pass"})
    return client


async def test_create_and_list(authed_client: AsyncClient) -> None:
    resp = await authed_client.post("/api/categories", json={"name": "Food"})
    assert resp.status_code == 201
    food = resp.json()
    assert food["name"] == "Food"
    assert food["parent_id"] is None

    resp = await authed_client.get("/api/categories")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


async def test_get_by_id(authed_client: AsyncClient) -> None:
    resp = await authed_client.post("/api/categories", json={"name": "Transport"})
    cat_id = resp.json()["id"]
    resp = await authed_client.get(f"/api/categories/{cat_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Transport"


async def test_get_not_found(authed_client: AsyncClient) -> None:
    resp = await authed_client.get("/api/categories/9999")
    assert resp.status_code == 404


async def test_create_with_parent(authed_client: AsyncClient) -> None:
    parent = (await authed_client.post("/api/categories", json={"name": "Food"})).json()
    child = (
        await authed_client.post(
            "/api/categories",
            json={"name": "Groceries", "parent_id": parent["id"]},
        )
    ).json()
    assert child["parent_id"] == parent["id"]


async def test_update(authed_client: AsyncClient) -> None:
    cat = (await authed_client.post("/api/categories", json={"name": "Old"})).json()
    resp = await authed_client.patch(
        f"/api/categories/{cat['id']}", json={"name": "New"}
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "New"


async def test_delete(authed_client: AsyncClient) -> None:
    cat = (await authed_client.post("/api/categories", json={"name": "Temp"})).json()
    resp = await authed_client.delete(f"/api/categories/{cat['id']}")
    assert resp.status_code == 204
    resp = await authed_client.get(f"/api/categories/{cat['id']}")
    assert resp.status_code == 404


async def test_self_parent_rejected(authed_client: AsyncClient) -> None:
    cat = (await authed_client.post("/api/categories", json={"name": "X"})).json()
    resp = await authed_client.patch(
        f"/api/categories/{cat['id']}", json={"parent_id": cat["id"]}
    )
    assert resp.status_code == 400


async def test_cycle_rejected(authed_client: AsyncClient) -> None:
    a = (await authed_client.post("/api/categories", json={"name": "A"})).json()
    b = (
        await authed_client.post(
            "/api/categories", json={"name": "B", "parent_id": a["id"]}
        )
    ).json()
    resp = await authed_client.patch(
        f"/api/categories/{a['id']}", json={"parent_id": b["id"]}
    )
    assert resp.status_code == 400
