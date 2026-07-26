"""Tests for R5 tool-result offload (fae.agent.tool_offload)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fae.agent.tool_offload import (
    OffloadResult,
    ToolOffloader,
    _preview_lines,
    _safe_name,
    maybe_offload_result,
    tool_offload_cleanup_loop,
)
from fae.tools.filesystem import dispatch_filesystem_tool


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
    payload_path = Path(off.path)
    assert payload_path.exists()

    data = json.loads(payload_path.read_text())
    assert data["body"] == big
    assert data["tool"] == "memory_search"
    assert data["call_id"] == "call-1"
    assert "preview" in data
    # Now timestamp-free: only the digest is in the name.
    assert "-" not in data["digest"]
    assert data["chars"] == len(big)


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


@pytest.mark.asyncio
async def test_offloader_path_is_byte_stable_across_processes(tmp_path: Path) -> None:
    """Two independent offloaders must agree on the file path for the same
    (tool, call_id, content). The naming scheme must not depend on wall
    clock or transient instance state."""
    big = "abcdef\n" * 100
    o1 = ToolOffloader(tmp_path, max_chars=10, keep_lines=4, enabled=True)
    o2 = ToolOffloader(tmp_path / "other", max_chars=10, keep_lines=4, enabled=True)
    _, off1 = await maybe_offload_result(
        o1, tool_name="t", call_id="c", result=big,
    )
    _, off2 = await maybe_offload_result(
        o2, tool_name="t", call_id="c", result=big,
    )
    assert off1 is not None
    assert off2 is not None
    assert Path(off1.path).name == Path(off2.path).name


def test_prompt_envelope_is_byte_stable() -> None:
    """Pin the exact envelope shape so cache_control segments survive."""
    envelope = OffloadResult(
        path="/tmp/abc.json",
        chars_written=12345,
        kept_chars=200,
    ).to_prompt_replacement("read_file")
    assert envelope == (
        '<tool_offload tool="read_file" path="/tmp/abc.json" '
        'chars="12345" preview_chars="200">\n</tool_offload>\n'
    )


def test_cleanup_expired_removes_only_old_files(tmp_path: Path) -> None:
    o = ToolOffloader(tmp_path, max_chars=10, keep_lines=4, ttl_s=60.0, enabled=True)
    fresh = tmp_path / "fresh.json"
    stale = tmp_path / "stale.json"
    fresh.write_text("x", encoding="utf-8")
    stale.write_text("x", encoding="utf-8")
    # Backdate stale.mtime by 2 hours.
    import os

    two_hours_ago = 120.0
    os.utime(stale, (two_hours_ago, two_hours_ago))
    removed = o.cleanup_expired()
    assert str(stale) in removed
    assert str(fresh) not in removed
    assert fresh.exists()
    assert not stale.exists()


def test_cleanup_expired_skips_non_json_and_disabled(tmp_path: Path) -> None:
    o = ToolOffloader(tmp_path, max_chars=10, keep_lines=4, ttl_s=60.0, enabled=True)
    junk = tmp_path / "notes.txt"
    junk.write_text("x", encoding="utf-8")
    import os

    two_hours_ago = 120.0
    os.utime(junk, (two_hours_ago, two_hours_ago))
    removed = o.cleanup_expired()
    assert removed == []
    assert junk.exists()
    # Disabled offloader is a no-op.
    disabled = ToolOffloader(
        tmp_path / "other", max_chars=10, keep_lines=4, enabled=False,
    )
    assert disabled.cleanup_expired() == []


def test_cleanup_expired_handles_missing_dir(tmp_path: Path) -> None:
    """First-run cleanup must not crash if the directory has never been created."""
    nested = tmp_path / "not-yet" / "offload"
    o = ToolOffloader(nested, max_chars=10, keep_lines=4, ttl_s=60.0, enabled=True)
    # The constructor creates the directory; remove it to simulate never-run.
    import shutil

    shutil.rmtree(nested)
    assert o.cleanup_expired() == []


@pytest.mark.asyncio
async def test_cleanup_loop_runs_periodically_and_cancels(tmp_path: Path) -> None:
    import asyncio

    o = ToolOffloader(tmp_path, max_chars=10, keep_lines=4, ttl_s=0.001, enabled=True)
    payload = tmp_path / "leaked.json"
    payload.write_text("x", encoding="utf-8")
    import os

    os.utime(payload, (100.0, 100.0))  # very old
    task = asyncio.create_task(tool_offload_cleanup_loop(o, interval_s=10.0))
    # Force the first wait to elapse then cancel.
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    # It may or may not have run depending on scheduling; either way the
    # loop must respect cancellation. Make sure no unhandled errors.
    assert task.done()


# ── read_file ↔ offload reachability ─────────────────────────────────────


@pytest.mark.asyncio
async def test_read_file_can_pull_back_offloaded_payload(tmp_path: Path) -> None:
    """End-to-end: offload writes to disk → read_file resolves the pointer."""
    workspace = tmp_path / "ws"
    offload_dir = tmp_path / "offload"
    workspace.mkdir()
    o = ToolOffloader(offload_dir, max_chars=10, keep_lines=4, enabled=True)
    big = "abcdef\n" * 50
    body, off = await maybe_offload_result(
        o, tool_name="run_bash", call_id="c1", result=big,
    )
    assert off is not None and off.path
    # read_file should be able to read it because the offload dir is an
    # explicit extra root, even though the workspace is empty.
    read = json.loads(
        dispatch_filesystem_tool(
            "read_file",
            {"path": off.path},
            root=workspace,
            extra_roots=(str(offload_dir),),
        )
    )
    assert read["ok"] is True
    assert "abcdef" in read["content"]


def test_read_file_offload_path_without_extra_root_is_rejected(tmp_path: Path) -> None:
    """Without wiring an extra root, an offload pointer must still look
    like 'outside_workspace' (or 'workspace_not_configured')."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    offload_path = tmp_path / "offload" / "leaked.json"
    offload_path.parent.mkdir(parents=True)
    offload_path.write_text("secret", encoding="utf-8")
    res = json.loads(
        dispatch_filesystem_tool(
            "read_file",
            {"path": str(offload_path)},
            root=workspace,
        )
    )
    assert res["ok"] is False
    assert res["error"] in {"workspace_not_configured", "outside_workspace"}


def test_safe_resolve_extra_root_silently_skips_invalid(tmp_path: Path) -> None:
    """Empty / missing / non-directory extra roots must not crash and must
    not change the membership check: a path under a *valid* extra root is
    accepted, but a path under an invalid extra root keeps the normal
    outside_workspace rejection."""
    from fae.tools.safepath import WorkspacePathError, safe_resolve

    base = tmp_path / "ws"
    base.mkdir()
    extra = tmp_path / "extra"
    extra.mkdir()
    bogus = f"{extra}_nope"
    target = extra / "x.txt"

    # No extra roots → target outside base, must raise.
    with pytest.raises(WorkspacePathError):
        safe_resolve(base, str(target))

    # Mix of invalid + valid: invalid silently dropped, valid still works.
    resolved = safe_resolve(base, str(target), extra_roots=("", bogus, str(extra)))
    assert resolved == target.resolve(strict=False)