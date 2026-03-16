"""Integration tests for Gemini CLI hook adapter with orchestrator hook manager.

These are deterministic, non-API tests that verify the hook adapter correctly
builds settings.json config and integrates with MassGen's GeneralHookManager.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from massgen.mcp_tools.hooks import (
    GeneralHookManager,
    HookResult,
    HookType,
    PatternHook,
)
from massgen.mcp_tools.native_hook_adapters import GeminiCLINativeHookAdapter


class _AllowHook(PatternHook):
    """Minimal hook that allows everything. Used across test classes."""

    async def execute(self, tool_name, arguments, context):
        return HookResult(allowed=True)


class TestAdapterSupportsHookTypes:
    """Verify GeminiCLINativeHookAdapter supports expected hook types."""

    def test_supports_pre_tool_use(self) -> None:
        adapter = GeminiCLINativeHookAdapter()
        assert adapter.supports_hook_type(HookType.PRE_TOOL_USE) is True

    def test_supports_post_tool_use(self) -> None:
        adapter = GeminiCLINativeHookAdapter()
        assert adapter.supports_hook_type(HookType.POST_TOOL_USE) is True


class TestBuildNativeHooksConfig:
    """Test building settings.json hooks config from GeneralHookManager."""

    def test_empty_manager_returns_empty(self, tmp_path: Path) -> None:
        adapter = GeminiCLINativeHookAdapter(hook_dir=tmp_path)
        manager = GeneralHookManager()
        config = adapter.build_native_hooks_config(manager)
        assert config == {}

    def test_post_tool_hook_generates_after_tool_entry(self, tmp_path: Path) -> None:
        adapter = GeminiCLINativeHookAdapter(hook_dir=tmp_path)
        manager = GeneralHookManager()

        manager.register_global_hook(
            HookType.POST_TOOL_USE,
            _AllowHook(name="test_injection", matcher=".*"),
        )

        config = adapter.build_native_hooks_config(manager)
        assert "hooks" in config
        assert "AfterTool" in config["hooks"]
        entries = config["hooks"]["AfterTool"]
        assert len(entries) >= 1
        assert entries[0]["matcher"] == ".*"
        assert len(entries[0]["hooks"]) == 1
        assert entries[0]["hooks"][0]["type"] == "command"

    def test_pre_tool_hook_generates_before_tool_entry(self, tmp_path: Path) -> None:
        adapter = GeminiCLINativeHookAdapter(hook_dir=tmp_path)
        manager = GeneralHookManager()

        manager.register_global_hook(
            HookType.PRE_TOOL_USE,
            _AllowHook(name="test_permission", matcher="write_file"),
        )

        config = adapter.build_native_hooks_config(manager)
        assert "hooks" in config
        assert "BeforeTool" in config["hooks"]
        entries = config["hooks"]["BeforeTool"]
        assert len(entries) >= 1
        assert entries[0]["matcher"] == "write_file"

    def test_hook_command_points_to_hook_script(self, tmp_path: Path) -> None:
        """Hook command should invoke the gemini_cli_hook_script.py with correct args."""
        adapter = GeminiCLINativeHookAdapter(hook_dir=tmp_path)
        manager = GeneralHookManager()

        manager.register_global_hook(
            HookType.POST_TOOL_USE,
            _AllowHook(name="test", matcher=".*"),
        )

        config = adapter.build_native_hooks_config(manager)
        command = config["hooks"]["AfterTool"][0]["hooks"][0]["command"]
        assert "gemini_cli_hook_script" in command
        assert "--hook-dir" in command
        assert str(tmp_path) in command
        assert "--event AfterTool" in command

    def test_no_config_without_hook_dir(self) -> None:
        """Adapter without hook_dir should return empty config."""
        adapter = GeminiCLINativeHookAdapter(hook_dir=None)
        manager = GeneralHookManager()

        manager.register_global_hook(
            HookType.POST_TOOL_USE,
            _AllowHook(name="test", matcher=".*"),
        )

        config = adapter.build_native_hooks_config(manager)
        assert config == {}

    def test_multiple_hooks_same_type_merged(self, tmp_path: Path) -> None:
        """Multiple hooks of the same type should produce separate entries."""
        adapter = GeminiCLINativeHookAdapter(hook_dir=tmp_path)
        manager = GeneralHookManager()

        manager.register_global_hook(
            HookType.POST_TOOL_USE,
            _AllowHook(name="hook1", matcher=".*"),
        )
        manager.register_global_hook(
            HookType.POST_TOOL_USE,
            _AllowHook(name="hook2", matcher="read_file"),
        )

        config = adapter.build_native_hooks_config(manager)
        # Two different matchers should produce two entries
        entries = config["hooks"]["AfterTool"]
        matchers = {e["matcher"] for e in entries}
        assert ".*" in matchers
        assert "read_file" in matchers

    def test_both_hook_types_in_same_config(self, tmp_path: Path) -> None:
        adapter = GeminiCLINativeHookAdapter(hook_dir=tmp_path)
        manager = GeneralHookManager()

        manager.register_global_hook(
            HookType.PRE_TOOL_USE,
            _AllowHook(name="pre", matcher="write_file"),
        )
        manager.register_global_hook(
            HookType.POST_TOOL_USE,
            _AllowHook(name="post", matcher=".*"),
        )

        config = adapter.build_native_hooks_config(manager)
        assert "BeforeTool" in config["hooks"]
        assert "AfterTool" in config["hooks"]


class TestMergeNativeConfigs:
    """Test merging multiple hook configs."""

    def test_merge_two_configs(self) -> None:
        adapter = GeminiCLINativeHookAdapter()
        config1 = {
            "hooks": {
                "AfterTool": [{"matcher": ".*", "hooks": [{"type": "command", "command": "hook1"}]}],
            },
        }
        config2 = {
            "hooks": {
                "BeforeTool": [{"matcher": "write_file", "hooks": [{"type": "command", "command": "hook2"}]}],
            },
        }

        merged = adapter.merge_native_configs(config1, config2)
        assert "hooks" in merged
        assert "AfterTool" in merged["hooks"]
        assert "BeforeTool" in merged["hooks"]
        assert len(merged["hooks"]["AfterTool"]) == 1
        assert len(merged["hooks"]["BeforeTool"]) == 1

    def test_merge_same_event_accumulates(self) -> None:
        adapter = GeminiCLINativeHookAdapter()
        config1 = {
            "hooks": {
                "AfterTool": [{"matcher": ".*", "hooks": [{"type": "command", "command": "hook1"}]}],
            },
        }
        config2 = {
            "hooks": {
                "AfterTool": [{"matcher": "read_file", "hooks": [{"type": "command", "command": "hook2"}]}],
            },
        }

        merged = adapter.merge_native_configs(config1, config2)
        assert len(merged["hooks"]["AfterTool"]) == 2

    def test_merge_empty_configs(self) -> None:
        adapter = GeminiCLINativeHookAdapter()
        merged = adapter.merge_native_configs({}, {}, None)
        assert merged == {}

    def test_merge_one_empty_one_real(self) -> None:
        adapter = GeminiCLINativeHookAdapter()
        config = {
            "hooks": {
                "AfterTool": [{"matcher": ".*", "hooks": [{"type": "command", "command": "hook1"}]}],
            },
        }
        merged = adapter.merge_native_configs({}, config)
        assert "AfterTool" in merged["hooks"]
        assert len(merged["hooks"]["AfterTool"]) == 1


class TestAdapterFileIPC:
    """Test the adapter's file-based IPC methods directly."""

    def test_write_and_read_round_trip(self, tmp_path: Path) -> None:
        adapter = GeminiCLINativeHookAdapter(hook_dir=tmp_path)
        adapter.write_hook_payload("injected content", event="AfterTool")

        content = adapter.read_unconsumed_hook_content()
        assert content == "injected content"

    def test_clear_removes_files(self, tmp_path: Path) -> None:
        adapter = GeminiCLINativeHookAdapter(hook_dir=tmp_path)
        adapter.write_hook_payload("content")

        assert (tmp_path / "hook_payload.json").exists()
        adapter.clear_hook_files()
        assert not (tmp_path / "hook_payload.json").exists()

    def test_sequence_increments(self, tmp_path: Path) -> None:
        adapter = GeminiCLINativeHookAdapter(hook_dir=tmp_path)

        adapter.write_hook_payload("first")
        p1 = json.loads((tmp_path / "hook_payload.json").read_text())

        adapter.write_hook_payload("second")
        p2 = json.loads((tmp_path / "hook_payload.json").read_text())

        assert p2["sequence"] > p1["sequence"]

    def test_write_no_hook_dir_is_noop(self) -> None:
        """Writing without hook_dir should silently do nothing."""
        adapter = GeminiCLINativeHookAdapter(hook_dir=None)
        # Should not raise
        adapter.write_hook_payload("content")

    def test_read_no_hook_dir_returns_none(self) -> None:
        adapter = GeminiCLINativeHookAdapter(hook_dir=None)
        assert adapter.read_unconsumed_hook_content() is None

    def test_clear_no_hook_dir_is_noop(self) -> None:
        adapter = GeminiCLINativeHookAdapter(hook_dir=None)
        # Should not raise
        adapter.clear_hook_files()


class TestGeminiBackendHookIntegration:
    """Integration: GeminiCLIBackend + GeneralHookManager + NativeHookAdapter."""

    def test_backend_native_hooks_config_written_to_settings(self, tmp_path: Path) -> None:
        """End-to-end: register hooks -> build config -> write settings.json."""
        from massgen.backend.gemini_cli import GeminiCLIBackend

        with patch.object(GeminiCLIBackend, "_find_gemini_cli", return_value="/usr/bin/gemini"):
            backend = GeminiCLIBackend(cwd=str(tmp_path))

        adapter = backend.get_native_hook_adapter()
        assert adapter is not None

        adapter.hook_dir = tmp_path / ".gemini"
        manager = GeneralHookManager()

        manager.register_global_hook(
            HookType.POST_TOOL_USE,
            _AllowHook(name="mid_stream_injection", matcher=".*"),
        )
        hooks_config = adapter.build_native_hooks_config(manager)

        backend.set_native_hooks_config(hooks_config)
        backend.system_prompt = "Test agent"
        backend._write_workspace_config()

        settings_path = tmp_path / ".gemini" / "settings.json"
        assert settings_path.exists()
        settings = json.loads(settings_path.read_text())
        assert "hooks" in settings
        assert "AfterTool" in settings["hooks"]

    def test_backend_tools_exclude_in_settings(self, tmp_path: Path) -> None:
        """tools.exclude should always be written in settings.json."""
        from massgen.backend.gemini_cli import GeminiCLIBackend

        with patch.object(GeminiCLIBackend, "_find_gemini_cli", return_value="/usr/bin/gemini"):
            backend = GeminiCLIBackend(cwd=str(tmp_path))

        backend.system_prompt = "Test"
        backend._write_workspace_config()

        settings_path = tmp_path / ".gemini" / "settings.json"
        settings = json.loads(settings_path.read_text())
        assert "tools" in settings
        excluded = settings["tools"]["exclude"]
        assert "ask_user" in excluded
        assert "enter_plan_mode" in excluded
        assert "save_memory" in excluded

    def test_hook_payload_survives_workspace_config_rewrite(self, tmp_path: Path) -> None:
        """Writing workspace config should not delete hook payload files."""
        from massgen.backend.gemini_cli import GeminiCLIBackend

        with patch.object(GeminiCLIBackend, "_find_gemini_cli", return_value="/usr/bin/gemini"):
            backend = GeminiCLIBackend(cwd=str(tmp_path))

        adapter = backend.get_native_hook_adapter()
        adapter.hook_dir = tmp_path / ".gemini"

        backend.write_post_tool_use_hook("injection content")
        assert (tmp_path / ".gemini" / "hook_payload.json").exists()

        backend.system_prompt = "Updated prompt"
        backend._write_workspace_config()

        assert (tmp_path / ".gemini" / "hook_payload.json").exists()
        content = backend.read_unconsumed_hook_content()
        assert content == "injection content"
