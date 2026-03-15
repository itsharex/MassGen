"""Tests for round evaluator artifact resolution — specifically the
_candidate_artifact_paths method which must find critique_packet.md,
verdict.json, and next_tasks.json in various workspace layouts.

The critical case is when subagent_orchestrator is enabled: the round
evaluator runs as a multi-agent MassGen instance, so artifacts end up
in inner agent workspace directories like workspace/agent_<id>/critique_packet.md
rather than workspace/critique_packet.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Create a basic workspace directory."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


class TestCandidateArtifactPathsInnerAgent:
    """Test that _candidate_artifact_paths finds artifacts in inner agent dirs.

    When using subagent_orchestrator, the winning agent writes artifacts
    into workspace/agent_<hash>/ rather than workspace/.  The resolver
    MUST search this pattern.
    """

    def test_finds_artifact_in_inner_agent_directory(self, workspace: Path) -> None:
        """Artifact at workspace/agent_<id>/critique_packet.md must be found."""
        from massgen.subagent.models import RoundEvaluatorResult

        inner = workspace / "agent_2_03c1f747"
        inner.mkdir()
        packet = inner / "critique_packet.md"
        packet.write_text("# Critique\nNeeds improvement.", encoding="utf-8")

        candidates = RoundEvaluatorResult._candidate_artifact_paths(
            "critique_packet.md",
            workspace_path=str(workspace),
        )
        resolved_paths = {str(c.resolve()) for c in candidates}
        assert str(packet.resolve()) in resolved_paths, f"Expected to find {packet} in candidates, got: {candidates}"

    def test_finds_verdict_json_in_inner_agent_directory(self, workspace: Path) -> None:
        """verdict.json in inner agent dir must also be found."""
        from massgen.subagent.models import RoundEvaluatorResult

        inner = workspace / "agent_1_abc12345"
        inner.mkdir()
        verdict = inner / "verdict.json"
        verdict.write_text('{"verdict": "iterate", "scores": {}}', encoding="utf-8")

        candidates = RoundEvaluatorResult._candidate_artifact_paths(
            "verdict.json",
            workspace_path=str(workspace),
        )
        resolved_paths = {str(c.resolve()) for c in candidates}
        assert str(verdict.resolve()) in resolved_paths

    def test_prefers_root_over_inner_agent(self, workspace: Path) -> None:
        """If artifact exists at both root and inner agent dir, root wins."""
        from massgen.subagent.models import RoundEvaluatorResult

        # Root artifact
        root_packet = workspace / "critique_packet.md"
        root_packet.write_text("# Root critique", encoding="utf-8")

        # Inner agent artifact
        inner = workspace / "agent_1_abc12345"
        inner.mkdir()
        inner_packet = inner / "critique_packet.md"
        inner_packet.write_text("# Inner critique", encoding="utf-8")

        candidates = RoundEvaluatorResult._candidate_artifact_paths(
            "critique_packet.md",
            workspace_path=str(workspace),
        )
        assert len(candidates) >= 2
        # Root should come first (priority=0 vs priority=5)
        assert candidates[0].resolve() == root_packet.resolve()

    def test_multiple_inner_agents_picks_most_recent(self, workspace: Path) -> None:
        """When multiple inner agents have the artifact, most recent wins."""
        import time

        from massgen.subagent.models import RoundEvaluatorResult

        inner1 = workspace / "agent_1_aaa"
        inner1.mkdir()
        p1 = inner1 / "critique_packet.md"
        p1.write_text("Old critique", encoding="utf-8")

        time.sleep(0.05)  # Ensure different mtime

        inner2 = workspace / "agent_2_bbb"
        inner2.mkdir()
        p2 = inner2 / "critique_packet.md"
        p2.write_text("New critique", encoding="utf-8")

        candidates = RoundEvaluatorResult._candidate_artifact_paths(
            "critique_packet.md",
            workspace_path=str(workspace),
        )
        # Both should be found
        resolved = [str(c.resolve()) for c in candidates]
        assert str(p1.resolve()) in resolved
        assert str(p2.resolve()) in resolved
        # Most recent should come first (within same priority, sorted by -mtime)
        idx1 = resolved.index(str(p1.resolve()))
        idx2 = resolved.index(str(p2.resolve()))
        assert idx2 < idx1, "More recent artifact should come first"


class TestResolvePacketArtifactWithInnerAgent:
    """Integration test: from_subagent_result must find artifacts from inner agents."""

    def test_from_subagent_result_finds_inner_agent_critique(self, workspace: Path) -> None:
        """from_subagent_result must successfully find critique_packet.md
        in an inner agent directory and return status='success'."""
        from massgen.subagent.models import RoundEvaluatorResult, SubagentResult

        inner = workspace / "agent_2_winner"
        inner.mkdir()
        (inner / "critique_packet.md").write_text(
            "# Critique Packet\n\nThe answer needs edge case handling.",
            encoding="utf-8",
        )
        (inner / "verdict.json").write_text(
            '{"verdict": "iterate", "scores": {"E1": 7, "E2": 5}}',
            encoding="utf-8",
        )

        result = SubagentResult(
            subagent_id="round_eval_r2",
            status="partial",
            success=False,
            answer="Critique complete. Verdict: ITERATE.",
            workspace_path=str(workspace),
            execution_time_seconds=300.0,
            error="Subagent exceeded timeout",
        )

        evaluator_result = RoundEvaluatorResult.from_subagent_result(result, elapsed=300.0)
        assert evaluator_result.status == "success", (
            f"Expected status='success' but got '{evaluator_result.status}'. " f"Error: {evaluator_result.error}. " f"Packet text: {evaluator_result.packet_text}"
        )
        assert evaluator_result.packet_text is not None
        assert "edge case" in evaluator_result.packet_text
        assert evaluator_result.verdict == "iterate"


class TestMaxLaunchFailures:
    """Test that _ROUND_EVALUATOR_MAX_LAUNCH_FAILURES allows at least one retry."""

    def test_max_failures_allows_retry(self) -> None:
        """The max launch failures constant must be > 1 to allow at least one retry."""
        from massgen.orchestrator import Orchestrator

        assert Orchestrator._ROUND_EVALUATOR_MAX_LAUNCH_FAILURES > 1, (
            f"_ROUND_EVALUATOR_MAX_LAUNCH_FAILURES is {Orchestrator._ROUND_EVALUATOR_MAX_LAUNCH_FAILURES}. "
            "With value 1, the first failure is immediately terminal (attempt_number=1, 1<1 is False). "
            "Must be > 1 to allow retries."
        )
