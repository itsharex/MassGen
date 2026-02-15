# -*- coding: utf-8 -*-
"""Unit tests for FinalAnswerModal — the tabbed final answer + review changes modal."""


from massgen.filesystem_manager import ReviewResult
from massgen.frontend.displays.textual.widgets.modals.final_answer_modal import (
    AnswerTabContent,
    FinalAnswerModal,
    FinalAnswerModalData,
)
from massgen.frontend.displays.textual.widgets.modals.review_changes_panel import (
    ReviewChangesPanel,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_DIFF = """\
diff --git a/src/app.py b/src/app.py
index abc1234..def5678 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,4 +1,5 @@
 import os
+import sys

 def main():
     pass
@@ -10,3 +11,3 @@ def helper():
-    return False
+    return True
     # end
"""

MOCK_ANSWER = """\
# Implementation Summary

## Changes Made

1. Added `import sys` to support CLI arguments
2. Fixed `helper()` to return True instead of False
3. Updated configuration defaults

## Testing

All tests pass with the new implementation.
"""

MOCK_VOTES = {
    "winner": "agent_a",
    "vote_counts": {"agent_a": 2, "agent_b": 1},
    "is_tie": False,
}

MOCK_VOTES_TIE = {
    "winner": "agent_a",
    "vote_counts": {"agent_a": 1, "agent_b": 1},
    "is_tie": True,
}

MOCK_POST_EVAL = "All criteria met. Code quality verified."

MOCK_CONTEXT_PATHS = {
    "new": ["src/new_file.py"],
    "modified": ["src/app.py", "src/config.py"],
}


def _make_changes() -> list:
    return [
        {
            "original_path": "/project",
            "isolated_path": "/tmp/worktree",
            "changes": [
                {"status": "M", "path": "src/app.py"},
            ],
            "diff": SAMPLE_DIFF,
        },
    ]


_SENTINEL = object()


def _make_data(
    *,
    answer: str = MOCK_ANSWER,
    votes: dict | None | object = _SENTINEL,
    post_eval: str | None = None,
    changes: list | None = None,
    context_paths: dict | None = None,
) -> FinalAnswerModalData:
    return FinalAnswerModalData(
        answer_content=answer,
        vote_results=MOCK_VOTES if votes is _SENTINEL else (votes or {}),
        agent_id="agent_a",
        model_name="claude-sonnet-4-5-20250929",
        post_eval_content=post_eval,
        post_eval_status="verified" if post_eval else "none",
        changes=changes,
        context_paths=context_paths,
    )


# ---------------------------------------------------------------------------
# FinalAnswerModalData construction
# ---------------------------------------------------------------------------


class TestFinalAnswerModalData:
    def test_defaults(self):
        data = FinalAnswerModalData(answer_content="hello")
        assert data.answer_content == "hello"
        assert data.vote_results == {}
        assert data.agent_id == ""
        assert data.changes is None
        assert data.post_eval_status == "none"

    def test_with_all_fields(self):
        changes = _make_changes()
        data = _make_data(changes=changes, post_eval=MOCK_POST_EVAL, context_paths=MOCK_CONTEXT_PATHS)
        assert data.answer_content == MOCK_ANSWER
        assert data.changes == changes
        assert data.post_eval_content == MOCK_POST_EVAL
        assert data.post_eval_status == "verified"


# ---------------------------------------------------------------------------
# AnswerTabContent
# ---------------------------------------------------------------------------


class TestHeaderTitle:
    def test_header_with_votes(self):
        """Header should include winner and vote info."""
        data = _make_data()
        modal = FinalAnswerModal(data=data)
        title = modal._build_header_title()
        assert "Final Answer" in title
        assert "Winner: agent_a" in title
        assert "2 votes" in title
        assert "Votes:" in title

    def test_header_no_votes(self):
        """Header with no votes should just say 'Final Answer'."""
        data = _make_data(votes={})
        modal = FinalAnswerModal(data=data)
        title = modal._build_header_title()
        assert title == "Final Answer"

    def test_header_tie(self):
        """Header should show tie-breaker info."""
        data = _make_data(votes=MOCK_VOTES_TIE)
        modal = FinalAnswerModal(data=data)
        title = modal._build_header_title()
        assert "tie-breaker" in title
        assert "Votes:" in title


class TestAnswerTabContent:
    def test_winner_summary(self):
        data = _make_data()
        tab = AnswerTabContent(data=data)
        summary = tab._build_winner_summary()
        assert "agent_a" in summary
        assert "2 votes" in summary

    def test_winner_summary_tie(self):
        data = _make_data(votes=MOCK_VOTES_TIE)
        tab = AnswerTabContent(data=data)
        summary = tab._build_winner_summary()
        assert "tie-breaker" in summary

    def test_winner_summary_no_votes(self):
        data = _make_data(votes={})
        tab = AnswerTabContent(data=data)
        summary = tab._build_winner_summary()
        assert summary == ""

    def test_vote_summary(self):
        data = _make_data()
        tab = AnswerTabContent(data=data)
        summary = tab._build_vote_summary()
        assert "agent_a (2)" in summary
        assert "agent_b (1)" in summary

    def test_vote_summary_no_votes(self):
        data = _make_data(votes={})
        tab = AnswerTabContent(data=data)
        summary = tab._build_vote_summary()
        assert summary == ""


# ---------------------------------------------------------------------------
# FinalAnswerModal construction
# ---------------------------------------------------------------------------


class TestFinalAnswerModalConstruction:
    def test_answer_only_no_panel(self):
        """No changes → no ReviewChangesPanel."""
        data = _make_data(changes=None)
        modal = FinalAnswerModal(data=data)
        assert modal._panel is None

    def test_with_changes_creates_panel(self):
        """With changes → ReviewChangesPanel is created."""
        data = _make_data(changes=_make_changes())
        modal = FinalAnswerModal(data=data)
        assert modal._panel is not None
        assert isinstance(modal._panel, ReviewChangesPanel)

    def test_panel_has_correct_file_count(self):
        """Panel should track the files from changes."""
        data = _make_data(changes=_make_changes())
        modal = FinalAnswerModal(data=data)
        assert len(modal._panel._all_file_paths) == 1


# ---------------------------------------------------------------------------
# Dismiss behavior
# ---------------------------------------------------------------------------


class TestDismissBehavior:
    def _capture_dismiss(self, modal):
        captured = {}
        modal.dismiss = lambda result: captured.update({"result": result})
        return captured

    def test_close_from_answer_approves_all(self):
        """Closing from answer tab should approve all changes."""
        data = _make_data(changes=_make_changes())
        modal = FinalAnswerModal(data=data)
        captured = self._capture_dismiss(modal)
        modal._close_with_approve_all()
        result = captured["result"]
        assert isinstance(result, ReviewResult)
        assert result.approved is True
        assert result.approved_files is None
        assert result.metadata["selection_mode"] == "all"

    def test_close_no_changes_approves_all(self):
        """Closing with no changes should still return approved=True."""
        data = _make_data(changes=None)
        modal = FinalAnswerModal(data=data)
        captured = self._capture_dismiss(modal)
        modal._close_with_approve_all()
        result = captured["result"]
        assert result.approved is True

    def test_esc_action_approves_all(self):
        """ESC action should approve all."""
        data = _make_data(changes=_make_changes())
        modal = FinalAnswerModal(data=data)
        captured = self._capture_dismiss(modal)
        modal.action_close_modal()
        result = captured["result"]
        assert result.approved is True


# ---------------------------------------------------------------------------
# Panel integration
# ---------------------------------------------------------------------------


class TestPanelIntegration:
    def test_panel_action_approve_selected(self):
        """Panel's approve_selected action should result in dismiss."""
        data = _make_data(changes=_make_changes())
        modal = FinalAnswerModal(data=data)
        captured = {}
        modal.dismiss = lambda result: captured.update({"result": result})

        # Simulate panel emitting ActionRequested
        result = modal._panel.get_review_result("approve")
        event = ReviewChangesPanel.ActionRequested("approve_selected", result)
        # Set the sender for the message
        event._sender = modal._panel
        modal.on_review_changes_panel_action_requested(event)

        assert "result" in captured
        assert captured["result"].approved is True

    def test_panel_action_reject(self):
        """Panel's reject action should result in dismiss with approved=False."""
        data = _make_data(changes=_make_changes())
        modal = FinalAnswerModal(data=data)
        captured = {}
        modal.dismiss = lambda result: captured.update({"result": result})

        result = modal._panel.get_review_result("reject")
        event = ReviewChangesPanel.ActionRequested("reject", result)
        event._sender = modal._panel
        modal.on_review_changes_panel_action_requested(event)

        assert captured["result"].approved is False


# ---------------------------------------------------------------------------
# Answer tab footer buttons
# ---------------------------------------------------------------------------


class TestAnswerFooterButtons:
    def test_approve_all_answer_btn_handler(self):
        """approve_all_answer_btn should trigger _close_with_approve_all."""
        data = _make_data(changes=_make_changes())
        modal = FinalAnswerModal(data=data)
        captured = {}
        modal.dismiss = lambda result: captured.update({"result": result})

        # Simulate the button press handler
        class FakeButton:
            id = "approve_all_answer_btn"

        class FakeEvent:
            button = FakeButton()

            def stop(self):
                pass

        modal.on_button_pressed(FakeEvent())
        assert captured["result"].approved is True
        assert captured["result"].metadata["selection_mode"] == "all"

    def test_review_changes_btn_handler(self):
        """review_changes_btn should call action_switch_review_tab via call_later."""
        data = _make_data(changes=_make_changes())
        modal = FinalAnswerModal(data=data)
        switched = {"called": False}
        modal.action_switch_review_tab = lambda: switched.update({"called": True})
        # call_later defers execution; stub it to invoke immediately
        modal.call_later = lambda fn: fn()

        class FakeButton:
            id = "review_changes_btn"

        class FakeEvent:
            button = FakeButton()

            def stop(self):
                pass

            def prevent_default(self):
                pass

        modal.on_button_pressed(FakeEvent())
        assert switched["called"] is True


# ---------------------------------------------------------------------------
# Post-eval rendering
# ---------------------------------------------------------------------------


class TestPostEvalRendering:
    def test_post_eval_present(self):
        """Post-eval data should be stored correctly."""
        data = _make_data(post_eval=MOCK_POST_EVAL)
        assert data.post_eval_content == MOCK_POST_EVAL
        assert data.post_eval_status == "verified"

    def test_post_eval_absent(self):
        """No post-eval data should result in 'none' status."""
        data = _make_data(post_eval=None)
        assert data.post_eval_content is None
        assert data.post_eval_status == "none"


# ---------------------------------------------------------------------------
# Context paths
# ---------------------------------------------------------------------------


class TestContextPaths:
    def test_context_paths_stored(self):
        data = _make_data(context_paths=MOCK_CONTEXT_PATHS)
        assert data.context_paths is not None
        assert len(data.context_paths["new"]) == 1
        assert len(data.context_paths["modified"]) == 2

    def test_no_context_paths(self):
        data = _make_data(context_paths=None)
        assert data.context_paths is None


# ---------------------------------------------------------------------------
# Prior action mode (re-opened after approve/reject)
# ---------------------------------------------------------------------------


class TestPriorActionMode:
    def test_prior_action_default(self):
        """prior_action defaults to None."""
        data = FinalAnswerModalData(answer_content="hello")
        assert data.prior_action is None

    def test_prior_action_approved(self):
        """prior_action can be set to 'approved'."""
        data = FinalAnswerModalData(answer_content="hello", prior_action="approved")
        assert data.prior_action == "approved"

    def test_prior_action_rejected(self):
        """prior_action can be set to 'rejected'."""
        data = FinalAnswerModalData(answer_content="hello", prior_action="rejected")
        assert data.prior_action == "rejected"

    def test_prior_action_creates_panel_with_changes(self):
        """prior_action set should still create ReviewChangesPanel when changes exist."""
        data = _make_data(changes=_make_changes())
        data.prior_action = "approved"
        modal = FinalAnswerModal(data=data)
        assert modal._panel is not None
        assert modal._prior_action == "approved"

    def test_prior_action_rejected_creates_panel(self):
        """prior_action='rejected' should still create panel."""
        data = _make_data(changes=_make_changes())
        data.prior_action = "rejected"
        modal = FinalAnswerModal(data=data)
        assert modal._panel is not None
        assert modal._prior_action == "rejected"

    def test_prior_action_no_panel_without_changes(self):
        """prior_action set without changes should not create panel."""
        data = _make_data()
        data.prior_action = "approved"
        modal = FinalAnswerModal(data=data)
        assert modal._panel is None

    def test_prior_action_answer_tab_has_back_button(self):
        """prior_action set should produce 'Back to Timeline' button."""
        data = _make_data()
        tab = AnswerTabContent(data=data, has_changes=True, prior_action="approved")
        assert tab._prior_action == "approved"

    def test_prior_action_back_button_dismisses(self):
        """back_to_timeline_btn should trigger _close_with_approve_all."""
        data = _make_data(changes=_make_changes())
        data.prior_action = "approved"
        modal = FinalAnswerModal(data=data)
        captured = {}
        modal.dismiss = lambda result: captured.update({"result": result})

        class FakeButton:
            id = "back_to_timeline_btn"

        class FakeEvent:
            button = FakeButton()

            def stop(self):
                pass

        modal.on_button_pressed(FakeEvent())
        assert captured["result"].approved is True

    def test_prior_action_esc_dismisses(self):
        """ESC in prior_action mode should dismiss just like normal."""
        data = _make_data(changes=_make_changes())
        data.prior_action = "rejected"
        modal = FinalAnswerModal(data=data)
        captured = {}
        modal.dismiss = lambda result: captured.update({"result": result})
        modal.action_close_modal()
        assert captured["result"].approved is True

    def test_panel_dimmed_when_prior_action_set(self):
        """Panel should have review-approved-dim class when prior_action is set."""
        data = _make_data(changes=_make_changes())
        data.prior_action = "rejected"
        modal = FinalAnswerModal(data=data)
        assert modal._panel is not None
        assert modal._panel.has_class("review-approved-dim")

    def test_panel_rework_disabled_when_prior_action_set(self):
        """Panel should have show_rework=False when prior_action is set."""
        data = _make_data(changes=_make_changes())
        data.prior_action = "approved"
        modal = FinalAnswerModal(data=data)
        assert modal._panel._show_rework is False
