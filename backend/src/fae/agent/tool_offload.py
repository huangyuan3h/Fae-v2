"""Tool-result offload (Context Engineering R5).

Ports the FilesystemMiddleware pattern from Deep Agents / Letta's
"compaction" flow: when a tool result exceeds a configured char budget, we
dump the raw payload to disk and replace the in-prompt body with a short
reference + preview. The agent can ask the host (via `read_file`) to pull
the full text back when it actually needs it.

Design choices
--------------
- The offload directory is *separate* from archival — it stores transient
  tool artifacts with a TTL-based GC, not long-term memory.
- The replacement text is byte-stable per (tool, call_id, content_hash) so
  cache_control on the surrounding prefix survives.
- File names encode only the content digest (and tool / call_id for human
  readability) — no wall-clock timestamp, so the same content always
  lands at the same path across processes.
- We deliberately keep writes synchronous (running inside
  ``asyncio.to_thread``); an offload file is cheap (single fsync + json).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
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
        """Replacement body for the in-prompt tool_result block.

        The shape is locked for cache_control byte-stability across re-renders
        and across processes; tests pin the exact string (see
        ``tests/test_tool_offload.py::test_prompt_envelope_is_byte_stable``).
        """
        if self.skipped:
            return ""
        body = (
            f'<tool_offload tool="{tool_name}" path="{self.path}" '
            f'chars="{self.chars_written}" preview_chars="{self.kept_chars}">\n'
            f"</tool_offload>\n"
        )
        return body


class ToolOffloader:
    """Offload oversized tool results to disk; serve stable preview bodies."""

    def __init__(
        self,
        base_dir: str | Path,
        *,
        max_chars: int = 8000,
        keep_lines: int = 20,
        ttl_s: float = 86_400.0,
        enabled: bool = True,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.max_chars = max(0, max_chars)
        self.keep_lines = max(1, keep_lines)
        self.ttl_s = max(0.0, ttl_s)
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
                reason="under_budget" if self.enabled else "disabled",
            )
        path = await asyncio.to_thread(
            self._write_payload, tool_name, call_id, result,
        )
        return OffloadResult(
            path=str(path),
            chars_written=len(result),
            kept_chars=len(_preview_lines(result, self.keep_lines)),
        )

    def cleanup_expired(self, *, now: float | None = None) -> list[str]:
        """Remove offload files older than ``self.ttl_s``.

        Returns the absolute paths of files that were removed. Safe to
        call repeatedly; never raises — errors are logged and skipped.
        """
        if not self.enabled:
            return []
        ttl = self.ttl_s
        if ttl <= 0:
            return []
        cutoff = (now if now is not None else _now()) - ttl
        removed: list[str] = []
        try:
            for entry in self.base_dir.iterdir():
                if not entry.is_file():
                    continue
                if entry.suffix != ".json":
                    continue
                try:
                    mtime = entry.stat().st_mtime
                except OSError:
                    continue
                if mtime >= cutoff:
                    continue
                try:
                    entry.unlink()
                    removed.append(str(entry))
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    logger.warning(
                        "tool_offload failed to remove %s: %s", entry, exc,
                    )
        except FileNotFoundError:
            # Base dir may not exist yet on first run; nothing to clean.
            return []
        return removed

    # ── private helpers ──────────────────────────────────────────────────

    def _write_payload(
        self, tool_name: str, call_id: str, result: str
    ) -> Path:
        """Sync write — runs inside asyncio.to_thread to keep the loop free."""
        digest = hashlib.sha256(result.encode("utf-8")).hexdigest()[:12]
        safe_tool = _safe_name(tool_name) or "tool"
        safe_id = _safe_name(call_id) or digest
        fname = f"{safe_tool}-{safe_id}-{digest}.json"
        path = self.base_dir / fname
        payload = {
            "tool": tool_name,
            "call_id": call_id,
            "digest": digest,
            "chars": len(result),
            "preview": _preview_lines(result, self.keep_lines),
            "body": result,
        }
        # Idempotent overwrite: same content always lands on same path.
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        os.replace(tmp, path)
        logger.debug(
            "tool_offload wrote %s (%d chars → %d preview)",
            path.name, len(result), len(_preview_lines(result, self.keep_lines)),
        )
        return path


def _now() -> float:
    import time as _time

    return _time.time()


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


async def tool_offload_cleanup_loop(
    offloader: "ToolOffloader",
    interval_s: float,
) -> None:
    """Periodic background sweep. Cancel the surrounding task to stop."""
    interval = max(10.0, interval_s)
    while True:
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            return
        try:
            removed = offloader.cleanup_expired()
        except Exception:  # noqa: BLE001
            logger.exception("tool_offload sweep failed")
            removed = []
        if removed:
            logger.info(
                "tool_offload sweep removed %d file(s)", len(removed),
            )