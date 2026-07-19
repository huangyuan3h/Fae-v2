"""Optional OpenAI-compatible embeddings for archival search."""

from __future__ import annotations

import logging
from typing import Callable

import httpx

logger = logging.getLogger("fae.memory.embeddings")

EmbedFn = Callable[[str], list[float]]


class OpenAICompatibleEmbedder:
    """POST {base}/embeddings — OpenAI-compatible."""

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str = "",
        model: str = "text-embedding-3-small",
        timeout_s: float = 15.0,
        dimensions: int | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = (api_key or "").strip()
        self.model = model
        self.timeout_s = timeout_s
        self.dimensions = dimensions
        self._dim: int | None = dimensions
        self._http = httpx.Client(
            base_url=self.base_url,
            timeout=timeout_s,
            headers=(
                {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
            ),
        )

    @property
    def vector_size(self) -> int:
        if self._dim is None:
            # Probe once with a tiny string.
            vec = self.embed("probe")
            self._dim = len(vec)
        return self._dim

    def embed(self, text: str) -> list[float]:
        body: dict = {
            "model": self.model,
            "input": text or " ",
        }
        if self.dimensions is not None:
            body["dimensions"] = self.dimensions
        resp = self._http.post("/embeddings", json=body)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("data") or []
        if not items:
            raise RuntimeError("embeddings response missing data")
        vec = list(items[0]["embedding"])
        if self._dim is None:
            self._dim = len(vec)
        return vec

    def close(self) -> None:
        self._http.close()


def build_embedder(
    *,
    base_url: str,
    api_key: str = "",
    model: str = "text-embedding-3-small",
    dimensions: int | None = None,
) -> OpenAICompatibleEmbedder | None:
    url = (base_url or "").strip()
    if not url:
        return None
    try:
        embedder = OpenAICompatibleEmbedder(
            url,
            api_key=api_key,
            model=model,
            dimensions=dimensions,
        )
        # Fail fast if misconfigured
        _ = embedder.vector_size
        logger.info(
            "Archival embeddings ready model=%s dim=%s url=%s",
            model,
            embedder.vector_size,
            url,
        )
        return embedder
    except Exception:  # noqa: BLE001
        logger.exception("Failed to init embeddings at %s — staying on stub", url)
        return None
