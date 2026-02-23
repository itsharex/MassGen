"""Tests for SubagentManager.cancel_subagent() internal method."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from massgen.subagent.models import SubagentConfig, SubagentState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manager(tmp_path: Path):
    """Create a SubagentManager with minimal dependencies."""
    from massgen.subagent.manager import SubagentManager

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = SubagentManager(
        parent_workspace=str(workspace),
        parent_agent_id="parent-1",
        orchestrator_id="orch-1",
        parent_agent_configs=[{"id": "agent-1", "backend": "mock"}],
    )
    return manager


def _make_state(
    subagent_id: str,
    status: str = "running",
    task: str = "test task",
) -> SubagentState:
    """Create a SubagentState for testing."""
    config = SubagentConfig(
        id=subagent_id,
        task=task,
        parent_agent_id="parent-1",
    )
    return SubagentState(
        config=config,
        status=status,
        workspace_path="/tmp/test",
        started_at=datetime.now(),
    )


# ---------------------------------------------------------------------------
# cancel_subagent tests
# ---------------------------------------------------------------------------


class TestCancelSubagent:
    @pytest.mark.asyncio
    async def test_cancel_unknown_id_returns_error(self, tmp_path):
        manager = _make_manager(tmp_path)

        result = await manager.cancel_subagent("nonexistent-id")
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_cancel_terminal_state_returns_error(self, tmp_path):
        """Cannot cancel a subagent that's already completed/failed."""
        manager = _make_manager(tmp_path)
        state = _make_state("sub-1", status="completed")
        manager._subagents["sub-1"] = state

        result = await manager.cancel_subagent("sub-1")
        assert result["success"] is False
        assert "already" in result["error"].lower() or "terminal" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_cancel_cancels_asyncio_task(self, tmp_path):
        manager = _make_manager(tmp_path)
        state = _make_state("sub-1", status="running")
        manager._subagents["sub-1"] = state

        mock_task = MagicMock()
        mock_task.done.return_value = False
        mock_task.cancel.return_value = True
        manager._background_tasks["sub-1"] = mock_task

        result = await manager.cancel_subagent("sub-1")
        assert result["success"] is True
        mock_task.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_terminates_process(self, tmp_path):
        manager = _make_manager(tmp_path)
        state = _make_state("sub-1", status="running")
        manager._subagents["sub-1"] = state

        mock_process = AsyncMock()
        mock_process.returncode = None  # Still running
        mock_process.terminate = MagicMock()
        mock_process.wait = AsyncMock()
        mock_process.kill = MagicMock()
        manager._active_processes["sub-1"] = mock_process

        result = await manager.cancel_subagent("sub-1")
        assert result["success"] is True
        mock_process.terminate.assert_called_once()
        assert state.status == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_kills_on_timeout(self, tmp_path):
        """If terminate doesn't work within timeout, SIGKILL should be used."""
        manager = _make_manager(tmp_path)
        state = _make_state("sub-1", status="running")
        manager._subagents["sub-1"] = state

        mock_process = AsyncMock()
        mock_process.returncode = None
        mock_process.terminate = MagicMock()
        # Simulate timeout on first wait, then succeed on second
        mock_process.wait = AsyncMock(side_effect=[asyncio.TimeoutError(), None])
        mock_process.kill = MagicMock()
        manager._active_processes["sub-1"] = mock_process

        result = await manager.cancel_subagent("sub-1")
        assert result["success"] is True
        mock_process.kill.assert_called_once()
        assert state.status == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_sets_status_to_cancelled(self, tmp_path):
        manager = _make_manager(tmp_path)
        state = _make_state("sub-1", status="running")
        manager._subagents["sub-1"] = state

        result = await manager.cancel_subagent("sub-1")
        assert result["success"] is True
        assert state.status == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_already_finished_process(self, tmp_path):
        """Process already exited but state still says running."""
        manager = _make_manager(tmp_path)
        state = _make_state("sub-1", status="running")
        manager._subagents["sub-1"] = state

        mock_process = AsyncMock()
        mock_process.returncode = 0  # Already exited
        manager._active_processes["sub-1"] = mock_process

        result = await manager.cancel_subagent("sub-1")
        assert result["success"] is True
        assert state.status == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_pending_state(self, tmp_path):
        """Can cancel a pending subagent."""
        manager = _make_manager(tmp_path)
        state = _make_state("sub-1", status="pending")
        manager._subagents["sub-1"] = state

        result = await manager.cancel_subagent("sub-1")
        assert result["success"] is True
        assert state.status == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_freezes_elapsed_seconds(self, tmp_path):
        """Cancelled subagents should report a stable elapsed time in display data."""
        manager = _make_manager(tmp_path)
        state = _make_state("sub-1", status="running")
        state.started_at = datetime.now() - timedelta(seconds=5)
        manager._subagents["sub-1"] = state

        result = await manager.cancel_subagent("sub-1")
        assert result["success"] is True
        assert state.finished_at is not None

        first_elapsed = manager.get_subagent_display_data("sub-1").elapsed_seconds
        await asyncio.sleep(0.01)
        second_elapsed = manager.get_subagent_display_data("sub-1").elapsed_seconds

        assert second_elapsed == first_elapsed

    @pytest.mark.asyncio
    async def test_cancel_sets_result_error_for_display_reason(self, tmp_path):
        """Cancelled subagents should carry a displayable terminal reason."""
        manager = _make_manager(tmp_path)
        state = _make_state("sub-1", status="running")
        state.started_at = datetime.now() - timedelta(seconds=3)
        manager._subagents["sub-1"] = state

        result = await manager.cancel_subagent("sub-1")
        assert result["success"] is True
        assert state.result is not None
        assert state.result.error == "Subagent cancelled"

    @pytest.mark.asyncio
    async def test_list_subagents_reports_cancelled_after_cancel(self, tmp_path):
        """list_subagents should preserve cancelled status instead of downgrading to error."""
        manager = _make_manager(tmp_path)
        state = _make_state("sub-1", status="running")
        manager._subagents["sub-1"] = state

        cancelled = await manager.cancel_subagent("sub-1")
        assert cancelled["success"] is True

        listed = manager.list_subagents()
        assert listed
        assert listed[0]["subagent_id"] == "sub-1"
        assert listed[0]["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_background_cancel_not_overwritten_by_timeout_result(self, tmp_path, monkeypatch):
        """Background runner must preserve cancelled state/result when cancellation races timeout handling."""
        manager = _make_manager(tmp_path)
        (Path(manager.parent_workspace) / "CONTEXT.md").write_text("# Context\ncancel test\n")

        started = asyncio.Event()

        async def _fake_execute_subagent(config, workspace):  # noqa: ANN001 - monkeypatch target signature
            started.set()
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                # Mirror real _execute_subagent behavior that converts cancellation
                # into a timeout-style result payload.
                return manager._create_timeout_result_with_recovery(
                    subagent_id=config.id,
                    workspace=workspace,
                    timeout_seconds=10.0,
                )

        monkeypatch.setattr(manager, "_execute_subagent", _fake_execute_subagent)

        spawned = manager.spawn_subagent_background(
            task="long running task",
            subagent_id="sub-1",
            timeout_seconds=10.0,
        )
        assert spawned["status"] == "running"

        await asyncio.wait_for(started.wait(), timeout=1.0)
        cancelled = await manager.cancel_subagent("sub-1")
        assert cancelled["success"] is True
        assert cancelled["status"] == "cancelled"

        await manager.wait_for_subagent("sub-1", timeout=2.0)

        state = manager._subagents["sub-1"]
        assert state.status == "cancelled"
        assert state.result is not None
        assert state.result.error == "Subagent cancelled"

        listed = manager.list_subagents()
        assert listed
        assert listed[0]["subagent_id"] == "sub-1"
        assert listed[0]["status"] == "cancelled"
