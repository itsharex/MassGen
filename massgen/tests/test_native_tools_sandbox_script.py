"""Tests for scripts/test_native_tools_sandbox.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "test_native_tools_sandbox.py"
SPEC = importlib.util.spec_from_file_location("test_native_tools_sandbox_script_module", MODULE_PATH)
assert SPEC and SPEC.loader
SANDBOX_SCRIPT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SANDBOX_SCRIPT)


@pytest.mark.parametrize(
    ("backend_type", "requested_runner", "expected_runner"),
    [
        ("claude_code", "auto", "direct"),
        ("codex", "auto", "direct"),
        ("copilot", "auto", "orchestrator"),
        ("gemini_cli", "auto", "orchestrator"),
        ("copilot", "direct", "direct"),
        ("gemini_cli", "orchestrator", "orchestrator"),
    ],
)
def test_resolve_runner(backend_type: str, requested_runner: str, expected_runner: str) -> None:
    """Auto mode should choose the realistic runner per backend."""
    assert SANDBOX_SCRIPT.resolve_runner(backend_type, requested_runner) == expected_runner


def test_build_orchestrator_runner_uses_single_agent_quick_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Orchestrator runner should use a single-agent, presentation-free config."""
    captured: dict[str, object] = {}
    backend = SimpleNamespace(model="test-model")

    def fake_configurable_agent(*, config, backend):
        captured["agent_config"] = config
        captured["agent_backend"] = backend
        return SimpleNamespace(agent_id=config.agent_id, backend=backend)

    def fake_create_orchestrator(agents, **kwargs):
        captured["agents"] = agents
        captured["orchestrator_config"] = kwargs.get("config")
        return "fake-orchestrator"

    monkeypatch.setattr(SANDBOX_SCRIPT, "ConfigurableAgent", fake_configurable_agent)
    monkeypatch.setattr(SANDBOX_SCRIPT, "create_orchestrator", fake_create_orchestrator)

    orchestrator = SANDBOX_SCRIPT.build_orchestrator_runner(backend)

    assert orchestrator == "fake-orchestrator"
    assert captured["agent_backend"] is backend
    assert captured["agents"] == [("sandbox_agent", SimpleNamespace(agent_id="sandbox_agent", backend=backend))]

    agent_config = captured["agent_config"]
    assert agent_config.agent_id == "sandbox_agent"
    assert agent_config.backend_params["model"] == "test-model"

    orchestrator_config = captured["orchestrator_config"]
    assert orchestrator_config.skip_voting is True
    assert orchestrator_config.skip_final_presentation is True
    assert orchestrator_config.max_new_answers_per_agent == 1
    assert orchestrator_config.final_answer_strategy == "winner_reuse"
    assert orchestrator_config.coordination_config.write_mode == "legacy"


@pytest.mark.asyncio
async def test_run_agent_task_dispatches_to_orchestrator_runner(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """SandboxTester should route execution through the orchestrator helper when selected."""
    workspace = tmp_path / "workspace"
    writable = tmp_path / "writable"
    readonly = tmp_path / "readonly"
    outside = tmp_path / "outside"
    for path in (workspace, writable, readonly, outside):
        path.mkdir()

    tester = SANDBOX_SCRIPT.SandboxTester(
        workspace,
        writable,
        readonly,
        outside,
        tmp_path,
        runner_type="orchestrator",
    )

    fake_backend = object()

    monkeypatch.setattr(tester, "create_backend", lambda: fake_backend)

    async def fake_run_with_orchestrator(prompt, backend):
        assert prompt == "Read something"
        assert backend is fake_backend
        return "orchestrated-response"

    async def fake_run_with_direct_backend(prompt, backend):
        raise AssertionError("direct backend path should not be used")

    monkeypatch.setattr(tester, "_run_with_orchestrator", fake_run_with_orchestrator)
    monkeypatch.setattr(tester, "_run_with_direct_backend", fake_run_with_direct_backend)

    response = await tester.run_agent_task("Read something")

    assert response == "orchestrated-response"
