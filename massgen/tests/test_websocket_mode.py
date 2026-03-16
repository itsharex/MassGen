"""Regression coverage for websocket mode in the Response backend."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from massgen.api_params_handler._response_api_params_handler import (
    ResponseAPIParamsHandler,
)
from massgen.backend.base import StreamChunk
from massgen.backend.base_with_custom_tool_and_mcp import CustomToolAndMCPBackend
from massgen.backend.response import ResponseBackend
from massgen.stream_chunk.base import ChunkType


def _make_mock_backend() -> MagicMock:
    """Create a minimal backend mock for API params handler tests."""
    backend = MagicMock()
    backend.formatter = MagicMock()
    backend.formatter.format_messages = MagicMock(return_value=[])
    backend.formatter.format_tools = MagicMock(return_value=[])
    backend.formatter.format_custom_tools = MagicMock(return_value=[])
    backend.custom_tool_manager = MagicMock()
    backend.custom_tool_manager.registered_tools = []
    backend._mcp_functions = {}
    backend.get_mcp_tools_formatted = MagicMock(return_value=[])
    backend._get_custom_tools_schemas = MagicMock(return_value=[])
    return backend


async def _empty_async_stream():
    """Return an empty async iterator for stream tests."""
    if False:
        yield None


def _patched_parent_stream(captured: dict[str, object]):
    """Create a fake parent stream method that records kwargs."""

    async def _fake_stream(self, messages, tools, **kwargs):
        captured["messages"] = messages
        captured["tools"] = tools
        captured["kwargs"] = dict(kwargs)
        yield StreamChunk(type="content", content="ok")

    return _fake_stream


class TestWebSocketModeParamExclusion:
    """websocket_mode must stay out of raw API payloads."""

    @pytest.mark.asyncio
    async def test_websocket_mode_not_in_built_api_params(self):
        handler = ResponseAPIParamsHandler(_make_mock_backend())

        api_params = await handler.build_api_params(
            messages=[{"role": "user", "content": "hello"}],
            tools=[],
            all_params={"model": "gpt-5.2", "websocket_mode": True},
        )

        assert "websocket_mode" not in api_params


class TestWebSocketModeApiParams:
    """Websocket mode should adjust Response API params."""

    @pytest.mark.asyncio
    async def test_stream_present_when_websocket_mode_false(self):
        handler = ResponseAPIParamsHandler(_make_mock_backend())

        api_params = await handler.build_api_params(
            messages=[{"role": "user", "content": "hello"}],
            tools=[],
            all_params={"model": "gpt-5.2", "websocket_mode": False},
        )

        assert api_params.get("stream") is True

    @pytest.mark.asyncio
    async def test_stream_stripped_when_websocket_mode_true(self):
        handler = ResponseAPIParamsHandler(_make_mock_backend())

        api_params = await handler.build_api_params(
            messages=[{"role": "user", "content": "hello"}],
            tools=[],
            all_params={"model": "gpt-5.2", "websocket_mode": True},
        )

        assert "stream" not in api_params


class TestWebSocketModeConfigValidation:
    """Config validation should treat websocket_mode as boolean-only."""

    def test_valid_boolean_true_accepted(self):
        from massgen.config_validator import ConfigValidator

        config = {
            "agents": [
                {
                    "id": "test",
                    "backend": {
                        "type": "openai",
                        "model": "gpt-5.2",
                        "websocket_mode": True,
                    },
                },
            ],
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)
        ws_errors = [error for error in result.errors if "websocket_mode" in str(error)]
        assert ws_errors == []

    def test_non_boolean_rejected(self):
        from massgen.config_validator import ConfigValidator

        config = {
            "agents": [
                {
                    "id": "test",
                    "backend": {
                        "type": "openai",
                        "model": "gpt-5.2",
                        "websocket_mode": "yes",
                    },
                },
            ],
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)
        ws_errors = [error for error in result.errors if "websocket_mode" in str(error)]
        assert ws_errors


class TestWebSocketTransport:
    """Tests for the standalone websocket transport."""

    def test_transport_builds_correct_url(self):
        from massgen.backend._websocket_transport import WebSocketResponseTransport

        transport = WebSocketResponseTransport(api_key="test-key")
        assert transport.url == "wss://api.openai.com/v1/responses"

    def test_transport_includes_auth_header(self):
        from massgen.backend._websocket_transport import WebSocketResponseTransport

        transport = WebSocketResponseTransport(api_key="sk-test123")
        headers = transport._build_headers()
        assert headers["Authorization"] == "Bearer sk-test123"

    def test_transport_wraps_payload_as_response_create(self):
        from massgen.backend._websocket_transport import WebSocketResponseTransport

        transport = WebSocketResponseTransport(api_key="test-key")
        wrapped = transport._build_response_create_event(
            {"model": "gpt-5.2", "input": []},
        )
        parsed = json.loads(wrapped)

        assert parsed["type"] == "response.create"
        assert parsed["model"] == "gpt-5.2"
        assert parsed["input"] == []
        assert "response" not in parsed

    @pytest.mark.asyncio
    async def test_transport_connect_failure_raises(self):
        from massgen.backend._websocket_transport import (
            WebSocketConnectionError,
            WebSocketResponseTransport,
        )

        transport = WebSocketResponseTransport(api_key="invalid-key")
        with (
            patch(
                "massgen.backend._websocket_transport.websockets.connect",
                new=AsyncMock(side_effect=RuntimeError("boom")),
            ),
            patch(
                "massgen.backend._websocket_transport.asyncio.sleep",
                new=AsyncMock(),
            ),
            pytest.raises(WebSocketConnectionError, match="Failed to connect"),
        ):
            await transport.connect()

    @pytest.mark.asyncio
    async def test_transport_raises_with_nested_error_payload(self):
        from massgen.backend._websocket_transport import (
            WebSocketConnectionError,
            WebSocketResponseTransport,
        )

        transport = WebSocketResponseTransport(api_key="test-key")

        ws = MagicMock()
        ws.send = AsyncMock()
        ws.__aiter__.return_value = [
            json.dumps(
                {
                    "type": "error",
                    "error": {
                        "type": "insufficient_quota",
                        "code": "insufficient_quota",
                        "message": "quota exceeded",
                        "param": None,
                    },
                    "sequence_number": 2,
                },
            ),
        ]
        transport._ws = ws

        with pytest.raises(WebSocketConnectionError, match="quota exceeded"):
            async for _ in transport.send_and_receive({"model": "gpt-5.2"}):
                pass

        ws.send.assert_awaited_once()


class TestResponseBackendWebSocketMode:
    """ResponseBackend should integrate websocket mode without leaking internals."""

    def test_websocket_mode_defaults_false_and_reads_from_config(self):
        assert ResponseBackend(api_key="test-key", model="gpt-5.2")._websocket_mode is False
        assert ResponseBackend(api_key="test-key", model="gpt-5.2", websocket_mode=True)._websocket_mode is True

    @pytest.mark.asyncio
    async def test_stream_with_tools_establishes_and_closes_websocket_transport(self):
        captured: dict[str, object] = {}
        transport = MagicMock()
        transport.connect = AsyncMock()
        transport.close = AsyncMock()

        with (
            patch(
                "massgen.backend._websocket_transport.WebSocketResponseTransport",
                return_value=transport,
            ) as transport_cls,
            patch.object(
                CustomToolAndMCPBackend,
                "stream_with_tools",
                new=_patched_parent_stream(captured),
            ),
        ):
            backend = ResponseBackend(
                api_key="test-key",
                model="gpt-5.2",
                websocket_mode=True,
            )
            chunks = [
                chunk
                async for chunk in backend.stream_with_tools(
                    [{"role": "user", "content": "hello"}],
                    [],
                )
            ]

        assert len(chunks) == 1
        transport_cls.assert_called_once_with(
            api_key="test-key",
            organization=None,
        )
        transport.connect.assert_awaited_once()
        transport.close.assert_awaited_once()
        assert captured["kwargs"]["_ws_transport"] is transport

    @pytest.mark.asyncio
    async def test_stream_with_tools_falls_back_to_http_when_connect_fails(self):
        captured: dict[str, object] = {}
        transport = MagicMock()
        transport.connect = AsyncMock(side_effect=RuntimeError("boom"))
        transport.close = AsyncMock()

        with (
            patch(
                "massgen.backend._websocket_transport.WebSocketResponseTransport",
                return_value=transport,
            ),
            patch.object(
                CustomToolAndMCPBackend,
                "stream_with_tools",
                new=_patched_parent_stream(captured),
            ),
        ):
            backend = ResponseBackend(
                api_key="test-key",
                model="gpt-5.2",
                websocket_mode=True,
            )
            chunks = [
                chunk
                async for chunk in backend.stream_with_tools(
                    [{"role": "user", "content": "hello"}],
                    [],
                )
            ]

        assert len(chunks) == 1
        transport.connect.assert_awaited_once()
        transport.close.assert_not_awaited()
        assert "_ws_transport" not in captured["kwargs"]
        assert captured["kwargs"].get("websocket_mode") is False

    @pytest.mark.asyncio
    async def test_create_response_stream_uses_http_without_websocket_transport(self):
        backend = ResponseBackend(api_key="test-key", model="gpt-5.2")
        client = MagicMock()
        client.responses.create = AsyncMock(return_value="http-stream")

        stream = await backend._create_response_stream(
            {"model": "gpt-5.2"},
            client,
            None,
        )

        assert stream == "http-stream"
        client.responses.create.assert_awaited_once_with(model="gpt-5.2")

    @pytest.mark.asyncio
    async def test_create_response_stream_uses_websocket_when_connected(self):
        backend = ResponseBackend(api_key="test-key", model="gpt-5.2")
        client = MagicMock()
        ws_transport = MagicMock()
        ws_transport.is_connected = True

        async def _ws_events():
            yield {"type": "response.output_text.delta", "delta": "hi"}

        ws_transport.send_and_receive = MagicMock(return_value=_ws_events())

        stream = await backend._create_response_stream(
            {"model": "gpt-5.2"},
            client,
            ws_transport,
        )
        events = [event async for event in stream]

        assert len(events) == 1
        assert events[0].type == "response.output_text.delta"
        assert events[0].delta == "hi"
        client.responses.create.assert_not_called()

    def test_ws_event_supports_attribute_and_mapping_access(self):
        from massgen.backend.response import _WSEvent

        event = _WSEvent(
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "web_search_call",
                    "action": {"query": "hello"},
                },
            },
        )

        assert event.type == "response.output_item.done"
        assert event.item.type == "web_search_call"
        assert "query" in event.item.action
        assert event.item.action["query"] == "hello"
        assert event.model_dump()["item"]["action"]["query"] == "hello"
        assert hasattr(event, "item")
        assert not hasattr(event, "missing")

    @pytest.mark.asyncio
    async def test_stream_with_custom_tools_filters_ws_internal_kwargs(self):
        backend = ResponseBackend(api_key="test-key", model="gpt-5.2")
        backend._create_response_stream = AsyncMock(return_value=_empty_async_stream())

        async for _ in backend._stream_with_custom_and_mcp_tools(
            current_messages=[{"role": "user", "content": "hello"}],
            tools=[],
            client=MagicMock(),
            model="gpt-5.2",
            _ws_transport=object(),
        ):
            pass

        api_params = backend._create_response_stream.await_args.args[0]
        assert "_ws_transport" not in api_params


def _make_mock_chunk(chunk_type: str, **attrs) -> MagicMock:
    """Create a mock stream chunk with a given type and arbitrary attributes."""
    chunk = MagicMock()
    chunk.type = chunk_type
    for k, v in attrs.items():
        setattr(chunk, k, v)
    return chunk


def _make_failed_chunk(error_message: str = "server error") -> MagicMock:
    """Create a mock response.failed chunk with nested error."""
    chunk = MagicMock()
    chunk.type = "response.failed"
    chunk.response = MagicMock()
    chunk.response.error = MagicMock()
    chunk.response.error.message = error_message
    return chunk


async def _run_ws_stream_with_tools(backend_kwargs):
    """Shared helper: create WS backend, patch transport, call stream_with_tools.

    Returns (transport_cls_mock, captured_kwargs).
    """
    captured: dict[str, object] = {}
    transport = MagicMock()
    transport.connect = AsyncMock()
    transport.close = AsyncMock()

    with (
        patch(
            "massgen.backend._websocket_transport.WebSocketResponseTransport",
            return_value=transport,
        ) as transport_cls,
        patch.object(
            CustomToolAndMCPBackend,
            "stream_with_tools",
            new=_patched_parent_stream(captured),
        ),
    ):
        backend = ResponseBackend(**backend_kwargs)
        _ = [
            chunk
            async for chunk in backend.stream_with_tools(
                [{"role": "user", "content": "hello"}],
                [],
            )
        ]

    return transport_cls, captured


class TestResponseFailed:
    """response.failed must produce exactly one error chunk in both MCP and non-MCP paths."""

    @pytest.mark.asyncio
    async def test_response_failed_yields_error_in_mcp_path(self):
        """A bare response.failed should yield exactly one ERROR, no DONE, and return immediately."""
        backend = ResponseBackend(api_key="test-key", model="gpt-5.2")
        failed_chunk = _make_failed_chunk("rate limit exceeded")

        async def _stream(*args, **kwargs):
            yield failed_chunk

        backend._create_response_stream = AsyncMock(side_effect=_stream)

        with patch.object(
            backend,
            "end_api_call_timing",
            wraps=backend.end_api_call_timing,
        ) as timing_spy:
            chunks = []
            async for c in backend._stream_with_custom_and_mcp_tools(
                current_messages=[{"role": "user", "content": "hi"}],
                tools=[],
                client=MagicMock(),
                model="gpt-5.2",
            ):
                chunks.append(c)

        error_chunks = [c for c in chunks if getattr(c, "type", None) in [ChunkType.ERROR, "error"]]
        done_chunks = [c for c in chunks if getattr(c, "type", None) in [ChunkType.DONE, "done"]]
        assert len(error_chunks) == 1, f"Expected exactly 1 error chunk, got {len(error_chunks)}"
        assert "rate limit" in (getattr(error_chunks[0], "error", "") or "")
        assert len(done_chunks) == 0, "No DONE chunk should be emitted on failure"
        timing_spy.assert_called_once()
        timing_spy.assert_called_with(success=False, error="rate limit exceeded")

    @pytest.mark.asyncio
    async def test_response_failed_yields_error_in_process_stream(self):
        """_process_stream should detect response.failed, yield exactly one ERROR, and return."""
        backend = ResponseBackend(api_key="test-key", model="gpt-5.2")
        backend.start_api_call_timing("gpt-5.2")

        failed_chunk = _make_failed_chunk("quota exceeded")

        async def _stream():
            yield failed_chunk

        with patch.object(
            backend,
            "end_api_call_timing",
            wraps=backend.end_api_call_timing,
        ) as timing_spy:
            chunks = []
            async for c in backend._process_stream(_stream(), {}, agent_id="test"):
                chunks.append(c)

        error_chunks = [c for c in chunks if getattr(c, "type", None) in [ChunkType.ERROR, "error"]]
        done_chunks = [c for c in chunks if getattr(c, "type", None) in [ChunkType.DONE, "done"]]
        assert len(error_chunks) == 1, f"Expected exactly 1 error chunk, got {len(error_chunks)}"
        assert "quota exceeded" in (getattr(error_chunks[0], "error", "") or "")
        assert len(done_chunks) == 0, "No DONE chunk should be emitted on failure"
        timing_spy.assert_called_once()
        timing_spy.assert_called_with(success=False, error="quota exceeded")


class TestBackgroundSuppressionWebSocketMode:
    """background must be excluded from API params in websocket mode."""

    @pytest.mark.asyncio
    async def test_background_excluded_in_websocket_mode(self):
        handler = ResponseAPIParamsHandler(_make_mock_backend())

        api_params = await handler.build_api_params(
            messages=[{"role": "user", "content": "hello"}],
            tools=[],
            all_params={
                "model": "gpt-5.2",
                "websocket_mode": True,
                "background": True,
            },
        )

        assert "background" not in api_params

    @pytest.mark.asyncio
    async def test_background_present_in_non_websocket_mode(self):
        handler = ResponseAPIParamsHandler(_make_mock_backend())

        api_params = await handler.build_api_params(
            messages=[{"role": "user", "content": "hello"}],
            tools=[],
            all_params={
                "model": "gpt-5.2",
                "websocket_mode": False,
                "background": True,
            },
        )

        assert api_params.get("background") is True


class TestWebSocketTransportConfigParity:
    """WebSocket transport must receive organization and custom URL from config."""

    @pytest.mark.asyncio
    async def test_transport_receives_organization_from_config(self):
        transport_cls, _ = await _run_ws_stream_with_tools(
            {
                "api_key": "test-key",
                "model": "gpt-5.2",
                "websocket_mode": True,
                "organization": "org-test123",
            },
        )
        assert transport_cls.call_args[1].get("organization") == "org-test123"

    @pytest.mark.asyncio
    async def test_transport_receives_custom_url_from_base_url(self):
        transport_cls, _ = await _run_ws_stream_with_tools(
            {
                "api_key": "test-key",
                "model": "gpt-5.2",
                "websocket_mode": True,
                "base_url": "https://custom.api.example.com/v1",
            },
        )
        assert transport_cls.call_args[1].get("url") == "wss://custom.api.example.com/v1/responses"


class TestResponseCompletedRegression:
    """response.incomplete without tool calls must still work (regression guard)."""

    @pytest.mark.asyncio
    async def test_response_incomplete_without_tool_calls(self):
        backend = ResponseBackend(api_key="test-key", model="gpt-5.2")

        incomplete_chunk = MagicMock()
        incomplete_chunk.type = "response.incomplete"
        incomplete_chunk.response = MagicMock()
        incomplete_chunk.response.usage = MagicMock(spec=[])
        incomplete_chunk.response.usage.input_tokens = 10
        incomplete_chunk.response.usage.output_tokens = 5
        incomplete_chunk.response.id = "resp_456"
        incomplete_chunk.response.output = []

        async def _stream(*args, **kwargs):
            yield incomplete_chunk

        backend._create_response_stream = AsyncMock(side_effect=_stream)

        chunks = []
        async for c in backend._stream_with_custom_and_mcp_tools(
            current_messages=[{"role": "user", "content": "hi"}],
            tools=[],
            client=MagicMock(),
            model="gpt-5.2",
        ):
            chunks.append(c)

        done_chunks = [c for c in chunks if getattr(c, "type", None) in [ChunkType.DONE, "done"]]
        error_chunks = [c for c in chunks if getattr(c, "type", None) in [ChunkType.ERROR, "error"]]
        assert len(done_chunks) == 1, f"Expected exactly 1 done chunk, got {len(done_chunks)}"
        assert len(error_chunks) == 0


class TestWebSocketFallbackParity:
    """HTTP fallback after websocket connect failure must preserve client config and streaming."""

    @pytest.mark.asyncio
    async def test_create_client_passes_base_url_and_organization(self):
        """_create_client() must pass base_url and organization to AsyncOpenAI."""
        backend = ResponseBackend(
            api_key="test-key",
            model="gpt-5.2",
            base_url="https://custom.api.example.com/v1",
            organization="org-custom",
        )

        with patch("massgen.backend.response.openai.AsyncOpenAI") as mock_openai:
            mock_openai.return_value = MagicMock()
            backend._create_client()

        call_kwargs = mock_openai.call_args
        assert call_kwargs[1].get("base_url") == "https://custom.api.example.com/v1"
        assert call_kwargs[1].get("organization") == "org-custom"

    @pytest.mark.asyncio
    async def test_create_response_stream_falls_to_http_when_transport_disconnected(
        self,
    ):
        """_create_response_stream with a non-None but disconnected transport
        must use the HTTP path, not attempt WebSocket send."""
        backend = ResponseBackend(api_key="test-key", model="gpt-5.2")
        client = MagicMock()
        client.responses.create = AsyncMock(return_value="http-stream")

        ws_transport = MagicMock()
        ws_transport.is_connected = False

        stream = await backend._create_response_stream(
            {"model": "gpt-5.2", "stream": True},
            client,
            ws_transport,
        )

        assert stream == "http-stream"
        client.responses.create.assert_awaited_once_with(model="gpt-5.2", stream=True)
        ws_transport.send_and_receive.assert_not_called()


class TestMidStreamDisconnect:
    """Mid-stream websocket loss must fail cleanly with one error chunk."""

    @pytest.mark.asyncio
    async def test_midstream_exception_preserves_content_and_yields_one_error(self):
        """Stream yields content then raises; expect early content, one ERROR, no DONE."""
        backend = ResponseBackend(api_key="test-key", model="gpt-5.2")

        content_chunk = _make_mock_chunk("response.output_text.delta", delta="partial")

        async def _stream(*args, **kwargs):
            yield content_chunk
            raise ConnectionError("websocket closed unexpectedly")

        backend._create_response_stream = AsyncMock(side_effect=_stream)

        with patch.object(
            backend,
            "end_api_call_timing",
            wraps=backend.end_api_call_timing,
        ) as timing_spy:
            chunks = []
            async for c in backend._stream_with_custom_and_mcp_tools(
                current_messages=[{"role": "user", "content": "hi"}],
                tools=[],
                client=MagicMock(),
                model="gpt-5.2",
            ):
                chunks.append(c)

        content_chunks = [c for c in chunks if getattr(c, "type", None) in [ChunkType.CONTENT, "content"] and getattr(c, "content", None)]
        assert len(content_chunks) >= 1, "Early content before disconnect should be preserved"

        error_chunks = [c for c in chunks if getattr(c, "type", None) in [ChunkType.ERROR, "error"]]
        done_chunks = [c for c in chunks if getattr(c, "type", None) in [ChunkType.DONE, "done"]]
        assert len(error_chunks) == 1, f"Expected exactly 1 error chunk after mid-stream disconnect, got {len(error_chunks)}"
        assert "websocket closed" in (getattr(error_chunks[0], "error", "") or "").lower()
        assert len(done_chunks) == 0, "No DONE chunk should be emitted after disconnect"
        timing_spy.assert_called_once()
        call_kwargs = timing_spy.call_args[1]
        assert call_kwargs["success"] is False

    @pytest.mark.asyncio
    async def test_midstream_exception_no_tool_recursion(self):
        """After mid-stream disconnect, the stream must not attempt tool recursion."""
        backend = ResponseBackend(api_key="test-key", model="gpt-5.2")

        fc_item = MagicMock()
        fc_item.type = "function_call"
        fc_item.call_id = "call_1"
        fc_item.name = "my_tool"

        added_chunk = _make_mock_chunk("response.output_item.added", item=fc_item)

        stream_call_count = 0

        async def _stream(*args, **kwargs):
            nonlocal stream_call_count
            stream_call_count += 1
            yield added_chunk
            raise ConnectionError("socket died")

        backend._create_response_stream = AsyncMock(side_effect=_stream)

        chunks = []
        async for c in backend._stream_with_custom_and_mcp_tools(
            current_messages=[{"role": "user", "content": "hi"}],
            tools=[],
            client=MagicMock(),
            model="gpt-5.2",
        ):
            chunks.append(c)

        error_chunks = [c for c in chunks if getattr(c, "type", None) in [ChunkType.ERROR, "error"]]
        assert len(error_chunks) == 1, f"Expected exactly 1 error chunk, got {len(error_chunks)}"
        assert stream_call_count == 1, "Stream must not recurse after mid-stream disconnect"


class TestNonMCPMidStreamDisconnect:
    """Non-MCP _process_stream path must handle mid-stream exceptions cleanly."""

    @pytest.mark.asyncio
    async def test_process_stream_midstream_exception_yields_one_error(self):
        """Stream yields content then raises; expect content preserved, 1 ERROR, 0 DONE."""
        backend = ResponseBackend(api_key="test-key", model="gpt-5.2")
        backend.start_api_call_timing("gpt-5.2")

        content_chunk = _make_mock_chunk("response.output_text.delta", delta="partial")

        async def _stream():
            yield content_chunk
            raise ConnectionError("socket reset")

        with patch.object(
            backend,
            "end_api_call_timing",
            wraps=backend.end_api_call_timing,
        ) as timing_spy:
            chunks = []
            async for c in backend._process_stream(_stream(), {}, agent_id="test"):
                chunks.append(c)

        content_chunks = [c for c in chunks if getattr(c, "type", None) in [ChunkType.CONTENT, "content"] and getattr(c, "content", None)]
        error_chunks = [c for c in chunks if getattr(c, "type", None) in [ChunkType.ERROR, "error"]]
        done_chunks = [c for c in chunks if getattr(c, "type", None) in [ChunkType.DONE, "done"]]
        assert len(content_chunks) >= 1, "Early content before exception should be preserved"
        assert len(error_chunks) == 1, f"Expected exactly 1 error chunk, got {len(error_chunks)}"
        assert "socket reset" in (getattr(error_chunks[0], "error", "") or "").lower()
        assert len(done_chunks) == 0, "No DONE chunk should be emitted after exception"
        timing_spy.assert_called_once()
        call_kwargs = timing_spy.call_args[1]
        assert call_kwargs["success"] is False
