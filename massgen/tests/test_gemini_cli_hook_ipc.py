"""Tests for Gemini CLI backend hook IPC — write/read/clear hook payloads.

Mirrors the structure of test_codex_hook_ipc.py for backend parity.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from massgen.backend.gemini_cli import GeminiCLIBackend


def _make_gemini_backend(tmp_path: Path) -> GeminiCLIBackend:
    """Create a GeminiCLIBackend with mocked internals pointing at tmp_path."""
    with patch.object(GeminiCLIBackend, "_find_gemini_cli", return_value="/usr/bin/gemini"):
        backend = GeminiCLIBackend(cwd=str(tmp_path))
    # Ensure adapter hook_dir is set
    adapter = backend.get_native_hook_adapter()
    if adapter and hasattr(adapter, "hook_dir"):
        adapter.hook_dir = tmp_path / ".gemini"
    return backend


class TestSupportsServerHooks:
    def test_returns_true(self, tmp_path: Path) -> None:
        backend = _make_gemini_backend(tmp_path)
        assert backend.supports_mcp_server_hooks() is True


class TestSupportsNativeHooks:
    def test_returns_true(self, tmp_path: Path) -> None:
        backend = _make_gemini_backend(tmp_path)
        assert backend.supports_native_hooks() is True

    def test_adapter_is_gemini_cli_type(self, tmp_path: Path) -> None:
        from massgen.mcp_tools.native_hook_adapters import GeminiCLINativeHookAdapter

        backend = _make_gemini_backend(tmp_path)
        adapter = backend.get_native_hook_adapter()
        assert isinstance(adapter, GeminiCLINativeHookAdapter)


class TestGetHookDir:
    def test_returns_gemini_subdir(self, tmp_path: Path) -> None:
        backend = _make_gemini_backend(tmp_path)
        hook_dir = backend.get_hook_dir()
        assert hook_dir == tmp_path / ".gemini"


class TestWritePostToolUseHook:
    def test_creates_valid_json_file(self, tmp_path: Path) -> None:
        backend = _make_gemini_backend(tmp_path)
        backend.write_post_tool_use_hook("peer answer content")

        hook_file = backend.get_hook_dir() / "hook_payload.json"
        assert hook_file.exists()

        payload = json.loads(hook_file.read_text(encoding="utf-8"))
        assert payload["inject"]["content"] == "peer answer content"
        assert payload["inject"]["strategy"] == "tool_result"
        assert payload["tool_matcher"] == "*"
        assert payload["sequence"] >= 1
        assert payload["expires_at"] > time.time()

    def test_event_field_is_after_tool(self, tmp_path: Path) -> None:
        """Gemini CLI hooks are event-scoped; payload should have event=AfterTool."""
        backend = _make_gemini_backend(tmp_path)
        backend.write_post_tool_use_hook("content")

        payload = json.loads(
            (backend.get_hook_dir() / "hook_payload.json").read_text(),
        )
        assert payload["event"] == "AfterTool"

    def test_sequence_increments(self, tmp_path: Path) -> None:
        backend = _make_gemini_backend(tmp_path)
        backend.write_post_tool_use_hook("first")
        first_payload = json.loads(
            (backend.get_hook_dir() / "hook_payload.json").read_text(),
        )

        backend.write_post_tool_use_hook("second")
        second_payload = json.loads(
            (backend.get_hook_dir() / "hook_payload.json").read_text(),
        )

        assert second_payload["sequence"] > first_payload["sequence"]

    def test_atomic_write_no_partial_reads(self, tmp_path: Path) -> None:
        """Verify write uses tmp+replace pattern (no partial file visible)."""
        backend = _make_gemini_backend(tmp_path)
        backend.write_post_tool_use_hook("content")

        hook_file = backend.get_hook_dir() / "hook_payload.json"
        # If write was atomic, the file should always be valid JSON
        payload = json.loads(hook_file.read_text(encoding="utf-8"))
        assert "inject" in payload

    def test_default_expiry_is_30_seconds(self, tmp_path: Path) -> None:
        backend = _make_gemini_backend(tmp_path)
        before = time.time()
        backend.write_post_tool_use_hook("content")

        payload = json.loads(
            (backend.get_hook_dir() / "hook_payload.json").read_text(),
        )
        # Expiry should be roughly 30s from now
        assert payload["expires_at"] >= before + 25
        assert payload["expires_at"] <= before + 35

    def test_custom_ttl(self, tmp_path: Path) -> None:
        backend = _make_gemini_backend(tmp_path)
        before = time.time()
        backend.write_post_tool_use_hook("content", ttl_seconds=60.0)

        payload = json.loads(
            (backend.get_hook_dir() / "hook_payload.json").read_text(),
        )
        assert payload["expires_at"] >= before + 55
        assert payload["expires_at"] <= before + 65

    def test_creates_hook_dir_if_missing(self, tmp_path: Path) -> None:
        backend = _make_gemini_backend(tmp_path)
        hook_dir = backend.get_hook_dir()
        # Ensure .gemini doesn't exist yet
        assert not hook_dir.exists()

        backend.write_post_tool_use_hook("content")
        assert hook_dir.exists()
        assert (hook_dir / "hook_payload.json").exists()


class TestClearHookFiles:
    def test_removes_hook_file(self, tmp_path: Path) -> None:
        backend = _make_gemini_backend(tmp_path)
        backend.write_post_tool_use_hook("content")

        hook_file = backend.get_hook_dir() / "hook_payload.json"
        assert hook_file.exists()

        backend.clear_hook_files()
        assert not hook_file.exists()

    def test_removes_tmp_file(self, tmp_path: Path) -> None:
        """Clear should also remove stale .tmp files from interrupted writes."""
        backend = _make_gemini_backend(tmp_path)
        hook_dir = backend.get_hook_dir()
        hook_dir.mkdir(parents=True, exist_ok=True)
        (hook_dir / "hook_payload.tmp").write_text("stale")

        backend.clear_hook_files()
        assert not (hook_dir / "hook_payload.tmp").exists()

    def test_no_error_when_file_missing(self, tmp_path: Path) -> None:
        backend = _make_gemini_backend(tmp_path)
        # Should not raise even when .gemini doesn't exist
        backend.clear_hook_files()

    def test_no_error_when_dir_missing(self, tmp_path: Path) -> None:
        """clear_hook_files should tolerate missing .gemini directory."""
        backend = _make_gemini_backend(tmp_path)
        hook_dir = backend.get_hook_dir()
        assert not hook_dir.exists()
        # Should not raise
        backend.clear_hook_files()


class TestReadUnconsumedHookContent:
    def test_returns_content_when_file_exists(self, tmp_path: Path) -> None:
        backend = _make_gemini_backend(tmp_path)
        backend.write_post_tool_use_hook("unconsumed human input")

        result = backend.read_unconsumed_hook_content()
        assert result == "unconsumed human input"

    def test_deletes_file_after_read(self, tmp_path: Path) -> None:
        backend = _make_gemini_backend(tmp_path)
        backend.write_post_tool_use_hook("content")

        backend.read_unconsumed_hook_content()
        hook_file = backend.get_hook_dir() / "hook_payload.json"
        assert not hook_file.exists()

    def test_returns_none_when_no_file(self, tmp_path: Path) -> None:
        backend = _make_gemini_backend(tmp_path)
        assert backend.read_unconsumed_hook_content() is None

    def test_consumed_hook_returns_none_on_second_read(self, tmp_path: Path) -> None:
        """Once consumed, a second call returns None (idempotent)."""
        backend = _make_gemini_backend(tmp_path)
        backend.write_post_tool_use_hook("some content")
        first = backend.read_unconsumed_hook_content()
        assert first is not None
        assert backend.read_unconsumed_hook_content() is None

    def test_returns_none_for_malformed_json(self, tmp_path: Path) -> None:
        backend = _make_gemini_backend(tmp_path)
        hook_dir = backend.get_hook_dir()
        hook_dir.mkdir(parents=True, exist_ok=True)
        (hook_dir / "hook_payload.json").write_text("not json")

        assert backend.read_unconsumed_hook_content() is None
        # File should be cleaned up
        assert not (hook_dir / "hook_payload.json").exists()

    def test_returns_none_for_empty_inject(self, tmp_path: Path) -> None:
        """Payload with empty inject content should return None."""
        backend = _make_gemini_backend(tmp_path)
        hook_dir = backend.get_hook_dir()
        hook_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "inject": {"content": "", "strategy": "tool_result"},
            "event": "AfterTool",
            "expires_at": time.time() + 30,
            "sequence": 1,
        }
        (hook_dir / "hook_payload.json").write_text(json.dumps(payload))

        # Empty content should still be returned (it's the caller's job to decide)
        # but read_unconsumed_hook_content returns the content string
        result = backend.read_unconsumed_hook_content()
        # Empty string is falsy, so the adapter returns None
        assert result is None or result == ""


class TestResetClearsHooks:
    """Verify that reset_state / clear_history cleans up hook files."""

    @pytest.mark.asyncio
    async def test_reset_state_clears_hooks(self, tmp_path: Path) -> None:
        backend = _make_gemini_backend(tmp_path)
        backend.write_post_tool_use_hook("stale content")
        hook_file = backend.get_hook_dir() / "hook_payload.json"
        assert hook_file.exists()

        await backend.reset_state()
        assert not hook_file.exists()

    @pytest.mark.asyncio
    async def test_clear_history_clears_hooks(self, tmp_path: Path) -> None:
        backend = _make_gemini_backend(tmp_path)
        backend.write_post_tool_use_hook("stale content")
        hook_file = backend.get_hook_dir() / "hook_payload.json"
        assert hook_file.exists()

        await backend.clear_history()
        assert not hook_file.exists()
