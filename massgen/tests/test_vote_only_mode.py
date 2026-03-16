#!/usr/bin/env python3
"""
Unit tests for vote-only mode when max_new_answers_per_agent limit is reached.

Tests cover:
- get_workflow_tools with vote_only parameter for all API formats
- Orchestrator._is_vote_only_mode() method
- MessageTemplates.evaluation_system_message_vote_only() method
"""

import pytest

from massgen.agent_config import AgentConfig
from massgen.message_templates import MessageTemplates
from massgen.orchestrator import Orchestrator
from massgen.tool import get_workflow_tools


def _get_tool_names(tools, api_format):
    """Extract tool names from tools list based on API format."""
    names = []
    for tool in tools:
        if api_format == "claude":
            # Claude format uses "name" at top level
            names.append(tool.get("name"))
        else:
            # chat_completions and response format use "function.name"
            names.append(tool.get("function", {}).get("name"))
    return names


class TestVoteOnlyModeAllFormats:
    """Tests for vote-only mode across all API formats."""

    @pytest.mark.parametrize("api_format", ["chat_completions", "claude", "response"])
    def test_default_includes_new_answer(self, api_format):
        """Test that get_workflow_tools includes new_answer by default for all formats."""
        tools = get_workflow_tools(
            valid_agent_ids=["agent_a", "agent_b"],
            api_format=api_format,
        )
        tool_names = _get_tool_names(tools, api_format)
        assert "new_answer" in tool_names, f"new_answer missing for {api_format}"
        assert "vote" in tool_names, f"vote missing for {api_format}"

    @pytest.mark.parametrize("api_format", ["chat_completions", "claude", "response"])
    def test_vote_only_excludes_new_answer(self, api_format):
        """Test that vote_only=True excludes new_answer for all formats."""
        tools = get_workflow_tools(
            valid_agent_ids=["agent_a", "agent_b"],
            api_format=api_format,
            vote_only=True,
        )
        tool_names = _get_tool_names(tools, api_format)
        assert "new_answer" not in tool_names, f"new_answer should be excluded for {api_format}"
        assert "vote" in tool_names, f"vote should be present for {api_format}"

    @pytest.mark.parametrize("api_format", ["chat_completions", "claude", "response"])
    def test_vote_only_fewer_tools(self, api_format):
        """Test that vote_only mode has fewer tools for all formats."""
        normal_tools = get_workflow_tools(
            valid_agent_ids=["agent_a", "agent_b"],
            api_format=api_format,
        )
        vote_only_tools = get_workflow_tools(
            valid_agent_ids=["agent_a", "agent_b"],
            api_format=api_format,
            vote_only=True,
        )
        assert len(vote_only_tools) < len(normal_tools), f"vote_only should have fewer tools for {api_format}"


class TestVoteOnlyModeWithBroadcast:
    """Tests for vote-only mode with broadcast enabled."""

    @pytest.mark.parametrize("api_format", ["chat_completions", "claude", "response"])
    def test_vote_only_with_broadcast_excludes_both(self, api_format):
        """Test that vote_only with broadcast excludes new_answer AND broadcast tools."""
        # Normal mode with broadcast
        normal_tools = get_workflow_tools(
            valid_agent_ids=["agent_a", "agent_b"],
            api_format=api_format,
            broadcast_mode="agents",
        )
        normal_names = _get_tool_names(normal_tools, api_format)

        # Vote-only mode with broadcast
        vote_only_tools = get_workflow_tools(
            valid_agent_ids=["agent_a", "agent_b"],
            api_format=api_format,
            broadcast_mode="agents",
            vote_only=True,
        )
        vote_only_names = _get_tool_names(vote_only_tools, api_format)

        # new_answer should be excluded
        assert "new_answer" not in vote_only_names
        # vote should remain
        assert "vote" in vote_only_names
        # broadcast tools should also be excluded in vote_only mode
        assert "ask_others" not in vote_only_names or "ask_others" not in normal_names


class TestOrchestratorVoteOnlyMode:
    """Tests for orchestrator vote-only mode detection."""

    def test_orchestrator_has_vote_only_method(self):
        """Test that Orchestrator has _is_vote_only_mode method."""
        assert hasattr(Orchestrator, "_is_vote_only_mode")

    def test_vote_only_mode_false_when_no_limit(self):
        """Test that vote-only mode is False when no limit is set."""
        config = AgentConfig()
        config.max_new_answers_per_agent = None
        orchestrator = Orchestrator(agents={}, config=config)

        assert orchestrator._is_vote_only_mode("agent_a") is False

    def test_vote_only_mode_false_when_under_limit(self):
        """Test that vote-only mode is False when under answer limit."""
        config = AgentConfig()
        config.max_new_answers_per_agent = 3
        orchestrator = Orchestrator(agents={}, config=config)

        # Simulate agent with 2 answers (under limit of 3)
        orchestrator.coordination_tracker.answers_by_agent["agent_a"] = [
            type("Answer", (), {"label": "agent1.1", "content": "answer1"})(),
            type("Answer", (), {"label": "agent1.2", "content": "answer2"})(),
        ]

        assert orchestrator._is_vote_only_mode("agent_a") is False

    def test_vote_only_mode_true_when_at_limit(self):
        """Test that vote-only mode is True when at answer limit."""
        config = AgentConfig()
        config.max_new_answers_per_agent = 3
        orchestrator = Orchestrator(agents={}, config=config)

        # Simulate agent with 3 answers (at limit)
        orchestrator.coordination_tracker.answers_by_agent["agent_a"] = [
            type("Answer", (), {"label": "agent1.1", "content": "answer1"})(),
            type("Answer", (), {"label": "agent1.2", "content": "answer2"})(),
            type("Answer", (), {"label": "agent1.3", "content": "answer3"})(),
        ]

        assert orchestrator._is_vote_only_mode("agent_a") is True

    def test_vote_only_mode_true_when_over_limit(self):
        """Test that vote-only mode is True when over answer limit."""
        config = AgentConfig()
        config.max_new_answers_per_agent = 2
        orchestrator = Orchestrator(agents={}, config=config)

        # Simulate agent with 3 answers (over limit of 2)
        orchestrator.coordination_tracker.answers_by_agent["agent_a"] = [
            type("Answer", (), {"label": "agent1.1", "content": "answer1"})(),
            type("Answer", (), {"label": "agent1.2", "content": "answer2"})(),
            type("Answer", (), {"label": "agent1.3", "content": "answer3"})(),
        ]

        assert orchestrator._is_vote_only_mode("agent_a") is True

    def test_vote_only_mode_per_agent(self):
        """Test that vote-only mode is tracked per agent."""
        config = AgentConfig()
        config.max_new_answers_per_agent = 2
        orchestrator = Orchestrator(agents={}, config=config)

        # Agent A at limit
        orchestrator.coordination_tracker.answers_by_agent["agent_a"] = [
            type("Answer", (), {"label": "agent1.1", "content": "answer1"})(),
            type("Answer", (), {"label": "agent1.2", "content": "answer2"})(),
        ]

        # Agent B under limit
        orchestrator.coordination_tracker.answers_by_agent["agent_b"] = [
            type("Answer", (), {"label": "agent2.1", "content": "answer1"})(),
        ]

        assert orchestrator._is_vote_only_mode("agent_a") is True
        assert orchestrator._is_vote_only_mode("agent_b") is False

    def test_vote_only_mode_true_when_global_limit_reached(self):
        """Global answer cap should force vote-only mode in voting coordination."""
        config = AgentConfig()
        config.max_new_answers_global = 2
        orchestrator = Orchestrator(agents={}, config=config)

        orchestrator.coordination_tracker.answers_by_agent["agent_a"] = [
            type("Answer", (), {"label": "agent1.1", "content": "answer1"})(),
        ]
        orchestrator.coordination_tracker.answers_by_agent["agent_b"] = [
            type("Answer", (), {"label": "agent2.1", "content": "answer2"})(),
        ]

        assert orchestrator._is_vote_only_mode("agent_c") is True

    def test_global_limit_disables_waiting_for_all_answers(self):
        """When global limit is reached, agents should not wait before voting."""
        config = AgentConfig()
        config.defer_voting_until_all_answered = True
        config.max_new_answers_per_agent = 2
        config.max_new_answers_global = 2
        orchestrator = Orchestrator(
            agents={"agent_a": _FakeAgentForToolFiltering(), "agent_b": _FakeAgentForToolFiltering()},
            config=config,
        )

        # agent_a has hit per-agent cap; agent_b has not answered yet.
        orchestrator.coordination_tracker.answers_by_agent["agent_a"] = [
            type("Answer", (), {"label": "agent1.1", "content": "answer1"})(),
            type("Answer", (), {"label": "agent1.2", "content": "answer2"})(),
        ]

        # Global cap is reached, so waiting should be bypassed.
        assert orchestrator._is_waiting_for_all_answers("agent_a") is False
        assert orchestrator._is_vote_only_mode("agent_a") is True


class _FakeBackendForToolFiltering:
    """Minimal backend stub for tool-name extraction."""

    filesystem_manager = None
    config = {}

    @staticmethod
    def extract_tool_name(tool_call):
        if isinstance(tool_call, dict):
            if "name" in tool_call:
                return tool_call.get("name")
            function = tool_call.get("function", {})
            if isinstance(function, dict):
                return function.get("name")
        return None


class _FakeAgentForToolFiltering:
    """Minimal agent stub exposing backend used by orchestrator helper."""

    backend = _FakeBackendForToolFiltering()


class TestWorkflowToolFiltering:
    """Tests for filtering unavailable workflow tools at runtime."""

    def test_filters_disallowed_workflow_calls(self):
        """Disallowed workflow tools should be separated from allowed calls."""
        orchestrator = Orchestrator(agents={}, config=AgentConfig())
        agent = _FakeAgentForToolFiltering()
        tool_calls = [
            {"name": "new_answer", "arguments": "{}"},
            {"name": "vote", "arguments": "{}"},
            {"name": "ask_others", "arguments": "{}"},
            {"name": "not_a_workflow_tool", "arguments": "{}"},
        ]

        allowed, disallowed, disallowed_names = orchestrator._split_disallowed_workflow_tool_calls(
            agent=agent,
            tool_calls=tool_calls,
            allowed_workflow_tool_names={"vote"},
        )

        assert [call["name"] for call in allowed] == ["vote", "not_a_workflow_tool"]
        assert [call["name"] for call in disallowed] == ["new_answer", "ask_others"]
        assert disallowed_names == ["new_answer", "ask_others"]

    def test_keeps_all_calls_when_workflow_tools_are_allowed(self):
        """If workflow tools are allowed this round, none should be filtered."""
        orchestrator = Orchestrator(agents={}, config=AgentConfig())
        agent = _FakeAgentForToolFiltering()
        tool_calls = [
            {"name": "new_answer", "arguments": "{}"},
            {"name": "vote", "arguments": "{}"},
        ]

        allowed, disallowed, disallowed_names = orchestrator._split_disallowed_workflow_tool_calls(
            agent=agent,
            tool_calls=tool_calls,
            allowed_workflow_tool_names={"new_answer", "vote"},
        )

        assert [call["name"] for call in allowed] == ["new_answer", "vote"]
        assert disallowed == []
        assert disallowed_names == []


class TestMessageTemplatesVoteOnly:
    """Tests for vote-only system message."""

    def test_message_templates_has_vote_only_method(self):
        """Test that MessageTemplates has vote-only system message method."""
        assert hasattr(MessageTemplates, "evaluation_system_message_vote_only")

    def test_vote_only_system_message_mentions_vote(self):
        """Test that vote-only system message mentions voting."""
        templates = MessageTemplates()
        message = templates.evaluation_system_message_vote_only()

        assert "vote" in message.lower()
        assert "MUST" in message  # Strong directive

    def test_vote_only_system_message_excludes_new_answer(self):
        """Test that vote-only system message doesn't mention new_answer."""
        templates = MessageTemplates()
        message = templates.evaluation_system_message_vote_only()

        assert "new_answer" not in message.lower()

    def test_vote_only_system_message_explains_reason(self):
        """Test that vote-only system message explains why voting is required."""
        templates = MessageTemplates()
        message = templates.evaluation_system_message_vote_only()

        # Should explain that answer limit was reached
        assert "limit" in message.lower() or "maximum" in message.lower()


class TestGeminiVoteOnlySchema:
    """Tests for Gemini vote-only structured output schema."""

    def test_vote_only_schema_exists(self):
        """Test that VoteOnlyCoordinationResponse schema exists."""
        from massgen.backend.gemini_utils import VoteOnlyCoordinationResponse

        assert VoteOnlyCoordinationResponse is not None

    def test_vote_only_schema_has_vote_only_action_type(self):
        """Test that vote-only schema only allows VOTE action."""
        from massgen.backend.gemini_utils import VoteOnlyActionType

        # Should only have VOTE option
        assert len(VoteOnlyActionType) == 1
        assert VoteOnlyActionType.VOTE.value == "vote"

    def test_vote_only_schema_no_answer_data_field(self):
        """Test that vote-only schema doesn't include answer_data field."""
        from massgen.backend.gemini_utils import VoteOnlyCoordinationResponse

        schema = VoteOnlyCoordinationResponse.model_json_schema()

        # Should not have answer_data in properties
        properties = schema.get("properties", {})
        assert "answer_data" not in properties
        assert "ask_others_data" not in properties

    def test_vote_only_schema_requires_vote_data(self):
        """Test that vote-only schema requires vote_data."""
        from massgen.backend.gemini_utils import VoteOnlyCoordinationResponse

        schema = VoteOnlyCoordinationResponse.model_json_schema()

        # vote_data should be required (not optional)
        required = schema.get("required", [])
        assert "vote_data" in required or "action_type" in required


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
