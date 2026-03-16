"""Integration tests for Copilot hook adapter with orchestrator hook manager.

These are deterministic, non-API tests that verify the hook adapter correctly
builds SessionHooks config and integrates with MassGen's GeneralHookManager.

Copilot's native hooks are in-process async callables (unlike Gemini CLI's
subprocess commands). The adapter produces {'on_pre_tool_use': handler,
'on_post_tool_use': handler} which is passed directly to the SDK session.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from massgen.mcp_tools.hooks import (
    GeneralHookManager,
    HookResult,
    HookType,
    PatternHook,
)
from massgen.mcp_tools.native_hook_adapters import CopilotNativeHookAdapter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _AllowHook(PatternHook):
    """Minimal hook that always allows."""

    async def execute(self, tool_name, arguments, context=None, **kwargs):
        return HookResult(allowed=True)


class _DenyHook(PatternHook):
    """Hook that always denies with a reason."""

    def __init__(self, name: str, matcher: str = ".*", reason: str = "denied"):
        super().__init__(name=name, matcher=matcher)
        self._reason = reason

    async def execute(self, tool_name, arguments, context=None, **kwargs):
        return HookResult(allowed=False, decision="deny", reason=self._reason)


class _InjectHook(PatternHook):
    """Hook that injects additional context (PostToolUse)."""

    def __init__(self, name: str, matcher: str = ".*", content: str = "injected"):
        super().__init__(name=name, matcher=matcher)
        self._content = content

    async def execute(self, tool_name, arguments, context=None, **kwargs):
        return HookResult(allowed=True, inject={"content": self._content})


def _pre_tool_input(tool_name: str, tool_args: dict | None = None) -> dict:
    return {
        "timestamp": 1_700_000_000,
        "cwd": "/workspace",
        "toolName": tool_name,
        "toolArgs": tool_args or {},
    }


def _post_tool_input(
    tool_name: str,
    tool_args: dict | None = None,
    tool_result: str = "ok",
) -> dict:
    return {
        "timestamp": 1_700_000_000,
        "cwd": "/workspace",
        "toolName": tool_name,
        "toolArgs": tool_args or {},
        "toolResult": tool_result,
    }


SDK_CONTEXT = {"session_id": "test_sess"}


def _make_copilot_backend(tmp_path):
    """Create a CopilotBackend with mocked SDK."""
    mock_copilot_module = MagicMock()
    mock_copilot_module.CopilotClient = MagicMock
    mock_copilot_module.Tool = MagicMock

    with patch.dict("sys.modules", {"copilot": mock_copilot_module}):
        from massgen.backend.copilot import CopilotBackend

        backend = CopilotBackend.__new__(CopilotBackend)
        backend.config = {}
        backend.client = MagicMock()
        backend.sessions = {}
        backend._session_signatures = {}
        backend._docker_execution = False
        backend.filesystem_manager = None
        backend._cwd = str(tmp_path)
        backend._custom_tools_config = []
        backend._custom_tool_specs_path = None
        backend.mcp_servers = []
        backend._massgen_hooks_config = {}

        # Initialize native hook adapter
        backend._init_native_hook_adapter(
            "massgen.mcp_tools.native_hook_adapters.CopilotNativeHookAdapter",
        )

    return backend


# ---------------------------------------------------------------------------
# TestAdapterSupportsHookTypes
# ---------------------------------------------------------------------------
class TestAdapterSupportsHookTypes:
    """Verify CopilotNativeHookAdapter supports expected hook types."""

    def test_supports_pre_tool_use(self) -> None:
        adapter = CopilotNativeHookAdapter()
        assert adapter.supports_hook_type(HookType.PRE_TOOL_USE) is True

    def test_supports_post_tool_use(self) -> None:
        adapter = CopilotNativeHookAdapter()
        assert adapter.supports_hook_type(HookType.POST_TOOL_USE) is True

    def test_does_not_support_pre_call(self) -> None:
        adapter = CopilotNativeHookAdapter()
        assert adapter.supports_hook_type(HookType.PRE_CALL) is False

    def test_does_not_support_post_call(self) -> None:
        adapter = CopilotNativeHookAdapter()
        assert adapter.supports_hook_type(HookType.POST_CALL) is False


# ---------------------------------------------------------------------------
# TestBuildNativeHooksConfigWithRealHooks
# ---------------------------------------------------------------------------
class TestBuildNativeHooksConfigWithRealHooks:
    """Test build_native_hooks_config returns correct callable config."""

    def test_empty_manager_returns_empty(self) -> None:
        adapter = CopilotNativeHookAdapter()
        manager = GeneralHookManager()
        config = adapter.build_native_hooks_config(manager)
        assert config == {}

    def test_post_tool_hook_generates_on_post_tool_use(self) -> None:
        adapter = CopilotNativeHookAdapter()
        manager = GeneralHookManager()
        manager.register_global_hook(
            HookType.POST_TOOL_USE,
            _InjectHook(name="mid_stream_inject", matcher="*"),
        )
        config = adapter.build_native_hooks_config(manager)
        assert "on_post_tool_use" in config
        assert callable(config["on_post_tool_use"])

    def test_pre_tool_hook_generates_on_pre_tool_use(self) -> None:
        adapter = CopilotNativeHookAdapter()
        manager = GeneralHookManager()
        manager.register_global_hook(
            HookType.PRE_TOOL_USE,
            _DenyHook(name="permission_gate", matcher="write_file"),
        )
        config = adapter.build_native_hooks_config(manager)
        assert "on_pre_tool_use" in config
        assert callable(config["on_pre_tool_use"])

    def test_both_hook_types_in_same_config(self) -> None:
        adapter = CopilotNativeHookAdapter()
        manager = GeneralHookManager()
        manager.register_global_hook(
            HookType.PRE_TOOL_USE,
            _AllowHook(name="pre", matcher="*"),
        )
        manager.register_global_hook(
            HookType.POST_TOOL_USE,
            _AllowHook(name="post", matcher="*"),
        )
        config = adapter.build_native_hooks_config(manager)
        assert "on_pre_tool_use" in config
        assert "on_post_tool_use" in config

    @pytest.mark.asyncio
    async def test_post_tool_hook_injects_content(self) -> None:
        adapter = CopilotNativeHookAdapter()
        manager = GeneralHookManager()
        manager.register_global_hook(
            HookType.POST_TOOL_USE,
            _InjectHook(name="inject", matcher="*", content="Agent B answered: 42"),
        )
        config = adapter.build_native_hooks_config(manager)
        result = await config["on_post_tool_use"](
            _post_tool_input("read_file"),
            SDK_CONTEXT,
        )
        assert result is not None
        assert result["additionalContext"] == "Agent B answered: 42"

    @pytest.mark.asyncio
    async def test_pre_tool_hook_denies_blocked_tool(self) -> None:
        adapter = CopilotNativeHookAdapter()
        manager = GeneralHookManager()
        manager.register_global_hook(
            HookType.PRE_TOOL_USE,
            _DenyHook(
                name="path_gate",
                matcher="*",
                reason="Access outside workspace denied",
            ),
        )
        config = adapter.build_native_hooks_config(manager)
        result = await config["on_pre_tool_use"](
            _pre_tool_input("write_file", {"path": "/etc/passwd"}),
            SDK_CONTEXT,
        )
        assert result is not None
        assert result["permissionDecision"] == "deny"
        assert "Access outside workspace" in result["permissionDecisionReason"]

    @pytest.mark.asyncio
    async def test_pre_tool_hook_allows_matching_tool(self) -> None:
        adapter = CopilotNativeHookAdapter()
        manager = GeneralHookManager()
        manager.register_global_hook(
            HookType.PRE_TOOL_USE,
            _AllowHook(name="allow_all", matcher="*"),
        )
        config = adapter.build_native_hooks_config(manager)
        result = await config["on_pre_tool_use"](
            _pre_tool_input("write_file", {"path": "/workspace/out.txt"}),
            SDK_CONTEXT,
        )
        # Allow → returns None (no modification)
        assert result is None

    @pytest.mark.asyncio
    async def test_hook_skips_non_matching_tool(self) -> None:
        """Hooks with pattern 'write_file' should not fire on 'read_file'."""
        adapter = CopilotNativeHookAdapter()
        manager = GeneralHookManager()
        manager.register_global_hook(
            HookType.PRE_TOOL_USE,
            _DenyHook(name="write_only", matcher="write_file"),
        )
        config = adapter.build_native_hooks_config(manager)
        result = await config["on_pre_tool_use"](
            _pre_tool_input("read_file"),
            SDK_CONTEXT,
        )
        # Pattern didn't match → None (allow)
        assert result is None

    @pytest.mark.asyncio
    async def test_multiple_post_hooks_context_concatenated(self) -> None:
        """Multiple PostToolUse hooks should concatenate their additionalContext."""
        adapter = CopilotNativeHookAdapter()
        manager = GeneralHookManager()
        manager.register_global_hook(
            HookType.POST_TOOL_USE,
            _InjectHook(name="inject1", matcher="*", content="part one"),
        )
        manager.register_global_hook(
            HookType.POST_TOOL_USE,
            _InjectHook(name="inject2", matcher="*", content="part two"),
        )
        config = adapter.build_native_hooks_config(manager)
        result = await config["on_post_tool_use"](
            _post_tool_input("read_file"),
            SDK_CONTEXT,
        )
        assert result is not None
        assert "part one" in result["additionalContext"]
        assert "part two" in result["additionalContext"]

    @pytest.mark.asyncio
    async def test_composite_deny_short_circuits(self) -> None:
        """Deny from first hook should stop further hook execution."""
        executed = []

        class TrackingHook(PatternHook):
            def __init__(self, name: str):
                super().__init__(name=name, matcher="*")

            async def execute(self, tool_name, arguments, context=None, **kwargs):
                executed.append(self.name)
                return HookResult(allowed=True)

        adapter = CopilotNativeHookAdapter()
        manager = GeneralHookManager()
        manager.register_global_hook(
            HookType.PRE_TOOL_USE,
            _DenyHook(name="first_deny", matcher="*"),
        )
        manager.register_global_hook(
            HookType.PRE_TOOL_USE,
            TrackingHook(name="should_not_run"),
        )
        config = adapter.build_native_hooks_config(manager)
        result = await config["on_pre_tool_use"](
            _pre_tool_input("some_tool"),
            SDK_CONTEXT,
        )
        assert result["permissionDecision"] == "deny"
        assert "should_not_run" not in executed


# ---------------------------------------------------------------------------
# TestMergeNativeConfigs
# ---------------------------------------------------------------------------
class TestMergeNativeConfigs:
    """Test merging multiple Copilot hook configs."""

    def test_merge_two_configs_with_different_types(self) -> None:
        adapter = CopilotNativeHookAdapter()
        config1 = {"on_pre_tool_use": lambda *a: None}
        config2 = {"on_post_tool_use": lambda *a: None}
        merged = adapter.merge_native_configs(config1, config2)
        assert "on_pre_tool_use" in merged
        assert "on_post_tool_use" in merged

    def test_merge_same_type_creates_composite(self) -> None:
        adapter = CopilotNativeHookAdapter()

        async def handler1(*a):
            return None

        async def handler2(*a):
            return None

        config1 = {"on_pre_tool_use": handler1}
        config2 = {"on_pre_tool_use": handler2}
        merged = adapter.merge_native_configs(config1, config2)
        # Should produce a composite, not the original
        assert callable(merged["on_pre_tool_use"])

    def test_merge_empty_configs(self) -> None:
        adapter = CopilotNativeHookAdapter()
        merged = adapter.merge_native_configs({}, {}, None)
        assert merged == {}

    def test_merge_single_handler_passthrough(self) -> None:
        adapter = CopilotNativeHookAdapter()
        handler = lambda *a: None  # noqa: E731
        config = {"on_post_tool_use": handler}
        merged = adapter.merge_native_configs(config)
        assert merged["on_post_tool_use"] is handler

    @pytest.mark.asyncio
    async def test_merged_composite_runs_both_handlers(self) -> None:
        """Merged composite should invoke both original handlers."""
        invoked = []

        async def handler_a(input_data, ctx):
            invoked.append("a")
            return None

        async def handler_b(input_data, ctx):
            invoked.append("b")
            return None

        adapter = CopilotNativeHookAdapter()
        merged = adapter.merge_native_configs(
            {"on_post_tool_use": handler_a},
            {"on_post_tool_use": handler_b},
        )
        await merged["on_post_tool_use"](_post_tool_input("tool"), SDK_CONTEXT)
        assert "a" in invoked
        assert "b" in invoked


# ---------------------------------------------------------------------------
# TestCopilotBackendHookIntegration
# ---------------------------------------------------------------------------
class TestCopilotBackendHookIntegration:
    """Integration: CopilotBackend + GeneralHookManager + NativeHookAdapter."""

    def test_backend_creates_native_hook_adapter(self, tmp_path) -> None:
        """Backend should initialize a CopilotNativeHookAdapter."""
        backend = _make_copilot_backend(tmp_path)
        adapter = backend.get_native_hook_adapter()
        assert adapter is not None
        assert isinstance(adapter, CopilotNativeHookAdapter)

    def test_backend_supports_native_hooks(self, tmp_path) -> None:
        backend = _make_copilot_backend(tmp_path)
        assert backend.supports_native_hooks() is True

    def test_set_native_hooks_config_stored_on_backend(self, tmp_path) -> None:
        """set_native_hooks_config should store config for session creation."""
        backend = _make_copilot_backend(tmp_path)
        adapter = backend.get_native_hook_adapter()
        manager = GeneralHookManager()
        manager.register_global_hook(
            HookType.POST_TOOL_USE,
            _InjectHook(name="inject", matcher="*"),
        )
        config = adapter.build_native_hooks_config(manager)
        backend.set_native_hooks_config(config)
        assert hasattr(backend, "_massgen_hooks_config")
        stored = backend._massgen_hooks_config
        assert "on_post_tool_use" in stored
        assert callable(stored["on_post_tool_use"])

    @pytest.mark.asyncio
    async def test_stored_hooks_inject_on_post_tool(self, tmp_path) -> None:
        """End-to-end: register hooks → build config → stored hooks fire correctly."""
        backend = _make_copilot_backend(tmp_path)
        adapter = backend.get_native_hook_adapter()
        manager = GeneralHookManager()
        manager.register_global_hook(
            HookType.POST_TOOL_USE,
            _InjectHook(
                name="mid_stream",
                matcher="*",
                content="The answer is 42",
            ),
        )
        config = adapter.build_native_hooks_config(manager)
        backend.set_native_hooks_config(config)

        # Simulate what the SDK does: call the stored handler
        stored = backend._massgen_hooks_config
        result = await stored["on_post_tool_use"](
            _post_tool_input("run_shell_command"),
            SDK_CONTEXT,
        )
        assert result is not None
        assert result["additionalContext"] == "The answer is 42"

    @pytest.mark.asyncio
    async def test_stored_hooks_deny_on_pre_tool(self, tmp_path) -> None:
        """PRE_TOOL_USE hook stored via set_native_hooks_config denies correctly."""
        backend = _make_copilot_backend(tmp_path)
        adapter = backend.get_native_hook_adapter()
        manager = GeneralHookManager()
        manager.register_global_hook(
            HookType.PRE_TOOL_USE,
            _DenyHook(
                name="ppm_gate",
                matcher="*",
                reason="Read-only context path",
            ),
        )
        config = adapter.build_native_hooks_config(manager)
        backend.set_native_hooks_config(config)

        stored = backend._massgen_hooks_config
        result = await stored["on_pre_tool_use"](
            _pre_tool_input("editFile", {"filePath": "/context/notes.md"}),
            SDK_CONTEXT,
        )
        assert result["permissionDecision"] == "deny"
        assert "Read-only context path" in result["permissionDecisionReason"]

    def test_provider_name_and_capabilities(self, tmp_path) -> None:
        """Backend should report correct provider name and capabilities."""
        from massgen.backend.base import FilesystemSupport

        backend = _make_copilot_backend(tmp_path)
        assert backend.get_provider_name() == "copilot"
        assert backend.get_filesystem_support() == FilesystemSupport.MCP
        assert backend.is_stateful() is True
        assert backend.supports_native_hooks() is True


# ---------------------------------------------------------------------------
# TestContextFactoryIntegration
# ---------------------------------------------------------------------------
class TestContextFactoryIntegration:
    """Verify context_factory is correctly passed through to hooks."""

    @pytest.mark.asyncio
    async def test_context_factory_enriches_hook_context(self) -> None:
        captured: dict = {}

        class CapturingHook(PatternHook):
            def __init__(self):
                super().__init__(name="capture", matcher="*")

            async def execute(self, tool_name, arguments, context=None, **kwargs):
                captured.update(context or {})
                return HookResult(allowed=True)

        adapter = CopilotNativeHookAdapter()
        manager = GeneralHookManager()
        manager.register_global_hook(HookType.PRE_TOOL_USE, CapturingHook())

        def ctx_factory():
            return {"agent_id": "agent_a", "orchestrator_id": "orch_1"}

        config = adapter.build_native_hooks_config(
            manager,
            context_factory=ctx_factory,
        )
        await config["on_pre_tool_use"](_pre_tool_input("some_tool"), SDK_CONTEXT)
        assert captured["agent_id"] == "agent_a"
        assert captured["orchestrator_id"] == "orch_1"
        assert captured["session_id"] == "test_sess"
        assert captured["cwd"] == "/workspace"

    @pytest.mark.asyncio
    async def test_post_hook_receives_tool_result(self) -> None:
        captured: dict = {}

        class CapturingHook(PatternHook):
            def __init__(self):
                super().__init__(name="capture", matcher="*")

            async def execute(self, tool_name, arguments, context=None, **kwargs):
                captured.update(context or {})
                return HookResult(allowed=True)

        adapter = CopilotNativeHookAdapter()
        manager = GeneralHookManager()
        manager.register_global_hook(HookType.POST_TOOL_USE, CapturingHook())

        config = adapter.build_native_hooks_config(manager)
        await config["on_post_tool_use"](
            _post_tool_input("read_file", tool_result="file contents here"),
            SDK_CONTEXT,
        )
        assert captured["tool_output"] == "file contents here"
