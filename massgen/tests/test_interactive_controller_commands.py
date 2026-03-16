"""Tests for slash command dispatch behavior."""

from massgen.frontend.interactive_controller import (
    SessionContext,
    SlashCommandDispatcher,
)


def _make_dispatcher() -> SlashCommandDispatcher:
    """Create a dispatcher with a minimal context for command-only tests."""
    return SlashCommandDispatcher(context=SessionContext(), adapter=None)  # type: ignore[arg-type]


def test_skills_command_dispatches_show_skills_action() -> None:
    """/skills should route to the skills modal action."""
    result = _make_dispatcher().dispatch("/skills")

    assert result.handled is True
    assert result.ui_action == "show_skills"


def test_skills_alias_dispatches_show_skills_action() -> None:
    """/k alias should route to the same skills action."""
    result = _make_dispatcher().dispatch("/k")

    assert result.handled is True
    assert result.ui_action == "show_skills"


def test_help_text_mentions_skills_command() -> None:
    """Canonical help output should document /skills."""
    help_text = SlashCommandDispatcher.build_help_text()

    assert "/skills, /k" in help_text
