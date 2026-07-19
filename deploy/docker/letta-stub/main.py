"""Letta health stub for Phase 1.1 compose. Memory APIs land in Phase 2."""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="FAE Letta Stub")


@app.get("/v1/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "letta-stub"}
