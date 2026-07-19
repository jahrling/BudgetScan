"""Offline test doubles + seeding helpers for the RAG layer.

Not collected by pytest (no `test_` prefix). The stub embedder is a deterministic
bag-of-tokens hash embedding: cosine similarity is high when two strings share
tokens, so retrieval is meaningful without a live Ollama.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from finance.models.account import Account
from finance.models.annotation import Annotation
from finance.models.category import Category
from finance.models.line_item import LineItem
from finance.models.transaction import Transaction
from finance.services.vector_store import SearchHit, VectorStore

_DIM = 256


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _hash_vector(text: str) -> list[float]:
    vec = [0.0] * _DIM
    for tok in _tokens(text):
        idx = int(hashlib.md5(tok.encode()).hexdigest(), 16) % _DIM
        vec[idx] += 1.0
    return vec


class StubEmbedder:
    """Deterministic offline embedder. Records how many times it was called."""

    def __init__(self) -> None:
        self.calls = 0

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [_hash_vector(t) for t in texts]


class StubGenerator:
    """Echoes the top retrieved note so tests can assert what was retrieved."""

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, query: str, hits: list[SearchHit]) -> str:
        self.calls += 1
        return hits[0].text if hits else ""


class SpyStore(VectorStore):
    """VectorStore that records whether `search` was ever called."""

    def __init__(self) -> None:
        super().__init__(path=None)
        self.searched = False

    def search(self, query_vector: list[float], *, k: int = 5) -> list[SearchHit]:
        self.searched = True
        return super().search(query_vector, k=k)


async def seed_account(session: AsyncSession) -> Account:
    acct = Account(name="Checking", type="checking", currency="USD")
    session.add(acct)
    await session.flush()
    return acct


async def seed_category(
    session: AsyncSession, name: str, parent_id: int | None = None
) -> Category:
    cat = Category(name=name, parent_id=parent_id)
    session.add(cat)
    await session.flush()
    return cat


async def add_transaction(
    session: AsyncSession,
    *,
    account_id: int,
    items: list[tuple[int, int]],  # (category_id, amount_cents)
    posted_at: datetime | None = None,
    description: str | None = None,
) -> Transaction:
    total = sum(amt for _, amt in items)
    txn = Transaction(
        account_id=account_id,
        posted_at=posted_at or datetime(2026, 6, 15, tzinfo=timezone.utc),
        amount_cents=total,
        description=description,
        status="split" if len(items) > 1 else "pending",
    )
    session.add(txn)
    await session.flush()
    for cat_id, amt in items:
        session.add(
            LineItem(
                transaction_id=txn.id,
                category_id=cat_id,
                description=description,
                amount_cents=amt,
            )
        )
    await session.flush()
    return txn


async def add_annotation(
    session: AsyncSession, text: str, transaction_id: int | None = None
) -> Annotation:
    ann = Annotation(text=text, transaction_id=transaction_id)
    session.add(ann)
    await session.flush()
    return ann
