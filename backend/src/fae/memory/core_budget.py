"""Core memory block size accounting (Phase 2.3)."""

from __future__ import annotations

from typing import Any


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars / token)."""
    return max(0, (len(text or "") + 3) // 4)


def measure_block(label: str, value: str) -> dict[str, Any]:
    text = value or ""
    return {
        "label": label,
        "chars": len(text),
        "tokens_est": estimate_tokens(text),
    }


def truncate_current(value: str, *, char_limit: int) -> str:
    """Keep the tail of current working memory within the budget."""
    text = value or ""
    if char_limit <= 0 or len(text) <= char_limit:
        return text
    return text[-char_limit:]


async def core_stats_from_client(client: Any) -> dict[str, Any]:
    """Read persona/human/current and return size stats."""
    labels = ("persona", "human", "current")
    blocks: dict[str, Any] = {}
    if client is None or not hasattr(client, "get_block"):
        for label in labels:
            blocks[label] = measure_block(label, "")
        return {"blocks": blocks, "total_chars": 0, "total_tokens_est": 0}

    total_chars = 0
    total_tokens = 0
    for label in labels:
        value = await client.get_block(label)
        info = measure_block(label, value)
        blocks[label] = info
        total_chars += info["chars"]
        total_tokens += info["tokens_est"]
    return {
        "blocks": blocks,
        "total_chars": total_chars,
        "total_tokens_est": total_tokens,
    }
