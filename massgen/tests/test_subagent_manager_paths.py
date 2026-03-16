"""Regression tests for SubagentManager path handling."""

import asyncio
import time
from pathlib import Path

import pytest

from massgen.subagent.manager import SubagentManager
from massgen.subagent.models import SubagentConfig


class _FakeProcess:
    """Minimal fake process for subprocess call interception."""

    def __init__(self, returncode: int = 1, stdout: bytes = b"", stderr: bytes = b"forced error"):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self):
        return self._stdout, self._stderr


@pytest.mark.asyncio
async def test_execute_with_orchestrator_uses_absolute_paths(monkeypatch, tmp_path: Path):
    """Ensure subprocess launch uses absolute config/output paths when workspace is relative."""
    monkeypatch.chdir(tmp_path)

    manager = SubagentManager(
        parent_workspace="relative_parent_workspace",
        parent_agent_id="parent_a",
        orchestrator_id="orch_1",
        parent_agent_configs=[{"id": "parent_a", "backend": {"type": "codex", "model": "gpt-5.3-codex"}}],
    )

    workspace = manager._create_workspace("sub_a")
    (workspace / "CONTEXT.md").write_text("test context", encoding="utf-8")

    captured = {}

    async def _fake_create_subprocess_exec(*args, **kwargs):
        captured["args"] = list(args)
        captured["cwd"] = kwargs.get("cwd")
        return _FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create_subprocess_exec)

    config = SubagentConfig.create(
        task="test task",
        parent_agent_id="parent_a",
        subagent_id="sub_a",
        timeout_seconds=60,
    )

    result = await manager._execute_with_orchestrator(
        config=config,
        workspace=workspace,
        start_time=time.time(),
    )

    assert result.success is False
    assert captured["cwd"] == str(workspace.resolve())

    cmd = captured["args"]
    config_path = Path(cmd[cmd.index("--config") + 1])
    output_path = Path(cmd[cmd.index("--output-file") + 1])

    assert config_path.is_absolute()
    assert output_path.is_absolute()
    assert config_path.name == f"subagent_config_{config.id}.yaml"
    assert output_path.name == "answer.txt"
