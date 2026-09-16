"""Investment domain: type vocabulary, budget exclusion, and account retype."""

from datetime import date, datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from finance.models.account import Account
from finance.models.budget import Budget
from finance.models.category import Category
from finance.models.line_item import LineItem
from finance.models.transaction import Transaction
from finance.scripts.retype_accounts import resolve
from finance.services import aggregation
from finance.services.account import (
    ACCOUNT_TYPES,
    CASH_FLOW_ACCOUNT_TYPES,
    INVESTMENT_ACCOUNT_TYPES,
)
from finance.services.budget import get_budget_status


# -- 1. Type vocabulary -------------------------------------------------------


def test_vocabulary_is_closed():
    assert ACCOUNT_TYPES == CASH_FLOW_ACCOUNT_TYPES | INVESTMENT_ACCOUNT_TYPES


def test_subsets_do_not_overlap():
    assert CASH_FLOW_ACCOUNT_TYPES & INVESTMENT_ACCOUNT_TYPES == frozenset()


def test_investment_types_are_nonempty():
    assert len(INVESTMENT_ACCOUNT_TYPES) > 0
    assert len(CASH_FLOW_ACCOUNT_TYPES) > 0


# -- 2. Budget exclusion ------------------------------------------------------


async def _seed_parallel_txns(session: AsyncSession):
    """Create identical transactions on checking and brokerage accounts."""
    checking = Account(name="Checking", type="checking", currency="USD")
    brokerage = Account(name="Brokerage", type="brokerage", currency="USD")
    session.add_all([checking, brokerage])
    await session.flush()

    cat = Category(name="Groceries")
    session.add(cat)
    await session.flush()

    posted = datetime(2026, 6, 15, tzinfo=timezone.utc)
    for acct in (checking, brokerage):
        txn = Transaction(
            account_id=acct.id,
            posted_at=posted,
            amount_cents=-5000,
            description="Test purchase",
            status="pending",
        )
        session.add(txn)
        await session.flush()
        session.add(
            LineItem(
                transaction_id=txn.id,
                category_id=cat.id,
                description="Test item",
                amount_cents=-5000,
            )
        )
    await session.flush()
    return checking, brokerage, cat


async def test_total_spend_excludes_investment_account(session: AsyncSession):
    checking, brokerage, cat = await _seed_parallel_txns(session)
    total = await aggregation.total_spend(session)
    assert total == -5000


async def test_spend_by_category_excludes_investment_account(session: AsyncSession):
    checking, brokerage, cat = await _seed_parallel_txns(session)
    rows = await aggregation.spend_by_category(session)
    totals = {r.category_name: r.total_cents for r in rows}
    assert totals["Groceries"] == -5000


async def test_budget_status_excludes_investment_account(session: AsyncSession):
    checking, brokerage, cat = await _seed_parallel_txns(session)
    budget = Budget(
        category_id=cat.id,
        year_month="2026-06",
        period="monthly",
        amount_cents=10000,
        start_date=date(2026, 6, 1),
    )
    session.add(budget)
    await session.flush()

    statuses = await get_budget_status(
        session,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
        year_month="2026-06",
    )
    assert len(statuses) == 1
    assert statuses[0]["spent_cents"] == 5000


async def test_checking_transaction_included(session: AsyncSession):
    checking, brokerage, cat = await _seed_parallel_txns(session)
    total = await aggregation.total_spend(
        session, category_ids=[cat.id]
    )
    assert total == -5000


# -- 3. Retype script resolve() -----------------------------------------------


@pytest.mark.parametrize(
    "name, quicken_type, expected_type",
    [
        ("My Checking", "Bank", "checking"),
        ("Rewards Visa Card", "CCard", "credit"),
        ("College Fund", "Oth A", "asset"),
        ("Fidelity Brokerage", "Port", "brokerage"),
        ("Cash Management (Individual - TOD) XX297", "Invst", "brokerage"),
        ("WATTS WATER TECH 401(k) XX7263", "401(k)/403(b)", "401k"),
        ("Student Loan", "\x01", "loan"),
        ("Home Mortgage", "\x01", "mortgage"),
        ("Roth Contributory IRA ...217", "Invst", "roth_ira"),
        ("Conrad's HSA Fidelity Go XX0882", "Invst", "hsa"),
        ("Iowa 529 - Archer x02", "Invst", "529"),
        ("Contributory ...988", "Invst", "ira"),
    ],
)
def test_resolve_maps_quicken_types(name, quicken_type, expected_type):
    result_type, reason = resolve(name, quicken_type)
    assert result_type == expected_type
    assert result_type in ACCOUNT_TYPES


def test_resolve_returns_none_for_unknown():
    result_type, reason = resolve("Something Unknown 12345", "")
    assert result_type is None
    assert "UNRESOLVED" in reason


def test_resolve_returns_none_when_no_quicken_type_and_no_name_match():
    result_type, reason = resolve("Mystery Account", None)
    assert result_type is None
    assert "UNRESOLVED" in reason
