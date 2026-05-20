from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

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
        await ac.post("/api/auth/setup", json={"username": "test", "password": "test"})
        yield ac

    app.dependency_overrides.clear()
    await engine.dispose()


async def _create_account(client: AsyncClient, name: str = "Checking") -> dict:
    resp = await client.post(
        "/api/accounts", json={"name": name, "type": "checking"}
    )
    assert resp.status_code == 201
    return resp.json()


async def _create_category(client: AsyncClient, name: str = "Groceries") -> dict:
    resp = await client.post("/api/categories", json={"name": name})
    assert resp.status_code == 201
    return resp.json()


async def _create_merchant(client: AsyncClient, name: str = "Costco") -> dict:
    resp = await client.post("/api/merchants", json={"name": name})
    assert resp.status_code == 201
    return resp.json()


# ── Account CRUD ──


async def test_account_crud(client: AsyncClient) -> None:
    acct = await _create_account(client)
    assert acct["name"] == "Checking"

    resp = await client.get("/api/accounts")
    assert len(resp.json()) == 1

    resp = await client.patch(
        f"/api/accounts/{acct['id']}", json={"name": "Savings"}
    )
    assert resp.json()["name"] == "Savings"

    resp = await client.delete(f"/api/accounts/{acct['id']}")
    assert resp.status_code == 204


# ── Merchant CRUD + search ──


async def test_merchant_crud_and_search(client: AsyncClient) -> None:
    m = await _create_merchant(client)
    assert m["name"] == "Costco"
    assert m["normalized_name"] == "costco"

    resp = await client.get("/api/merchants/search?q=cos")
    assert len(resp.json()) == 1

    resp = await client.get("/api/merchants/search?q=walmart")
    assert len(resp.json()) == 0

    resp = await client.patch(
        f"/api/merchants/{m['id']}", json={"name": "Costco Wholesale"}
    )
    assert resp.json()["normalized_name"] == "costco wholesale"

    resp = await client.delete(f"/api/merchants/{m['id']}")
    assert resp.status_code == 204


# ── Transaction round-trip with splits ──


async def test_create_transaction_with_splits(client: AsyncClient) -> None:
    acct = await _create_account(client)
    cat1 = await _create_category(client, "Groceries")
    cat2 = await _create_category(client, "Household")

    resp = await client.post(
        "/api/transactions",
        json={
            "account_id": acct["id"],
            "posted_at": "2026-05-19T12:00:00Z",
            "amount_cents": 5000,
            "description": "Costco trip",
            "line_items": [
                {"category_id": cat1["id"], "amount_cents": 3000, "description": "Food"},
                {"category_id": cat2["id"], "amount_cents": 2000, "description": "Paper towels"},
            ],
        },
    )
    assert resp.status_code == 201
    txn = resp.json()
    assert txn["amount_cents"] == 5000
    assert txn["status"] == "split"
    assert len(txn["line_items"]) == 2
    assert txn["line_items"][0]["category_name"] == "Groceries"

    resp = await client.get(f"/api/transactions/{txn['id']}")
    assert resp.status_code == 200
    detail = resp.json()
    assert len(detail["line_items"]) == 2


async def test_create_transaction_without_splits_creates_uncategorized(
    client: AsyncClient,
) -> None:
    acct = await _create_account(client)

    resp = await client.post(
        "/api/transactions",
        json={
            "account_id": acct["id"],
            "posted_at": "2026-05-19T12:00:00Z",
            "amount_cents": 2500,
        },
    )
    assert resp.status_code == 201
    txn = resp.json()
    assert len(txn["line_items"]) == 1
    assert txn["line_items"][0]["amount_cents"] == 2500
    assert txn["line_items"][0]["category_name"] == "Uncategorized"


# ── Split sum mismatch rejected ──


async def test_split_sum_mismatch_rejected(client: AsyncClient) -> None:
    acct = await _create_account(client)
    cat = await _create_category(client)

    resp = await client.post(
        "/api/transactions",
        json={
            "account_id": acct["id"],
            "posted_at": "2026-05-19T12:00:00Z",
            "amount_cents": 5000,
            "line_items": [
                {"category_id": cat["id"], "amount_cents": 3000},
                {"category_id": cat["id"], "amount_cents": 1000},
            ],
        },
    )
    assert resp.status_code == 400


async def test_replace_line_items_mismatch_rejected(client: AsyncClient) -> None:
    acct = await _create_account(client)
    cat = await _create_category(client)

    resp = await client.post(
        "/api/transactions",
        json={
            "account_id": acct["id"],
            "posted_at": "2026-05-19T12:00:00Z",
            "amount_cents": 5000,
        },
    )
    txn = resp.json()

    resp = await client.put(
        f"/api/transactions/{txn['id']}/line_items",
        json={
            "line_items": [
                {"category_id": cat["id"], "amount_cents": 9999},
            ]
        },
    )
    assert resp.status_code == 400


# ── Replace line items (PUT) ──


async def test_replace_line_items(client: AsyncClient) -> None:
    acct = await _create_account(client)
    cat1 = await _create_category(client, "Groceries")
    cat2 = await _create_category(client, "Dining")

    resp = await client.post(
        "/api/transactions",
        json={
            "account_id": acct["id"],
            "posted_at": "2026-05-19T12:00:00Z",
            "amount_cents": 5000,
        },
    )
    txn = resp.json()
    assert len(txn["line_items"]) == 1

    resp = await client.put(
        f"/api/transactions/{txn['id']}/line_items",
        json={
            "line_items": [
                {"category_id": cat1["id"], "amount_cents": 3000},
                {"category_id": cat2["id"], "amount_cents": 2000},
            ]
        },
    )
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 2
    assert items[0]["amount_cents"] == 3000
    assert items[1]["amount_cents"] == 2000


# ── Transaction list with filters ──


async def test_list_with_filters(client: AsyncClient) -> None:
    acct = await _create_account(client)

    await client.post(
        "/api/transactions",
        json={
            "account_id": acct["id"],
            "posted_at": "2026-05-10T12:00:00Z",
            "amount_cents": 1000,
        },
    )
    await client.post(
        "/api/transactions",
        json={
            "account_id": acct["id"],
            "posted_at": "2026-05-15T12:00:00Z",
            "amount_cents": 2000,
        },
    )

    resp = await client.get("/api/transactions")
    assert resp.json()["total"] == 2

    resp = await client.get(
        "/api/transactions?date_from=2026-05-12T00:00:00Z"
    )
    assert resp.json()["total"] == 1


# ── Transaction update and delete ──


async def test_update_transaction(client: AsyncClient) -> None:
    acct = await _create_account(client)

    resp = await client.post(
        "/api/transactions",
        json={
            "account_id": acct["id"],
            "posted_at": "2026-05-19T12:00:00Z",
            "amount_cents": 1000,
        },
    )
    txn = resp.json()

    resp = await client.patch(
        f"/api/transactions/{txn['id']}",
        json={"description": "Updated desc"},
    )
    assert resp.status_code == 200
    assert resp.json()["description"] == "Updated desc"


async def test_delete_transaction(client: AsyncClient) -> None:
    acct = await _create_account(client)

    resp = await client.post(
        "/api/transactions",
        json={
            "account_id": acct["id"],
            "posted_at": "2026-05-19T12:00:00Z",
            "amount_cents": 1000,
        },
    )
    txn = resp.json()

    resp = await client.delete(f"/api/transactions/{txn['id']}")
    assert resp.status_code == 204

    resp = await client.get(f"/api/transactions/{txn['id']}")
    assert resp.status_code == 404


# ── Merchant learning ──


async def test_merchant_learning_at_threshold(client: AsyncClient) -> None:
    acct = await _create_account(client)
    merchant = await _create_merchant(client)
    cat_groceries = await _create_category(client, "Groceries")
    cat_dining = await _create_category(client, "Dining")

    assert merchant["default_category_id"] is None

    for _ in range(3):
        await client.post(
            "/api/transactions",
            json={
                "account_id": acct["id"],
                "merchant_id": merchant["id"],
                "posted_at": "2026-05-19T12:00:00Z",
                "amount_cents": 1000,
                "line_items": [
                    {"category_id": cat_groceries["id"], "amount_cents": 1000},
                ],
            },
        )

    resp = await client.get(f"/api/merchants/{merchant['id']}")
    assert resp.json()["default_category_id"] == cat_groceries["id"]
