from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from finance.db import get_session
from finance.main import app
from finance.models import Base
from finance.models.account import Account
from finance.models.category import Category
from finance.models.line_item import LineItem
from finance.models.transaction import Transaction


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
        ac._session_factory = factory  # type: ignore[attr-defined]
        await ac.post("/api/auth/setup", json={"username": "test", "password": "test"})
        yield ac

    app.dependency_overrides.clear()
    await engine.dispose()


async def _create_category(
    client: AsyncClient, name: str = "Groceries", is_income: bool = False
) -> dict:
    resp = await client.post(
        "/api/categories", json={"name": name, "is_income": is_income}
    )
    assert resp.status_code == 201
    return resp.json()


async def _create_budget(
    client: AsyncClient,
    category_id: int,
    amount_cents: int = 40000,
    period: str = "monthly",
    start_date: str | None = None,
) -> dict:
    today = date.today()
    resp = await client.post(
        "/api/budgets",
        json={
            "category_id": category_id,
            "period": period,
            "amount_cents": amount_cents,
            "start_date": start_date or today.replace(day=1).isoformat(),
        },
    )
    assert resp.status_code == 201
    return resp.json()


# ── CRUD tests ──


async def test_create_and_list(client: AsyncClient) -> None:
    cat = await _create_category(client)
    budget = await _create_budget(client, cat["id"])
    assert budget["category_id"] == cat["id"]
    assert budget["amount_cents"] == 40000
    assert budget["period"] == "monthly"

    resp = await client.get("/api/budgets")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


async def test_get_by_id(client: AsyncClient) -> None:
    cat = await _create_category(client)
    budget = await _create_budget(client, cat["id"])
    resp = await client.get(f"/api/budgets/{budget['id']}")
    assert resp.status_code == 200
    assert resp.json()["amount_cents"] == 40000


async def test_get_not_found(client: AsyncClient) -> None:
    resp = await client.get("/api/budgets/9999")
    assert resp.status_code == 404


async def test_update(client: AsyncClient) -> None:
    cat = await _create_category(client)
    budget = await _create_budget(client, cat["id"])
    resp = await client.patch(
        f"/api/budgets/{budget['id']}", json={"amount_cents": 50000}
    )
    assert resp.status_code == 200
    assert resp.json()["amount_cents"] == 50000


async def test_delete(client: AsyncClient) -> None:
    cat = await _create_category(client)
    budget = await _create_budget(client, cat["id"])
    resp = await client.delete(f"/api/budgets/{budget['id']}")
    assert resp.status_code == 204
    resp = await client.get(f"/api/budgets/{budget['id']}")
    assert resp.status_code == 404


async def test_invalid_category(client: AsyncClient) -> None:
    today = date.today()
    resp = await client.post(
        "/api/budgets",
        json={
            "category_id": 9999,
            "period": "monthly",
            "amount_cents": 10000,
            "start_date": today.isoformat(),
        },
    )
    assert resp.status_code == 400


async def test_invalid_period(client: AsyncClient) -> None:
    cat = await _create_category(client)
    today = date.today()
    resp = await client.post(
        "/api/budgets",
        json={
            "category_id": cat["id"],
            "period": "yearly",
            "amount_cents": 10000,
            "start_date": today.isoformat(),
        },
    )
    assert resp.status_code == 400


# ── Status endpoint tests ──


async def test_status_empty(client: AsyncClient) -> None:
    resp = await client.get("/api/budgets/status?period=current_month")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_status_with_budget_no_spending(client: AsyncClient) -> None:
    cat = await _create_category(client)
    await _create_budget(client, cat["id"], amount_cents=40000)

    resp = await client.get("/api/budgets/status?period=current_month")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    item = items[0]
    assert item["category_id"] == cat["id"]
    assert item["budgeted_cents"] == 40000
    assert item["spent_cents"] == 0
    assert item["remaining_cents"] == 40000
    assert item["percent_used"] == 0.0


async def test_status_with_spending(client: AsyncClient) -> None:
    cat = await _create_category(client)
    await _create_budget(client, cat["id"], amount_cents=40000)

    factory = client._session_factory  # type: ignore[attr-defined]
    async with factory() as session:
        account = Account(name="Checking", type="checking", currency="USD")
        session.add(account)
        await session.flush()

        today = date.today()
        txn = Transaction(
            account_id=account.id,
            posted_at=datetime(today.year, today.month, 15, tzinfo=timezone.utc),
            amount_cents=-2500,
            status="final",
        )
        session.add(txn)
        await session.flush()

        li1 = LineItem(
            transaction_id=txn.id,
            category_id=cat["id"],
            amount_cents=-1500,
        )
        li2 = LineItem(
            transaction_id=txn.id,
            category_id=cat["id"],
            amount_cents=-1000,
        )
        session.add_all([li1, li2])
        await session.commit()

    resp = await client.get("/api/budgets/status?period=current_month")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    item = items[0]
    assert item["spent_cents"] == 2500
    assert item["remaining_cents"] == 37500
    assert item["percent_used"] == pytest.approx(6.2, abs=0.1)


# ── Income summary tests ──


async def test_income_summary_empty(client: AsyncClient) -> None:
    resp = await client.get("/api/budgets/income-summary?period=current_month")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_cents"] == 0
    assert data["categories"] == []


async def test_income_summary_with_data(client: AsyncClient) -> None:
    salary = await _create_category(client, "Salary", is_income=True)
    dividends = await _create_category(client, "Dividends", is_income=True)

    factory = client._session_factory  # type: ignore[attr-defined]
    async with factory() as session:
        account = Account(name="Checking", type="checking", currency="USD")
        session.add(account)
        await session.flush()

        today = date.today()
        txn = Transaction(
            account_id=account.id,
            posted_at=datetime(today.year, today.month, 1, tzinfo=timezone.utc),
            amount_cents=-500000,
            status="final",
        )
        session.add(txn)
        await session.flush()

        session.add(LineItem(
            transaction_id=txn.id,
            category_id=salary["id"],
            amount_cents=-500000,
        ))

        txn2 = Transaction(
            account_id=account.id,
            posted_at=datetime(today.year, today.month, 10, tzinfo=timezone.utc),
            amount_cents=-5000,
            status="final",
        )
        session.add(txn2)
        await session.flush()

        session.add(LineItem(
            transaction_id=txn2.id,
            category_id=dividends["id"],
            amount_cents=-5000,
        ))
        await session.commit()

    resp = await client.get("/api/budgets/income-summary?period=current_month")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_cents"] == 505000
    assert len(data["categories"]) == 2
    assert data["categories"][0]["category_name"] == "Salary"
    assert data["categories"][0]["amount_cents"] == 500000


async def test_spending_suggestions_include_income_sorted_by_abs(client: AsyncClient) -> None:
    groceries = await _create_category(client, "Groceries")
    salary = await _create_category(client, "Salary", is_income=True)

    factory = client._session_factory  # type: ignore[attr-defined]
    async with factory() as session:
        account = Account(name="Checking", type="checking", currency="USD")
        session.add(account)
        await session.flush()

        today = date.today()
        last_month_start = (today.replace(day=1) - timedelta(days=1)).replace(day=1)

        txn1 = Transaction(
            account_id=account.id,
            posted_at=datetime(
                last_month_start.year, last_month_start.month, 15,
                tzinfo=timezone.utc,
            ),
            amount_cents=10000,
            status="final",
        )
        session.add(txn1)
        await session.flush()

        session.add(LineItem(
            transaction_id=txn1.id,
            category_id=groceries["id"],
            amount_cents=10000,
        ))

        txn2 = Transaction(
            account_id=account.id,
            posted_at=datetime(
                last_month_start.year, last_month_start.month, 1,
                tzinfo=timezone.utc,
            ),
            amount_cents=-500000,
            status="final",
        )
        session.add(txn2)
        await session.flush()

        session.add(LineItem(
            transaction_id=txn2.id,
            category_id=salary["id"],
            amount_cents=-500000,
        ))
        await session.commit()

    resp = await client.get("/api/budgets/suggestions?months=1")
    assert resp.status_code == 200
    suggestions = resp.json()
    category_ids = [s["category_id"] for s in suggestions]
    assert groceries["id"] in category_ids
    assert salary["id"] in category_ids

    salary_sug = next(s for s in suggestions if s["category_id"] == salary["id"])
    assert salary_sug["is_income"] is True
    assert salary_sug["avg_monthly_cents"] == 500000

    assert suggestions[0]["category_id"] == salary["id"]
