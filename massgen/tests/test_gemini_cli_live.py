"""Live API integration tests for GeminiCLIBackend with actual Gemini CLI.

These tests require:
- Gemini CLI installed: npm install -g @google/gemini-cli
- GOOGLE_API_KEY or GEMINI_API_KEY set in environment (or `gemini` login)

Run with: uv run pytest massgen/tests/test_gemini_cli_live.py -v --run-integration --run-live-api
"""

from __future__ import annotations

import os
import tempfile

import pytest

from massgen.backend.gemini_cli import GeminiCLIBackend


def _has_gemini_credentials() -> bool:
    """Check if Gemini CLI credentials are available."""
    return bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))


def _skip_if_no_credentials():
    if not _has_gemini_credentials():
        pytest.skip("GEMINI_API_KEY / GOOGLE_API_KEY not found in environment")


def _skip_if_no_gemini_cli():
    import shutil

    if not shutil.which("gemini"):
        pytest.skip("Gemini CLI not installed (npm install -g @google/gemini-cli)")


@pytest.mark.integration
@pytest.mark.live_api
@pytest.mark.asyncio
async def test_real_stream_single_turn():
    """Test real single-turn streaming with Gemini CLI."""
    _skip_if_no_credentials()
    _skip_if_no_gemini_cli()

    with tempfile.TemporaryDirectory() as tmpdir:
        backend = GeminiCLIBackend(cwd=tmpdir)

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

        # Should have received at least one content chunk and a done chunk
        content_chunks = [c for c in chunks if c.type == "content"]
        done_chunks = [c for c in chunks if c.type == "done"]
        assert len(content_chunks) >= 1, "Expected at least one content chunk"
        assert len(done_chunks) == 1, "Expected exactly one done chunk"
        assert len(total_content) > 0, "Expected non-empty response"

        # Verify usage stats are present in the done chunk
        done_chunk = done_chunks[0]
        if done_chunk.usage:
            assert done_chunk.usage.get("prompt_tokens", 0) > 0 or done_chunk.usage.get("total_tokens", 0) > 0


@pytest.mark.integration
@pytest.mark.live_api
@pytest.mark.asyncio
async def test_real_stream_multi_turn():
    """Test multi-turn streaming with session persistence."""
    _skip_if_no_credentials()
    _skip_if_no_gemini_cli()

    with tempfile.TemporaryDirectory() as tmpdir:
        backend = GeminiCLIBackend(cwd=tmpdir)

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

        # Session should be established
        session_id = backend.session_id

        # Turn 2 — reference the previous turn
        messages.append({"role": "assistant", "content": turn1_content})
        messages.append(
            {"role": "user", "content": "What number did I ask you to remember? Reply with just the number."},
        )

        turn2_content = ""
        async for chunk in backend.stream_with_tools(messages, []):
            if chunk.type == "content":
                turn2_content += chunk.content or ""
            elif chunk.type == "done":
                break

        assert len(turn2_content) > 0, "Turn 2 should produce a response"
        # The response should contain "7" since we asked it to remember that number
        assert "7" in turn2_content, f"Expected '7' in response, got: {turn2_content}"

        # Session should be reused if available
        if session_id:
            assert backend.session_id == session_id, "Session ID should be stable across turns"


@pytest.mark.integration
@pytest.mark.live_api
@pytest.mark.asyncio
async def test_real_stream_with_workflow_tools():
    """Test streaming with MassGen workflow tools (new_answer)."""
    _skip_if_no_credentials()
    _skip_if_no_gemini_cli()

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

    with tempfile.TemporaryDirectory() as tmpdir:
        backend = GeminiCLIBackend(cwd=tmpdir)

        messages = [
            {"role": "user", "content": "What is the capital of France? Use the new_answer tool to respond."},
        ]

        chunks = []
        async for chunk in backend.stream_with_tools(messages, workflow_tools):
            chunks.append(chunk)
            if chunk.type in ("done", "error"):
                break

        # Should have at least a done or content chunk
        chunk_types = {c.type for c in chunks}
        assert "done" in chunk_types or "content" in chunk_types, f"Expected done or content chunk, got types: {chunk_types}"

        # Check for tool calls (the model may or may not use the tool)
        tool_chunks = [c for c in chunks if c.type == "tool_calls"]
        if tool_chunks:
            # If tool was called, verify it's the right one
            for tc in tool_chunks:
                if tc.tool_calls:
                    tool_names = [t.get("name", t.get("function", {}).get("name", "")) for t in tc.tool_calls]
                    assert any("new_answer" in name for name in tool_names), f"Expected new_answer tool call, got: {tool_names}"


@pytest.mark.integration
@pytest.mark.live_api
@pytest.mark.asyncio
async def test_settings_json_written_with_hooks_config():
    """Verify settings.json is written correctly when hooks config is set."""
    _skip_if_no_credentials()
    _skip_if_no_gemini_cli()

    import json

    with tempfile.TemporaryDirectory() as tmpdir:
        backend = GeminiCLIBackend(cwd=tmpdir)

        # Simulate hooks config from orchestrator
        backend._massgen_hooks_config = {
            "hooks": {
                "AfterTool": [
                    {
                        "matcher": ".*",
                        "hooks": [
                            {"type": "command", "command": "echo {}", "timeout": 10000},
                        ],
                    },
                ],
            },
        }

        # Trigger workspace config write
        backend.system_prompt = "You are a test agent."
        backend._write_workspace_config()

        settings_path = backend._workspace_config_dir() / "settings.json"
        assert settings_path.exists(), "settings.json should be written"

        settings = json.loads(settings_path.read_text())
        assert "hooks" in settings, "hooks section should be in settings.json"
        assert "AfterTool" in settings["hooks"], "AfterTool hooks should be present"
        assert "tools" in settings, "tools section should be in settings.json"
        assert "exclude" in settings["tools"], "tools.exclude should be present"


@pytest.mark.integration
@pytest.mark.live_api
@pytest.mark.asyncio
async def test_error_handling_invalid_model():
    """Test that invalid model produces a clear error, not a hang."""
    _skip_if_no_credentials()
    _skip_if_no_gemini_cli()

    with tempfile.TemporaryDirectory() as tmpdir:
        backend = GeminiCLIBackend(
            model="gemini-nonexistent-model-xyz",
            cwd=tmpdir,
        )

        messages = [{"role": "user", "content": "hello"}]

        chunks = []
        async for chunk in backend.stream_with_tools(messages, []):
            chunks.append(chunk)
            if chunk.type in ("done", "error"):
                break

        # Should get an error chunk, not hang forever
        error_chunks = [c for c in chunks if c.type == "error"]
        assert len(error_chunks) >= 1 or any(c.type == "done" for c in chunks), "Should get an error or done chunk for invalid model"


@pytest.mark.integration
@pytest.mark.live_api
@pytest.mark.asyncio
async def test_provider_name_and_capabilities():
    """Verify backend reports correct provider name and capabilities."""
    _skip_if_no_gemini_cli()

    from massgen.backend.base import FilesystemSupport

    with tempfile.TemporaryDirectory() as tmpdir:
        backend = GeminiCLIBackend(cwd=tmpdir)

        assert backend.get_provider_name() == "Gemini CLI"
        assert backend.get_filesystem_support() == FilesystemSupport.NATIVE
        assert backend.is_stateful() is True
        assert backend.supports_mcp_server_hooks() is True
        assert backend.supports_native_hooks() is True
