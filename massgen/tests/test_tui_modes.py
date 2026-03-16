#!/usr/bin/env python3
"""Tests for TUI mode state overrides."""

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "frontend" / "displays" / "tui_modes.py"
SPEC = importlib.util.spec_from_file_location("tui_modes_module", MODULE_PATH)
assert SPEC and SPEC.loader
TUI_MODES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TUI_MODES)
AnalysisConfig = TUI_MODES.AnalysisConfig
TuiModeState = TUI_MODES.TuiModeState


def test_default_coordination_mode_maps_to_voting_override() -> None:
    """Parallel UI mode should map to orchestrator voting mode."""
    state = TuiModeState()

    overrides = state.get_orchestrator_overrides()

    assert overrides["coordination_mode"] == "voting"


def test_decomposition_coordination_mode_maps_to_decomposition_override() -> None:
    """Decomposition UI mode should map directly to decomposition coordination."""
    state = TuiModeState(coordination_mode="decomposition")

    overrides = state.get_orchestrator_overrides()

    assert overrides["coordination_mode"] == "decomposition"


def test_coordination_override_coexists_with_refinement_overrides() -> None:
    """Coordination mode should not clobber existing quick-mode overrides."""
    state = TuiModeState(
        coordination_mode="decomposition",
        refinement_enabled=False,
        agent_mode="multi",
    )

    overrides = state.get_orchestrator_overrides()

    assert overrides["coordination_mode"] == "decomposition"
    assert overrides["max_new_answers_per_agent"] == 1
    assert overrides["skip_final_presentation"] is True
    assert overrides["disable_injection"] is True
    assert overrides["defer_voting_until_all_answered"] is True


def test_mode_summary_mentions_decomposition_only_when_active() -> None:
    """Mode summary should include decomposition only for non-default coordination mode."""
    default_summary = TuiModeState().get_mode_summary()
    decomp_summary = TuiModeState(coordination_mode="decomposition").get_mode_summary()

    assert "Coord: Decomposition" not in default_summary
    assert "Coord: Decomposition" in decomp_summary


def test_mode_summary_mentions_parallel_personas_when_enabled() -> None:
    """Mode summary should include parallel persona toggle when active."""
    summary = TuiModeState(
        coordination_mode="parallel",
        parallel_personas_enabled=True,
    ).get_mode_summary()

    assert "Personas: Perspective" in summary


def test_mode_summary_omits_parallel_personas_in_decomposition_mode() -> None:
    """Persona summary should not appear in decomposition mode."""
    summary = TuiModeState(
        coordination_mode="decomposition",
        parallel_personas_enabled=True,
    ).get_mode_summary()

    assert "Personas: ON" not in summary


def test_mode_summary_mentions_analysis_profile_when_active() -> None:
    """Analysis mode should include selected profile in mode summary."""
    state = TuiModeState(plan_mode="analysis")
    state.analysis_config.profile = "user"

    summary = state.get_mode_summary()

    assert "Analyze: User" in summary


def test_analysis_config_normalizes_enabled_skill_names() -> None:
    """Skill allowlist normalization should trim and deduplicate names."""
    config = AnalysisConfig(
        enabled_skill_names=[
            " skill-one ",
            "Skill-One",
            "",
            "skill-two",
        ],
    )

    assert config.get_enabled_skill_names() == ["skill-one", "skill-two"]
