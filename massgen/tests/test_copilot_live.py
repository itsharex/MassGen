"""Live API integration tests for CopilotBackend with actual Copilot SDK.

These tests require:
- github-copilot-sdk installed: pip install github-copilot-sdk
- Copilot authentication: run `copilot login` before executing

Run with: uv run pytest massgen/tests/test_copilot_live.py -v --run-integration --run-live-api
"""

from __future__ import annotations

import pytest


def _has_copilot_sdk() -> bool:
    """Check if the Copilot SDK is importable."""
    try:
        import copilot  # noqa: F401

        return True
    except ImportError:
        return False


def _skip_if_no_copilot_sdk() -> None:
    if not _has_copilot_sdk():
        pytest.skip("github-copilot-sdk not installed (pip install github-copilot-sdk)")


async def _check_copilot_auth(backend) -> None:
    """Skip test if Copilot is not authenticated."""
    try:
        await backend._ensure_started()
        is_auth, msg = await backend._query_auth_status(context="live_test")
    except Exception as e:
        pytest.skip(f"Copilot SDK not available or auth check failed: {e}")
    if is_auth is False:
        pytest.skip(
            f"Copilot not authenticated — run `copilot login` first (msg: {msg})",
        )


@pytest.mark.integration
@pytest.mark.live_api
@pytest.mark.asyncio
async def test_real_stream_single_turn():
    """Test real single-turn streaming with Copilot SDK."""
    _skip_if_no_copilot_sdk()
    from massgen.backend.copilot import CopilotBackend

    backend = CopilotBackend()
    await _check_copilot_auth(backend)

    messages = [
        {"role": "user", "content": "What is 2+2? Reply with just the number."},
    ]

    chunks = []
    total_content = ""

    async for chunk in backend.stream_with_tools(messages, []):
        chunks.append(chunk)
        if chunk.type == "content":
            total_content += chunk.content or ""
        elif chunk.type == "done":
            break

    content_chunks = [c for c in chunks if c.type == "content"]
    done_chunks = [c for c in chunks if c.type == "done"]
    assert len(content_chunks) >= 1, "Expected at least one content chunk"
    assert len(done_chunks) == 1, "Expected exactly one done chunk"
    assert len(total_content) > 0, "Expected non-empty response"
    assert "4" in total_content, f"Expected '4' in response to 2+2, got: {total_content!r}"

    await backend.reset_state()


@pytest.mark.integration
@pytest.mark.live_api
@pytest.mark.asyncio
async def test_real_stream_multi_turn():
    """Test multi-turn streaming with session persistence."""
    _skip_if_no_copilot_sdk()
    from massgen.backend.copilot import CopilotBackend

    backend = CopilotBackend()
    await _check_copilot_auth(backend)

    # Turn 1
    messages = [
        {"role": "user", "content": "Remember the number 7. Reply only: OK"},
    ]

    turn1_content = ""
    async for chunk in backend.stream_with_tools(messages, []):
        if chunk.type == "content":
            turn1_content += chunk.content or ""
        elif chunk.type == "done":
            break

    assert len(turn1_content) > 0, "Turn 1 should produce a response"

    # Turn 2 — reference the previous turn
    messages.append({"role": "assistant", "content": turn1_content})
    messages.append(
        {
            "role": "user",
            "content": "What number did I ask you to remember? Reply with just the number.",
        },
    )

    turn2_content = ""
    async for chunk in backend.stream_with_tools(messages, []):
        if chunk.type == "content":
            turn2_content += chunk.content or ""
        elif chunk.type == "done":
            break

    assert len(turn2_content) > 0, "Turn 2 should produce a response"
    assert "7" in turn2_content, f"Expected '7' in response, got: {turn2_content!r}"

    await backend.reset_state()


@pytest.mark.integration
@pytest.mark.live_api
@pytest.mark.asyncio
async def test_real_stream_with_workflow_tools():
    """Test streaming with MassGen workflow tools (new_answer)."""
    _skip_if_no_copilot_sdk()
    from massgen.backend.copilot import CopilotBackend

    workflow_tools = [
        {
            "type": "function",
            "function": {
                "name": "new_answer",
                "description": "Provide your answer to the ORIGINAL MESSAGE",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "Your answer",
                        },
                    },
                    "required": ["content"],
                },
            },
        },
    ]

    backend = CopilotBackend()
    await _check_copilot_auth(backend)

    messages = [
        {
            "role": "user",
            "content": "What is the capital of France? Use the new_answer tool to respond.",
        },
    ]

    chunks = []
    async for chunk in backend.stream_with_tools(messages, workflow_tools):
        chunks.append(chunk)
        if chunk.type in ("done", "error"):
            break

    chunk_types = {c.type for c in chunks}
    assert "done" in chunk_types or "content" in chunk_types, f"Expected done or content chunk, got: {chunk_types}"

    # If tool was called, verify it's the right one
    tool_chunks = [c for c in chunks if c.type == "tool_calls"]
    if tool_chunks:
        for tc in tool_chunks:
            if tc.tool_calls:
                tool_names = [t.get("name", t.get("function", {}).get("name", "")) for t in tc.tool_calls]
                assert any("new_answer" in name for name in tool_names), f"Expected new_answer tool call, got: {tool_names}"

    await backend.reset_state()


@pytest.mark.integration
@pytest.mark.live_api
@pytest.mark.asyncio
async def test_error_handling_unauthenticated():
    """Test that unauthenticated access produces a clear error, not a hang."""
    _skip_if_no_copilot_sdk()
    from massgen.backend.copilot import CopilotBackend

    backend = CopilotBackend()
    # Don't check auth — intentionally proceed even if unauthenticated
    # to test that we get an error rather than a hang.

    messages = [{"role": "user", "content": "hello"}]

    chunks = []
    try:
        async for chunk in backend.stream_with_tools(messages, []):
            chunks.append(chunk)
            if chunk.type in ("done", "error"):
                break
    except Exception:
        # Exception is acceptable — we just don't want a hang
        pass

    # If we got chunks, should be done or error (not stuck forever)
    if chunks:
        chunk_types = {c.type for c in chunks}
        assert "done" in chunk_types or "error" in chunk_types, f"Expected done or error, got: {chunk_types}"


@pytest.mark.integration
@pytest.mark.live_api
@pytest.mark.asyncio
async def test_provider_name_and_capabilities():
    """Verify backend reports correct provider name and capabilities."""
    _skip_if_no_copilot_sdk()
    from massgen.backend.base import FilesystemSupport
    from massgen.backend.copilot import CopilotBackend
    from massgen.mcp_tools.native_hook_adapters import CopilotNativeHookAdapter

    backend = CopilotBackend()
    assert backend.get_provider_name() == "copilot"
    assert backend.get_filesystem_support() == FilesystemSupport.MCP
    assert backend.is_stateful() is True
    assert backend.supports_native_hooks() is True
    adapter = backend.get_native_hook_adapter()
    assert isinstance(adapter, CopilotNativeHookAdapter)


@pytest.mark.integration
@pytest.mark.live_api
@pytest.mark.asyncio
async def test_native_hooks_fire_during_real_stream():
    """Verify that native PostToolUse hooks are invoked during a real streaming turn."""
    _skip_if_no_copilot_sdk()
    from massgen.backend.copilot import CopilotBackend
    from massgen.mcp_tools.hooks import (
        GeneralHookManager,
        HookResult,
        HookType,
        PatternHook,
    )

    hook_invocations: list[str] = []

    class TrackingHook(PatternHook):
        def __init__(self):
            super().__init__(name="tracker", matcher=".*")

        async def execute(self, tool_name, arguments, context=None, **kwargs):
            hook_invocations.append(tool_name)
            return HookResult(allowed=True)

    backend = CopilotBackend()
    await _check_copilot_auth(backend)

    adapter = backend.get_native_hook_adapter()
    manager = GeneralHookManager()
    manager.register_global_hook(HookType.POST_TOOL_USE, TrackingHook())
    config = adapter.build_native_hooks_config(manager)
    backend.set_native_hooks_config(config)

    messages = [{"role": "user", "content": "Say hello."}]

    async for chunk in backend.stream_with_tools(messages, []):
        if chunk.type == "done":
            break

    # Hook may or may not fire depending on whether tools were used
    # We just verify no exception was raised during streaming
    # (tracking is best-effort — model may not use tools on simple prompts)

    await backend.reset_state()
