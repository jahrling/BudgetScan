"""A tiny local vector index for the finance RAG layer.

Design constraints (ADR 0003):
- Indexes ONLY unstructured prose: manual annotations and receipt line-item
  descriptions. Entries carry the source text and a reference back to the owning
  transaction — never an amount. Numbers are answered from SQL, not from here.
- Stored locally under `data/vector/` (gitignored). No external service, no
  heavy dependency: cosine similarity is computed in pure Python, which is
  ample for personal-scale corpora.

The index is a flat JSON file. `rebuild_from_db` regenerates it from the current
annotations + line-item descriptions; `search` returns the closest entries to a
query vector.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from finance.config import settings
from finance.models.annotation import Annotation
from finance.models.line_item import LineItem
from finance.services.embeddings import Embedder


@dataclass
class VectorEntry:
    source: str  # "annotation" | "line_item"
    ref_id: int  # the annotation.id or line_item.id
    transaction_id: int | None  # owning transaction, for cross-referencing SQL
    text: str
    vector: list[float]


@dataclass
class SearchHit:
    source: str
    ref_id: int
    transaction_id: int | None
    text: str
    score: float


def _index_path() -> Path:
    return Path(settings.vector_index_dir) / "index.json"


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError(f"vector length mismatch: {len(a)} != {len(b)}")
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


class VectorStore:
    """In-memory vector index with JSON persistence.

    Not thread-safe; the app is single-user and access is request-scoped.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _index_path()
        self._entries: list[VectorEntry] = []

    # -- persistence -------------------------------------------------------

    def load(self) -> "VectorStore":
        if self._path.exists():
            raw = json.loads(self._path.read_text())
            self._entries = [VectorEntry(**e) for e in raw.get("entries", [])]
        else:
            self._entries = []
        return self

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"entries": [asdict(e) for e in self._entries]}
        # Atomic write so a crash can't leave a half-written index.
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(payload, fh)
            os.replace(tmp, self._path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    # -- mutation ----------------------------------------------------------

    def replace_all(self, entries: list[VectorEntry]) -> None:
        self._entries = list(entries)

    def __len__(self) -> int:
        return len(self._entries)

    # -- query -------------------------------------------------------------

    def search(self, query_vector: list[float], *, k: int = 5) -> list[SearchHit]:
        scored = [
            SearchHit(
                source=e.source,
                ref_id=e.ref_id,
                transaction_id=e.transaction_id,
                text=e.text,
                score=_cosine(query_vector, e.vector),
            )
            for e in self._entries
        ]
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:k]


async def collect_corpus(session: AsyncSession) -> list[tuple[str, int, int | None, str]]:
    """Gather the prose to index: (source, ref_id, transaction_id, text).

    Only free text is collected — annotations and line-item descriptions. No
    amounts are ever read here.
    """
    corpus: list[tuple[str, int, int | None, str]] = []

    ann_rows = await session.execute(select(Annotation))
    for ann in ann_rows.scalars().all():
        if ann.text and ann.text.strip():
            corpus.append(("annotation", ann.id, ann.transaction_id, ann.text.strip()))

    li_rows = await session.execute(
        select(LineItem).where(LineItem.description.is_not(None))
    )
    for li in li_rows.scalars().all():
        if li.description and li.description.strip():
            corpus.append(
                ("line_item", li.id, li.transaction_id, li.description.strip())
            )

    return corpus


async def rebuild_from_db(
    session: AsyncSession,
    embedder: Embedder,
    *,
    path: Path | None = None,
    persist: bool = True,
) -> VectorStore:
    """Re-embed the whole prose corpus and replace the on-disk index."""
    corpus = await collect_corpus(session)
    store = VectorStore(path=path)
    if not corpus:
        store.replace_all([])
        if persist:
            store.save()
        return store

    vectors = await embedder.embed([text for *_, text in corpus])
    entries = [
        VectorEntry(
            source=source,
            ref_id=ref_id,
            transaction_id=txn_id,
            text=text,
            vector=vector,
        )
        for (source, ref_id, txn_id, text), vector in zip(corpus, vectors, strict=True)
    ]
    store.replace_all(entries)
    if persist:
        store.save()
    return store
