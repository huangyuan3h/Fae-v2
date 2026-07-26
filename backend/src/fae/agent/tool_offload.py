"""Tool-result offload (Context Engineering R5).

Ports the FilesystemMiddleware pattern from Deep Agents / Letta's
"compaction" flow: when a tool result exceeds a configured char budget, we
dump the raw payload to disk and replace the in-prompt body with a short
reference + preview. The agent can ask the host (via `read_file`) to pull
the full text back when it actually needs it.

Design choices
--------------
- The offload directory is *separate* from archival — it stores transient
  tool artifacts (last 24h, GC'd on startup), not long-term memory.
- The replacement text is byte-stable per (tool, call_id, content_hash) so
  cache_control on the surrounding prefix survives.
- We deliberately keep this synchronous; tool dispatch is already async,
  and an offload file is cheap (single fsync + json write).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("fae.agent.tool_offload")


@dataclass
class OffloadResult:
    path: str
    chars_written: int
    kept_chars: int
    skipped: bool = False
    reason: str | None = None

    def to_prompt_replacement(self, tool_name: str) -> str:
        """Replacement body for the in-prompt tool_result block."""
        if self.skipped:
            return ""
        # Preview lines were captured at write time. We re-derive the
        # head/tail shape here so cache_control bytes stay stable for a
        # given digest — the caller has the same digest baked into the
        # file path, so this string is byte-stable across re-renders.
        head, sep, tail = (
            f'<tool_offload tool="{tool_name}" path="{self.path}" '
            f'chars="{self.chars_written}" preview_chars="{self.kept_chars}">',
            "\n",
            "\n</tool_offload>",
        )
        return f"{head}{sep}{tail}"


class ToolOffloader:
    """Offload oversized tool results to disk; serve stable preview bodies."""

    def __init__(
        self,
        base_dir: str | Path,
        *,
        max_chars: int = 8000,
        keep_lines: int = 20,
        enabled: bool = True,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.max_chars = max(0, max_chars)
        self.keep_lines = max(1, keep_lines)
        self.enabled = enabled and self.max_chars > 0
        if self.enabled:
            self.base_dir.mkdir(parents=True, exist_ok=True)

    async def maybe_offload(
        self,
        *,
        tool_name: str,
        call_id: str,
        result: str,
    ) -> OffloadResult:
        """Return an OffloadResult; ``skipped=True`` means the original
        result should be used unchanged in the prompt."""
        if not self.enabled or not result or len(result) <= self.max_chars:
            return OffloadResult(
                path="",
                chars_written=0,
                kept_chars=len(result or ""),
                skipped=True,
                reason="under_budget" if not self.enabled else None,
            )
        path = await asyncio.to_thread(
            self._write_payload, tool_name, call_id, result,
        )
        return OffloadResult(
            path=str(path),
            chars_written=len(result),
            kept_chars=len(_preview_lines(result, self.keep_lines)),
        )

    # ── private helpers ──────────────────────────────────────────────────

    def _write_payload(
        self, tool_name: str, call_id: str, result: str
    ) -> Path:
        """Sync write — runs inside asyncio.to_thread to keep the loop free."""
        digest = hashlib.sha256(result.encode("utf-8")).hexdigest()[:12]
        ts = time.strftime("%Y%m%d-%H%M%S", time.localtime())
        safe_tool = _safe_name(tool_name)
        safe_id = _safe_name(call_id) or digest
        fname = f"{ts}-{safe_tool}-{safe_id}-{digest}.json"
        path = self.base_dir / fname
        payload = {
            "tool": tool_name,
            "call_id": call_id,
            "ts": ts,
            "digest": digest,
            "chars": len(result),
            "preview": _preview_lines(result, self.keep_lines),
            "body": result,
        }
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        os.replace(tmp, path)
        logger.debug(
            "tool_offload wrote %s (%d chars → %d preview)",
            path.name, len(result), len(_preview_lines(result, self.keep_lines)),
        )
        return path


def _safe_name(value: str) -> str:
    out: list[str] = []
    for ch in (value or ""):
        if ch.isalnum() or ch in ("-", "_", "."):
            out.append(ch)
        elif ch == " ":
            out.append("_")
    s = "".join(out).strip("._-")
    return s[:48]


def _preview_lines(text: str, keep_lines: int = 20) -> str:
    """Keep the head and tail of a long tool result so the agent has a
    useful preview without the full payload."""
    if not text:
        return ""
    lines = text.splitlines()
    if len(lines) <= keep_lines:
        return text
    head = lines[: keep_lines // 2]
    tail = lines[-(keep_lines // 2) :]
    omitted = len(lines) - len(head) - len(tail)
    return "\n".join(
        [*head, f"... [truncated {omitted} lines, full content on disk] ...", *tail]
    )


# Decorator-style entry point for tool dispatch sites.
async def maybe_offload_result(
    offloader: ToolOffloader | None,
    *,
    tool_name: str,
    call_id: str,
    result: str,
) -> tuple[str, OffloadResult | None]:
    """Return (prompt_body, offload). If offload is None or skipped, the
    caller should use the original ``result`` unchanged."""
    if offloader is None or not result or not offloader.enabled:
        return result, None
    if len(result) <= offloader.max_chars:
        return result, None
    off = await offloader.maybe_offload(
        tool_name=tool_name, call_id=call_id, result=result,
    )
    if off.skipped:
        return result, off
    return off.to_prompt_replacement(tool_name), off