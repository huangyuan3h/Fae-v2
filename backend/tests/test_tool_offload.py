"""Tests for R5 tool-result offload (fae.agent.tool_offload)."""

from __future__ import annotations

from pathlib import Path

import pytest

from fae.agent.tool_offload import (
    OffloadResult,
    ToolOffloader,
    _preview_lines,
    _safe_name,
    maybe_offload_result,
)


@pytest.mark.asyncio
async def test_offloader_skips_small_results(tmp_path: Path) -> None:
    o = ToolOffloader(tmp_path, max_chars=200, keep_lines=10, enabled=True)
    body, off = await maybe_offload_result(
        o, tool_name="memory_search", call_id="c1", result="short"
    )
    assert off is None
    assert body == "short"


@pytest.mark.asyncio
async def test_offloader_writes_payload_and_returns_pointer(tmp_path: Path) -> None:
    o = ToolOffloader(tmp_path, max_chars=100, keep_lines=6, enabled=True)
    big = ("line one\n" * 200).strip()
    body, off = await maybe_offload_result(
        o, tool_name="memory_search", call_id="call-1", result=big
    )
    assert off is not None
    assert not off.skipped
    assert off.chars_written == len(big)
    assert off.kept_chars < len(big)
    assert "tool_offload" in body
    assert "memory_search" in body
    assert off.path
    # File exists and is valid JSON containing the full body.
    payload_path = Path(off.path)
    assert payload_path.exists()
    import json as _json

    data = _json.loads(payload_path.read_text())
    assert data["body"] == big
    assert data["tool"] == "memory_search"
    assert data["call_id"] == "call-1"
    assert "preview" in data


@pytest.mark.asyncio
async def test_offloader_disabled_returns_none(tmp_path: Path) -> None:
    o = ToolOffloader(tmp_path, max_chars=0, keep_lines=10, enabled=False)
    body, off = await maybe_offload_result(
        o, tool_name="weather", call_id="c", result="x" * 9999
    )
    assert off is None
    assert body == "x" * 9999


def test_safe_name_strips_path_chars() -> None:
    assert _safe_name("foo/bar baz?") == "foobar_baz"
    assert _safe_name("") == ""
    assert _safe_name("a" * 100) == "a" * 48


def test_preview_keeps_head_and_tail() -> None:
    text = "\n".join(f"line {i}" for i in range(1000))
    preview = _preview_lines(text, keep_lines=20)
    assert preview.count("\n") < 100  # heavily truncated
    assert "line 0" in preview
    assert "line 999" in preview
    assert "truncated" in preview


def test_preview_passthrough_for_short_text() -> None:
    text = "a\nb\nc"
    assert _preview_lines(text, keep_lines=20) == text


@pytest.mark.asyncio
async def test_offloader_replacement_is_byte_stable(tmp_path: Path) -> None:
    """Same content → same digest → same file name + replacement body."""
    o = ToolOffloader(tmp_path, max_chars=10, keep_lines=4, enabled=True)
    big = "abcdef\n" * 100
    body1, off1 = await maybe_offload_result(
        o, tool_name="t", call_id="c", result=big
    )
    body2, off2 = await maybe_offload_result(
        o, tool_name="t", call_id="c", result=big
    )
    assert body1 == body2
    assert off1.path == off2.path
    # Digest is part of the path so cache_control segment is stable.
    assert off1.path == off2.path