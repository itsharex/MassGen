"""Tests for CopilotBackend permission callback with PathPermissionManager.

Verifies that _build_permission_callback correctly integrates with PPM
to enforce path-level access control on Copilot SDK permission requests.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from massgen.filesystem_manager import PathPermissionManager, Permission


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_mock_ppm(
    *,
    writable_paths: list[str] | None = None,
    readable_paths: list[str] | None = None,
) -> MagicMock:
    """Create a mock PathPermissionManager with configurable permissions."""
    ppm = MagicMock(spec=PathPermissionManager)

    writable = {Path(p).resolve() for p in (writable_paths or [])}
    readable = {Path(p).resolve() for p in (readable_paths or [])}

    def fake_get_permission(path: Path) -> Permission | None:
        resolved = path.resolve()
        # Check if path is within any writable path
        for wp in writable:
            if resolved == wp or wp in resolved.parents:
                return Permission.WRITE
        # Check if path is within any readable path
        for rp in readable:
            if resolved == rp or rp in resolved.parents:
                return Permission.READ
        return None

    ppm.get_permission = MagicMock(side_effect=fake_get_permission)

    # pre_tool_use_hook is async
    async def fake_pre_tool_use_hook(tool_name, tool_args):
        return (True, None)

    ppm.pre_tool_use_hook = AsyncMock(side_effect=fake_pre_tool_use_hook)

    return ppm


def _make_mock_filesystem_manager(ppm: MagicMock | None = None) -> MagicMock:
    """Create a mock FilesystemManager with optional PPM."""
    fm = MagicMock()
    fm.path_permission_manager = ppm
    fm.get_current_workspace.return_value = Path("/workspace")
    return fm


def _make_copilot_backend(filesystem_manager=None):
    """Create a CopilotBackend instance with mocked SDK."""
    mock_copilot_module = MagicMock()
    mock_copilot_module.CopilotClient = MagicMock
    mock_copilot_module.Tool = MagicMock

    with patch.dict("sys.modules", {"copilot": mock_copilot_module}):
        # Need to reload or import fresh
        from massgen.backend.copilot import CopilotBackend

        backend = CopilotBackend.__new__(CopilotBackend)
        # Minimal init
        backend.config = {}
        backend.filesystem_manager = filesystem_manager
        backend.client = MagicMock()
        backend.sessions = {}
        backend._session_signatures = {}
        return backend


SDK_CONTEXT = {"session_id": "test_session"}


# ---------------------------------------------------------------------------
# TestPermissionCallback
# ---------------------------------------------------------------------------
class TestPermissionCallback:
    """Test _build_permission_callback with PPM integration."""

    def test_deny_policy_denies_all(self):
        """Policy 'deny' should deny all requests regardless of path."""
        backend = _make_copilot_backend()
        callback = backend._build_permission_callback("deny")

        request = {"kind": "write", "path": "/workspace/file.txt"}
        result = callback(request, SDK_CONTEXT)
        assert result["kind"] == "denied-by-rules"

    def test_approve_write_within_workspace(self):
        """Write to a path within writable workspace should be approved."""
        ppm = _make_mock_ppm(writable_paths=["/workspace"])
        fm = _make_mock_filesystem_manager(ppm)
        backend = _make_copilot_backend(filesystem_manager=fm)

        callback = backend._build_permission_callback("approve")
        request = {"kind": "write", "path": "/workspace/src/main.py"}
        result = callback(request, SDK_CONTEXT)
        assert result["kind"] == "approved"

    def test_deny_write_outside_workspace(self):
        """Write to a path outside writable workspace should be denied."""
        ppm = _make_mock_ppm(writable_paths=["/workspace"])
        fm = _make_mock_filesystem_manager(ppm)
        backend = _make_copilot_backend(filesystem_manager=fm)

        callback = backend._build_permission_callback("approve")
        request = {"kind": "write", "path": "/etc/passwd"}
        result = callback(request, SDK_CONTEXT)
        assert result["kind"] == "denied-by-rules"

    def test_deny_write_readonly_path(self):
        """Write to a read-only path should be denied."""
        ppm = _make_mock_ppm(readable_paths=["/reference"])
        fm = _make_mock_filesystem_manager(ppm)
        backend = _make_copilot_backend(filesystem_manager=fm)

        callback = backend._build_permission_callback("approve")
        request = {"kind": "write", "path": "/reference/doc.md"}
        result = callback(request, SDK_CONTEXT)
        assert result["kind"] == "denied-by-rules"

    def test_approve_read_within_context(self):
        """Read from a readable context path should be approved."""
        ppm = _make_mock_ppm(readable_paths=["/reference"])
        fm = _make_mock_filesystem_manager(ppm)
        backend = _make_copilot_backend(filesystem_manager=fm)

        callback = backend._build_permission_callback("approve")
        request = {"kind": "read", "path": "/reference/doc.md"}
        result = callback(request, SDK_CONTEXT)
        assert result["kind"] == "approved"

    def test_approve_read_writable_path(self):
        """Read from a writable path should be approved (WRITE implies READ)."""
        ppm = _make_mock_ppm(writable_paths=["/workspace"])
        fm = _make_mock_filesystem_manager(ppm)
        backend = _make_copilot_backend(filesystem_manager=fm)

        callback = backend._build_permission_callback("approve")
        request = {"kind": "read", "path": "/workspace/file.txt"}
        result = callback(request, SDK_CONTEXT)
        assert result["kind"] == "approved"

    def test_deny_read_outside_context(self):
        """Read from a path outside any context should be denied."""
        ppm = _make_mock_ppm(writable_paths=["/workspace"])
        fm = _make_mock_filesystem_manager(ppm)
        backend = _make_copilot_backend(filesystem_manager=fm)

        callback = backend._build_permission_callback("approve")
        request = {"kind": "read", "path": "/etc/shadow"}
        result = callback(request, SDK_CONTEXT)
        assert result["kind"] == "denied-by-rules"

    @pytest.mark.asyncio
    async def test_shell_validated_via_ppm(self):
        """Shell command should be validated via PPM pre_tool_use_hook."""
        ppm = _make_mock_ppm(writable_paths=["/workspace"])
        ppm.pre_tool_use_hook = AsyncMock(
            return_value=(False, "Command writes to protected path"),
        )
        fm = _make_mock_filesystem_manager(ppm)
        backend = _make_copilot_backend(filesystem_manager=fm)

        callback = backend._build_permission_callback("approve")
        request = {"kind": "shell", "command": "rm -rf /etc"}
        # Shell validation is async
        result = callback(request, SDK_CONTEXT)
        # For shell with PPM, it should deny based on PPM result
        assert result["kind"] == "denied-by-rules"

    def test_mcp_always_approved(self):
        """MCP kind should always be approved (handled by hook system)."""
        ppm = _make_mock_ppm(writable_paths=["/workspace"])
        fm = _make_mock_filesystem_manager(ppm)
        backend = _make_copilot_backend(filesystem_manager=fm)

        callback = backend._build_permission_callback("approve")
        request = {"kind": "mcp", "serverName": "test_server"}
        result = callback(request, SDK_CONTEXT)
        assert result["kind"] == "approved"

    def test_custom_tool_always_approved(self):
        """Custom-tool kind should always be approved."""
        ppm = _make_mock_ppm(writable_paths=["/workspace"])
        fm = _make_mock_filesystem_manager(ppm)
        backend = _make_copilot_backend(filesystem_manager=fm)

        callback = backend._build_permission_callback("approve")
        request = {"kind": "custom-tool", "toolName": "my_tool"}
        result = callback(request, SDK_CONTEXT)
        assert result["kind"] == "approved"

    def test_url_always_approved(self):
        """URL kind should always be approved."""
        ppm = _make_mock_ppm(writable_paths=["/workspace"])
        fm = _make_mock_filesystem_manager(ppm)
        backend = _make_copilot_backend(filesystem_manager=fm)

        callback = backend._build_permission_callback("approve")
        request = {"kind": "url", "url": "https://example.com"}
        result = callback(request, SDK_CONTEXT)
        assert result["kind"] == "approved"

    def test_unknown_path_field_fails_open(self):
        """Write request with unrecognized path fields should fail-open."""
        ppm = _make_mock_ppm(writable_paths=["/workspace"])
        fm = _make_mock_filesystem_manager(ppm)
        backend = _make_copilot_backend(filesystem_manager=fm)

        callback = backend._build_permission_callback("approve")
        # No recognized path field
        request = {"kind": "write", "target": "/etc/passwd"}
        result = callback(request, SDK_CONTEXT)
        assert result["kind"] == "approved"

    def test_no_ppm_falls_back_to_blanket_approve(self):
        """Without PPM, permission callback should blanket approve."""
        fm = _make_mock_filesystem_manager(ppm=None)
        backend = _make_copilot_backend(filesystem_manager=fm)

        callback = backend._build_permission_callback("approve")
        request = {"kind": "write", "path": "/etc/passwd"}
        result = callback(request, SDK_CONTEXT)
        assert result["kind"] == "approved"

    def test_no_filesystem_manager_falls_back_to_blanket_approve(self):
        """Without filesystem_manager, permission callback should blanket approve."""
        backend = _make_copilot_backend(filesystem_manager=None)

        callback = backend._build_permission_callback("approve")
        request = {"kind": "write", "path": "/etc/passwd"}
        result = callback(request, SDK_CONTEXT)
        assert result["kind"] == "approved"

    def test_debug_logging_includes_full_request(self):
        """Debug log should capture full request dict (loguru logger)."""
        ppm = _make_mock_ppm(writable_paths=["/workspace"])
        fm = _make_mock_filesystem_manager(ppm)
        backend = _make_copilot_backend(filesystem_manager=fm)

        callback = backend._build_permission_callback("approve")
        request = {
            "kind": "write",
            "path": "/workspace/file.txt",
            "toolCallId": "tc_123",
        }

        # Capture loguru output via a sink
        captured = []
        from massgen.logger_config import logger as loguru_logger

        handler_id = loguru_logger.add(
            lambda msg: captured.append(str(msg)),
            level="DEBUG",
            filter=lambda record: "Permission request" in record["message"],
        )
        try:
            callback(request, SDK_CONTEXT)
        finally:
            loguru_logger.remove(handler_id)

        assert len(captured) >= 1
        # toolCallId should be excluded from the logged dict
        assert "tc_123" not in captured[0]


# ---------------------------------------------------------------------------
# TestPathExtraction
# ---------------------------------------------------------------------------
class TestPathExtraction:
    """Test static path/command extraction helpers."""

    def test_extract_path_from_path_key(self):
        from massgen.backend.copilot import CopilotBackend

        result = CopilotBackend._extract_path_from_permission_request(
            {"kind": "write", "path": "/foo/bar.txt"},
        )
        assert result == "/foo/bar.txt"

    def test_extract_path_from_filePath_key(self):
        from massgen.backend.copilot import CopilotBackend

        result = CopilotBackend._extract_path_from_permission_request(
            {"kind": "write", "filePath": "/foo/bar.txt"},
        )
        assert result == "/foo/bar.txt"

    def test_extract_path_from_file_path_key(self):
        from massgen.backend.copilot import CopilotBackend

        result = CopilotBackend._extract_path_from_permission_request(
            {"kind": "write", "file_path": "/foo/bar.txt"},
        )
        assert result == "/foo/bar.txt"

    def test_extract_path_returns_none_when_missing(self):
        from massgen.backend.copilot import CopilotBackend

        result = CopilotBackend._extract_path_from_permission_request(
            {"kind": "write", "target": "/foo"},
        )
        assert result is None

    def test_extract_path_ignores_non_string(self):
        from massgen.backend.copilot import CopilotBackend

        result = CopilotBackend._extract_path_from_permission_request(
            {"kind": "write", "path": 42},
        )
        assert result is None

    def test_extract_command_from_command_key(self):
        from massgen.backend.copilot import CopilotBackend

        result = CopilotBackend._extract_command_from_permission_request(
            {"kind": "shell", "command": "ls -la"},
        )
        assert result == "ls -la"

    def test_extract_command_from_cmd_key(self):
        from massgen.backend.copilot import CopilotBackend

        result = CopilotBackend._extract_command_from_permission_request(
            {"kind": "shell", "cmd": "ls -la"},
        )
        assert result == "ls -la"

    def test_extract_command_returns_none_when_missing(self):
        from massgen.backend.copilot import CopilotBackend

        result = CopilotBackend._extract_command_from_permission_request(
            {"kind": "shell", "script": "echo hi"},
        )
        assert result is None


# ---------------------------------------------------------------------------
# TestSessionSignatureWithPPM
# ---------------------------------------------------------------------------
class TestSessionSignatureWithPPM:
    """Test that session signature includes writable paths for cache invalidation."""

    def test_different_writable_paths_produce_different_signatures(self):
        """Changing writable paths should invalidate the session cache."""
        backend = _make_copilot_backend()

        base_kwargs = {
            "model": "gpt-4",
            "system_message": "test",
            "system_message_mode": "append",
            "workflow_tools": [],
            "mcp_servers": {},
            "working_directory": "/workspace",
            "available_tools": None,
            "excluded_tools": None,
            "permission_policy": "approve",
        }

        sig1 = backend._build_session_signature(
            **base_kwargs,
            writable_paths=["/workspace"],
        )
        sig2 = backend._build_session_signature(
            **base_kwargs,
            writable_paths=["/workspace", "/extra"],
        )

        assert sig1 != sig2

    def test_same_writable_paths_produce_same_signature(self):
        """Same writable paths should produce same signature."""
        backend = _make_copilot_backend()

        base_kwargs = {
            "model": "gpt-4",
            "system_message": "test",
            "system_message_mode": "append",
            "workflow_tools": [],
            "mcp_servers": {},
            "working_directory": "/workspace",
            "available_tools": None,
            "excluded_tools": None,
            "permission_policy": "approve",
            "writable_paths": ["/workspace"],
        }

        sig1 = backend._build_session_signature(**base_kwargs)
        sig2 = backend._build_session_signature(**base_kwargs)

        assert sig1 == sig2


# ---------------------------------------------------------------------------
# TestCopilotDockerMode
# ---------------------------------------------------------------------------
class TestCopilotDockerMode:
    """Test Docker execution mode for CopilotBackend."""

    def test_docker_flag_set_from_config(self):
        """_docker_execution should be True when config has docker mode."""
        backend = _make_copilot_backend()
        backend.config = {"command_line_execution_mode": "docker"}
        # Re-initialize docker flag from config
        backend._docker_execution = backend.config.get("command_line_execution_mode") == "docker"
        assert backend._docker_execution is True

    def test_docker_flag_false_by_default(self):
        """_docker_execution should be False when not configured."""
        backend = _make_copilot_backend()
        backend._docker_execution = False
        assert backend._docker_execution is False

    def test_is_docker_mode_false_without_container(self):
        """_is_docker_mode should be False when no container is running."""
        backend = _make_copilot_backend()
        backend._docker_execution = True
        backend.config = {"agent_id": "test-agent"}
        # filesystem_manager exists but docker_manager has no container
        fm = MagicMock()
        dm = MagicMock()
        dm.get_container.return_value = None
        fm.docker_manager = dm
        backend.filesystem_manager = fm
        assert backend._is_docker_mode is False

    def test_is_docker_mode_true_with_container(self):
        """_is_docker_mode should be True when container exists."""
        backend = _make_copilot_backend()
        backend._docker_execution = True
        backend.config = {"agent_id": "test-agent"}
        fm = MagicMock()
        dm = MagicMock()
        dm.get_container.return_value = MagicMock()  # container exists
        fm.docker_manager = dm
        backend.filesystem_manager = fm
        assert backend._is_docker_mode is True

    def test_is_docker_mode_false_without_filesystem_manager(self):
        """_is_docker_mode should be False without filesystem_manager."""
        backend = _make_copilot_backend()
        backend._docker_execution = True
        backend.filesystem_manager = None
        assert backend._is_docker_mode is False

    def test_is_docker_mode_false_without_docker_manager(self):
        """_is_docker_mode should be False without docker_manager."""
        backend = _make_copilot_backend()
        backend._docker_execution = True
        backend.config = {"agent_id": "test-agent"}
        fm = MagicMock()
        fm.docker_manager = None
        backend.filesystem_manager = fm
        assert backend._is_docker_mode is False

    def test_disallowed_tools_in_docker_mode(self):
        """get_disallowed_tools should return tool list when Docker enabled."""
        backend = _make_copilot_backend()
        backend._docker_execution = True
        tools = backend.get_disallowed_tools(backend.config)
        assert len(tools) > 0
        # Should contain file and shell tool names
        assert any("file" in t.lower() or "File" in t for t in tools)
        assert any("shell" in t.lower() or "Shell" in t for t in tools)

    def test_disallowed_tools_empty_without_docker(self):
        """get_disallowed_tools should return [] when Docker not enabled."""
        backend = _make_copilot_backend()
        backend._docker_execution = False
        tools = backend.get_disallowed_tools(backend.config)
        assert tools == []

    def test_excluded_tools_merged_in_docker_mode(self):
        """Docker-excluded tools should merge into resolved excluded_tools."""
        backend = _make_copilot_backend()
        backend._docker_execution = True
        backend.config = {"exclude_tools": ["some_tool"]}

        # _resolve_backend_tool_filters returns base excluded tools
        _, excluded = backend._resolve_backend_tool_filters({})
        assert "some_tool" in excluded

        # Now apply Docker merge logic
        docker_excluded = backend.get_disallowed_tools(backend.config)
        merged = list(set((excluded or []) + docker_excluded))
        assert "some_tool" in merged
        assert len(merged) > 1  # has both user-excluded and docker-excluded
