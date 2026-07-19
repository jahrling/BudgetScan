"""Text embeddings via Ollama's local `nomic-embed-text` model.

This is the ONLY embedding path for the finance RAG layer. It embeds prose —
manual annotations and receipt line-item descriptions — never transaction
numbers (see ADR 0003). The Ollama endpoint stays bound to 127.0.0.1:11434.

The module exposes a small, injectable protocol (`Embedder`) so callers and
tests can swap the real Ollama client for a deterministic stub without a live
model.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import httpx

from finance.config import settings


@runtime_checkable
class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class OllamaEmbedder:
    """Calls Ollama `/api/embeddings` once per text.

    Ollama's embeddings endpoint takes a single `prompt`, so we issue one call
    per input. For personal-scale corpora (hundreds–low-thousands of notes)
    this is fine; batching can be added later if the index grows.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self._base_url = (base_url or settings.ollama_url).rstrip("/")
        self._model = model or settings.ollama_embed_model
        self._timeout = timeout if timeout is not None else settings.ollama_timeout_seconds

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        url = f"{self._base_url}/api/embeddings"
        out: list[list[float]] = []
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for text in texts:
                resp = await client.post(
                    url, json={"model": self._model, "prompt": text}
                )
                resp.raise_for_status()
                vec = resp.json().get("embedding")
                if not isinstance(vec, list) or not vec:
                    raise RuntimeError(
                        f"Ollama returned no embedding for model {self._model!r}"
                    )
                out.append([float(x) for x in vec])
        return out


def default_embedder() -> Embedder:
    return OllamaEmbedder()
