"""Seed default category tree. Idempotent — skips categories that already exist by name."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from finance.db import async_session_factory, init_db
from finance.models.category import Category

CATEGORY_TREE: dict[str, list[str]] = {
    "Food": ["Groceries", "Dining", "Coffee & Snacks"],
    "Transport": ["Gas", "Parking", "Public Transit", "Rideshare"],
    "Household": ["Rent/Mortgage", "Utilities", "Maintenance", "Furnishings"],
    "Personal": ["Clothing", "Health", "Haircare", "Subscriptions"],
    "Entertainment": ["Streaming", "Games", "Events", "Hobbies"],
    "Kids": ["School", "Activities", "Childcare", "Toys"],
    "Pets": ["Pet Food", "Vet", "Grooming"],
    "Savings": ["Emergency Fund", "Vacation", "Big Purchases"],
}


async def seed(session: AsyncSession) -> None:
    for parent_name, children in CATEGORY_TREE.items():
        existing = await session.execute(
            select(Category).where(
                Category.name == parent_name, Category.parent_id.is_(None)
            )
        )
        parent = existing.scalar_one_or_none()
        if parent is None:
            parent = Category(name=parent_name)
            session.add(parent)
            await session.flush()
            print(f"  + {parent_name}")
        else:
            print(f"  = {parent_name} (exists)")

        for child_name in children:
            existing_child = await session.execute(
                select(Category).where(
                    Category.name == child_name, Category.parent_id == parent.id
                )
            )
            if existing_child.scalar_one_or_none() is None:
                session.add(Category(name=child_name, parent_id=parent.id))
                print(f"    + {child_name}")
            else:
                print(f"    = {child_name} (exists)")

    await session.commit()


async def main() -> None:
    await init_db()
    async with async_session_factory() as session:
        print("Seeding categories...")
        await seed(session)
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
