"""Serve project documentation markdown files."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from finance.auth.dependencies import current_user

DOCS_DIR = Path(os.environ.get("DOCS_DIR", Path(__file__).resolve().parents[4] / "docs"))

router = APIRouter(prefix="/api/docs", tags=["docs"], dependencies=[Depends(current_user)])


@router.get("")
async def list_docs() -> list[dict[str, str]]:
    if not DOCS_DIR.is_dir():
        return []
    return [
        {"slug": p.stem, "filename": p.name}
        for p in sorted(DOCS_DIR.glob("*.md"))
    ]


@router.get("/{slug}")
async def get_doc(slug: str) -> dict[str, str]:
    safe = Path(slug).name
    path = DOCS_DIR / f"{safe}.md"
    if not path.is_file() or not path.resolve().is_relative_to(DOCS_DIR.resolve()):
        raise HTTPException(404, "Document not found")
    return {"slug": safe, "filename": path.name, "content": path.read_text()}
