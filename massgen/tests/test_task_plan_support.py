#!/usr/bin/env python3
"""Tests for Planning MCP task-plan display helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from massgen.frontend.displays.task_plan_support import update_task_plan_from_tool


class _FakeHost:
    def __init__(self, active_tasks: list[dict[str, Any]] | None = None) -> None:
        self._active_tasks = [dict(t) for t in active_tasks] if active_tasks else None
        self.pinned_updates: list[dict[str, Any]] = []
        self.plan_updates: list[dict[str, Any]] = []

    def get_active_tasks(self) -> list[dict[str, Any]] | None:
        if self._active_tasks is None:
            return None
        return [dict(t) for t in self._active_tasks]

    def update_pinned_task_plan(
        self,
        *,
        tasks: list[dict[str, Any]],
        focused_task_id: str | None = None,
        operation: str = "create",
        show_notification: bool = True,
    ) -> None:
        self.pinned_updates.append(
            {
                "tasks": [dict(t) for t in tasks],
                "focused_task_id": focused_task_id,
                "operation": operation,
                "show_notification": show_notification,
            },
        )
        self._active_tasks = [dict(t) for t in tasks]

    def update_task_plan(
        self,
        tasks: list[dict[str, Any]],
        plan_id: str | None = None,
        operation: str = "create",
    ) -> None:
        self.plan_updates.append(
            {
                "tasks": [dict(t) for t in tasks],
                "plan_id": plan_id,
                "operation": operation,
            },
        )
        self._active_tasks = [dict(t) for t in tasks]


def _tool(tool_name: str, result_full: str, tool_id: str = "tool_1") -> SimpleNamespace:
    return SimpleNamespace(tool_name=tool_name, result_full=result_full, tool_id=tool_id)


def test_update_task_plan_from_codex_wrapper_create_task_plan() -> None:
    host = _FakeHost()
    result = (
        "{'content': [{'type': 'text', 'text': "
        '\'{"success":true,"operation":"create_task_plan","tasks":[{"id":"task_1","description":"Define scope","status":"pending","priority":"medium","dependencies":[],"metadata":{}}]}\''
        "}], 'structured_content': {'success': True, 'operation': 'create_task_plan', "
        "'tasks': [{'id': 'task_1', 'description': 'Define scope', 'status': 'pending', "
        "'priority': 'medium', 'dependencies': [], 'metadata': {}}]}}"
    )
    tool_data = _tool("planning_agent_a/create_task_plan", result, tool_id="item_5")

    handled = update_task_plan_from_tool(host, tool_data, timeline=None)

    assert handled is True
    assert host.pinned_updates, "Expected pinned task plan update"
    assert host.plan_updates, "Expected host task-plan state update"
    assert host.pinned_updates[-1]["operation"] == "create"
    assert host.pinned_updates[-1]["tasks"][0]["id"] == "task_1"
    assert host.plan_updates[-1]["plan_id"] == "item_5"


def test_update_task_plan_from_codex_wrapper_status_update_patches_cached_tasks() -> None:
    host = _FakeHost(
        active_tasks=[
            {
                "id": "task_1",
                "description": "Define scope",
                "status": "pending",
                "priority": "medium",
                "dependencies": [],
                "metadata": {},
            },
        ],
    )
    result = (
        "{'content': [{'type': 'text', 'text': "
        '\'{"success":true,"operation":"update_task_status","task":{"id":"task_1",'
        '"description":"Define scope","status":"completed","priority":"medium",'
        '"dependencies":[],"metadata":{"completion_notes":"done"}}}\''
        "}], 'structured_content': {'success': True, 'operation': 'update_task_status', "
        "'task': {'id': 'task_1', 'description': 'Define scope', 'status': 'completed', "
        "'priority': 'medium', 'dependencies': [], 'metadata': {'completion_notes': 'done'}}}}"
    )
    tool_data = _tool("planning_agent_a/update_task_status", result, tool_id="item_9")

    handled = update_task_plan_from_tool(host, tool_data, timeline=None)

    assert handled is True
    assert host.pinned_updates, "Expected pinned task plan update"
    assert host.pinned_updates[-1]["operation"] == "update"
    assert host.pinned_updates[-1]["focused_task_id"] == "task_1"
    assert host.pinned_updates[-1]["tasks"][0]["status"] == "completed"
    assert host.plan_updates[-1]["operation"] == "update"
