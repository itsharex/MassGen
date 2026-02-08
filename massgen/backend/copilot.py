# -*- coding: utf-8 -*-
"""
GitHub Copilot backend implementation using github-copilot-sdk.

Reimplemented to use MCP server integration similar to Codex and Claude Code backends.
Supports custom tools and MCP servers via the SDK's native mcpServers configuration.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

try:
    from copilot import CopilotClient
    COPILOT_SDK_AVAILABLE = True
except ImportError:
    COPILOT_SDK_AVAILABLE = False
    CopilotClient = object

from ..logger_config import logger
from ._streaming_buffer_mixin import StreamingBufferMixin
from .base import FilesystemSupport, LLMBackend, StreamChunk
from .native_tool_mixin import NativeToolBackendMixin


class CopilotBackend(NativeToolBackendMixin, StreamingBufferMixin, LLMBackend):
    """GitHub Copilot backend integration with native MCP support."""

    def __init__(self, api_key: Optional[str] = None, **kwargs):
        """Initialize Copilot backend."""
        if not COPILOT_SDK_AVAILABLE:
            raise ImportError(
                "github-copilot-sdk is required for CopilotBackend. "
                "Install it with: pip install github-copilot-sdk"
            )

        super().__init__(api_key, **kwargs)
        self.__init_native_tool_mixin__()
        
        # Copilot SDK setup
        self.client = CopilotClient()
        self.sessions: Dict[str, Any] = {}
        self._started = False
        
        # Use existing SDK authentication if possible (no API key needed if logged in via `copilot login`)
        # If API key provided, SDK might use it if configured (though SDK usually relies on its own auth)
        
        # MCP support initialization
        self.mcp_servers = self.config.get("mcp_servers", [])
        
        # Determine current working directory
        if not self.filesystem_manager:
            self._cwd: str = os.getcwd()
        else:
            self._cwd = str(Path(str(self.filesystem_manager.get_current_workspace())).resolve())

        # Custom tools setup (packaged as MCP server)
        self._custom_tool_specs_path: Optional[Path] = None
        custom_tools = list(kwargs.get("custom_tools", []))
        
        # Register multimodal tools if enabled
        enable_multimodal = self.config.get("enable_multimodal_tools", False) or kwargs.get("enable_multimodal_tools", False)
        if enable_multimodal:
            from .base import get_multimodal_tool_definitions
            custom_tools.extend(get_multimodal_tool_definitions())
            logger.info("Copilot backend: multimodal tools enabled (read_media, generate_media)")

        if custom_tools:
            self._setup_custom_tools_mcp(custom_tools)

    def get_provider_name(self) -> str:
        return "copilot"

    def get_filesystem_support(self) -> FilesystemSupport:
        """Copilot SDK native support via MCP filesystem server."""
        return FilesystemSupport.MCP

    def get_disallowed_tools(self, config: Dict[str, Any]) -> List[str]:
        """Return native Copilot tools to disable."""
        # Copilot SDK typically starts with no tools unless configured via mcpServers
        # But we can list any we definitely don't want if they were to appear.
        return []

    def get_tool_category_overrides(self) -> Dict[str, str]:
        """Return tool category overrides."""
        # Since we use MCP for filesystem, we don't skip it.
        # But if Copilot eventually adds native tools, we might need to adjust.
        return {}

    async def _ensure_started(self):
        """Ensure the Copilot client is started."""
        if not self._started:
            try:
                await self.client.start()
                self._started = True
            except Exception as e:
                # Ignore if already running or check state
                if "already running" not in str(e):
                    logger.warning(f"Client start warning: {e}")
                self._started = True

    def _setup_custom_tools_mcp(self, custom_tools: List[Dict[str, Any]]) -> None:
        """Wrap MassGen custom tools as an MCP server and add to mcp_servers."""
        try:
            from ..mcp_tools.custom_tools_server import (
                build_server_config,
                write_tool_specs,
            )
        except ImportError:
            logger.warning("custom_tools_server not available, skipping custom tools")
            return

        # Store raw config so specs can be handled if needed
        self._custom_tools_config = custom_tools

        # Write specs to workspace/.copilot/custom_tool_specs.json
        config_dir = Path(self._cwd) / ".copilot"
        config_dir.mkdir(parents=True, exist_ok=True)
        specs_path = config_dir / "custom_tool_specs.json"
        
        write_tool_specs(custom_tools, specs_path)
        self._custom_tools_specs_path = specs_path

        # Build MCP server config and add to mcp_servers
        server_config = build_server_config(
            tool_specs_path=specs_path,
            allowed_paths=[self._cwd],
            agent_id=self.config.get("agent_id") or "copilot",
            env=self._build_custom_tools_mcp_env(),
        )
        
        # Add tool names to allowed list for cleaner config
        # Copilot SDK usually wants explicit tool lists or "*"
        if "tools" not in server_config:
             server_config["tools"] = ["*"]

        # Append to mcp_servers list (handled in create_session)
        self.mcp_servers.append(server_config)
        logger.info(f"Custom tools MCP server configured with {len(custom_tools)} tool configs")

    def _build_custom_tools_mcp_env(self) -> Dict[str, str]:
        """Build environment variables for the custom tools MCP server."""
        env_vars = {"FASTMCP_SHOW_CLI_BANNER": "false"}
        
        if not self.config:
            return env_vars
            
        creds = self.config.get("command_line_docker_credentials") or {}
        if not creds:
             return env_vars

        # Helper to load .env files
        def _load_env_file(env_file_path: Path) -> Dict[str, str]:
            loaded: Dict[str, str] = {}
            try:
                with open(env_file_path, "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        key, value = line.split("=", 1)
                        loaded[key.strip()] = value.strip()
            except Exception as e:
                logger.warning(f"⚠️ [Copilot] Failed to read env file {env_file_path}: {e}")
            return loaded

        # Pass all env vars if configured
        if creds.get("pass_all_env"):
            env_vars.update(os.environ)

        # Load from env_file
        env_file = creds.get("env_file")
        if env_file:
            env_path = Path(env_file).expanduser().resolve()
            if env_path.exists():
                file_env = _load_env_file(env_path)
                filter_list = creds.get("env_vars_from_file")
                if filter_list:
                    filtered_env = {k: v for k, v in file_env.items() if k in filter_list}
                    env_vars.update(filtered_env)
                else:
                    env_vars.update(file_env)

        # Pass specific env vars from host
        for var_name in creds.get("env_vars", []) or []:
            if var_name in os.environ:
                env_vars[var_name] = os.environ[var_name]

        # Always enforce banner suppression
        env_vars["FASTMCP_SHOW_CLI_BANNER"] = "false"
        return env_vars

    async def _process_stream(
        self,
        stream,
        all_params,
        agent_id: Optional[str] = None,
    ) -> AsyncGenerator[StreamChunk, None]:
        # Not used - handled by steam_with_tools logic
        raise NotImplementedError("CopilotBackend uses stream_with_tools")
        yield # pragma: no cover

    async def stream_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        **kwargs
    ) -> AsyncGenerator[StreamChunk, None]:
        """Stream with tool support using Copilot Sessions (MCP-native)."""
        await self._ensure_started()

        agent_id = kwargs.get("agent_id", self.config.get("agent_id") or "default")
        
        # Create a queue for events (mixed SessionEvent and StreamChunk)
        queue = asyncio.Queue()

        # Get or Update session
        session = self.sessions.get(agent_id)

        # Extract system message
        system_message = None
        for msg in messages:
            if msg["role"] == "system":
                content = msg.get("content", "")
                if isinstance(content, list):
                    content = "\n".join(
                        block.get("text", "") if isinstance(block, dict) else str(block)
                        for block in content
                    )
                if content:
                    system_message = content
                break
        
        # Build prompt from conversation history (excluding system message)
        prompt_parts = []
        for msg in messages:
             if msg["role"] != "system":
                role = msg["role"]
                content = msg.get("content", "")
                if isinstance(content, list):
                    content = "\n".join(
                        block.get("text", "") if isinstance(block, dict) else str(block)
                        for block in content
                    )
                if content:
                    prompt_parts.append(f"[{role}]: {content}")
        
        prompt = "\n\n".join(prompt_parts) if prompt_parts else "Please continue."

        # Setup MCP servers config
        # Convert list of MCP configs to dictionary format expected by SDK
        mcp_servers_dict = {}
        
        # Merge self.config "mcp_servers" (which might contain filesystem MCP injected by base class)
        # and self.mcp_servers (which contains custom tools MCP)
        # We need to handle duplications carefully.
        
        all_mcp_servers = []
        
        # 1. Configured servers (e.g. filesystem)
        config_mcp = self.config.get("mcp_servers", [])
        if isinstance(config_mcp, dict):
            for name, srv in config_mcp.items():
                srv_copy = srv.copy()
                srv_copy["name"] = name
                all_mcp_servers.append(srv_copy)
        elif isinstance(config_mcp, list):
            all_mcp_servers.extend(config_mcp)
            
        # 2. Custom/internal servers (custom tools)
        existing_names = {s.get("name") for s in all_mcp_servers}
        for s in self.mcp_servers:
            if isinstance(s, dict) and s.get("name") not in existing_names:
                all_mcp_servers.append(s)
                
        # Convert to SDK format: dict[name, config]
        for server in all_mcp_servers:
            name = server.get("name")
            if not name:
                continue
            
            # SDK expects fields: type, command, args, env, cwd, tools, etc.
            # Our config matches this mostly (stdio type)
            sdk_config = {
                "type": server.get("type", "local"), # SDK uses 'local', our config uses 'stdio' or 'local'
            }
            if sdk_config["type"] == "stdio":
                 sdk_config["type"] = "local" # Map stdio -> local for SDK if needed? SDK docs say "local" or "stdio" are typically aliases in some libs, but SDK doc says "local" or "stdio".
                 
            if server.get("command"): sdk_config["command"] = server["command"]
            if server.get("args"): sdk_config["args"] = server["args"]
            if server.get("env"): sdk_config["env"] = server["env"]
            if server.get("cwd"): sdk_config["cwd"] = server["cwd"]
            if server.get("tools"): sdk_config["tools"] = server["tools"]
            else: sdk_config["tools"] = ["*"] # Default to all tools
            
            if server.get("type") == "http":
                sdk_config["type"] = "http"
                if server.get("url"): sdk_config["url"] = server["url"]
                if server.get("headers"): sdk_config["headers"] = server["headers"]

            mcp_servers_dict[name] = sdk_config

        # Prepare session config
        session_config = {
            "model": kwargs.get("model", "gpt-4"),
            "streaming": True,
            "mcp_servers": mcp_servers_dict
        }
        
        if system_message:
             # SDK expects SystemMessageAppendConfig or string? 
             # Based on copilot.py source it was {"mode": "append", "content": ...}
             # But SDK client.py creates session payload "systemMessage": ...
             # Let's use the explicit dict format if that's what worked, or just string.
             # client.py L451: payload["systemMessage"] = system_message
             session_config["system_message"] = system_message

        try:
            if session:
                # Reuse session
                # resume_session supports mcp_servers update
                session = await self.client.resume_session(session.session_id, session_config)
                self.sessions[agent_id] = session
            else:
                # Create session
                session = await self.client.create_session(session_config)
                self.sessions[agent_id] = session
        except Exception as e:
            yield StreamChunk(type="error", error=f"Session creation failed: {e}", source=agent_id)
            return

        def on_event(event):
            queue.put_nowait(event)

        unsubscribe = session.on(on_event)
        
        # Track seen event IDs to avoid processing replayed history
        seen_event_ids = set()
        accumulated_content = []
        # Workflow tools might be called via MCP now, we need to detect them
        # Logic: if message contains tool_calls to new_answer/vote, we flag it.
        workflow_tool_called = False
        
        try:
            # Send message
            await session.send({"prompt": prompt})
            
            # Event loop
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=300)
                except asyncio.TimeoutError:
                     yield StreamChunk(type="error", error="Response timeout", source=agent_id)
                     break
                
                # Check for completion
                event_type = event.type
                if hasattr(event_type, "value"):
                    event_type = event_type.value

                # Helper to get event ID
                event_id = getattr(event, "id", None)
                if event_id is not None:
                     if event_id in seen_event_ids:
                         continue
                     seen_event_ids.add(event_id)

                # Process event
                if event_type == "assistant.message_delta":
                    if hasattr(event, "data") and hasattr(event.data, "delta_content"):
                        content = event.data.delta_content
                        if content:
                            accumulated_content.append(content)
                            yield StreamChunk(type="content", content=content, source=agent_id)
                            
                elif event_type == "assistant.reasoning_delta":
                     if hasattr(event, "data") and hasattr(event.data, "delta_content"):
                        content = event.data.delta_content
                        if content:
                            yield StreamChunk(type="content", content=content, source=agent_id) # Treating reasoning as content for now? Or reasoning type? StreamChunk has reasoning_delta.
                            # yield StreamChunk(type="reasoning", reasoning_delta=content, source=agent_id) 

                elif event_type == "session.idle":
                    break
                    
                # Handle tool calls (if SDK exposes them as events)
                # Copilot SDK likely executes MCP tools and sends results back automatically.
                # However, for workflow tools (vote, new_answer), we might need to know they were called.
                # Does SDK emit tool call events?
                # Looking at client.py, "item.started", "item.completed", "tool_call", "tool_result"?
                # copilot.py previously used StreamChunk(type="tool_calls") manually.
                # If SDK handles tool execution, we might see the *result* or the *call*.
                
                # If we need to intercept vote/new_answer, we rely on the MCP server implementation of them.
                # The MCP execution of `vote`/`new_answer` (in custom_tools_server) will run.
                # But `new_answer` in MassGen typically means "we are done, here is the answer".
                # The orchestrator looks for `StreamChunk` with `tool_calls`.
                # If SDK hides the tool call and just does it, we miss the signal for Orchestrator.
                
                # However, `StreamChunk` with `tool_calls` is how Orchestrator knows a tool was called.
                # If SDK handles it internally, Orchestrator won't see it unless we emit it, OR unless "vote" / "new_answer"
                # acts as a termination signal.
                
                # Copilot SDK might have events for tool calls.
                # Let's inspect `event.type`.
                # If it's a tool call event, we can emit a StreamChunk.
                
                # Handle tool calls
                if "tool" in str(event_type).lower():
                    data = getattr(event, "data", None)
                    if data:
                        # Extract tool requests from data
                        # Data might have 'tool_requests' list or direct fields depending on event type
                        tool_calls_to_emit = []
                        
                        # Check for tool_requests list (most likely source for tool calls)
                        tool_requests = getattr(data, "tool_requests", None) or getattr(data, "toolRequests", None)
                        if tool_requests:
                            for tr in tool_requests:
                                # ToolRequest object or dict
                                tr_name = getattr(tr, "name", None) or tr.get("name")
                                tr_args = getattr(tr, "arguments", {}) or tr.get("arguments", {})
                                tr_id = getattr(tr, "tool_call_id", None) or tr.get("tool_call_id") or tr.get("toolCallId") or f"call-{uuid.uuid4()}"
                                
                                if tr_name:
                                    tool_calls_to_emit.append({
                                        "name": tr_name,
                                        "arguments": tr_args,
                                        "id": tr_id
                                    })

                        # Fallback: check direct fields (some events might have single tool info)
                        if not tool_calls_to_emit:
                            t_name = getattr(data, "tool_name", None) or getattr(data, "toolName", None) or getattr(data, "mcp_tool_name", None) or getattr(data, "mcpToolName", None)
                            if t_name:
                                t_args = getattr(data, "arguments", {})
                                t_id = getattr(data, "tool_call_id", None) or getattr(data, "toolCallId", None) or f"call-{uuid.uuid4()}"
                                tool_calls_to_emit.append({
                                    "name": t_name,
                                    "arguments": t_args,
                                    "id": t_id
                                })

                        # Emit tool calls
                        if tool_calls_to_emit:
                             yield StreamChunk(
                                type="tool_calls",
                                tool_calls=tool_calls_to_emit,
                                source=agent_id
                            )
                             
                             # Flag workflow tools
                             for tc in tool_calls_to_emit:
                                 if tc["name"] in ["new_answer", "vote"]:
                                     workflow_tool_called = True

        except Exception as e:
            yield StreamChunk(type="error", error=str(e), source=agent_id)
        finally:
            unsubscribe()
        
        # Fallback: synthesize new_answer if needed and NOT already called
        if not workflow_tool_called and accumulated_content:
             full_answer = "".join(accumulated_content)
             # Basic heuristic: if we have content, we treat it as an answer.
             
             yield StreamChunk(
                type="tool_calls",
                tool_calls=[{
                    "name": "new_answer",
                    "arguments": {"answer": full_answer},
                    "id": f"synth-{agent_id}",
                }],
                source=agent_id,
            )

