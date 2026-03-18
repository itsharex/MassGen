"""Standalone MCP server exposing MassGen workflow tools (new_answer, vote).

new_answer snapshots deliverables into the current session directory so each
round has a traceable record. vote is a stateless passthrough.

Usage:
    python -m massgen.mcp_tools.standalone.workflow_server
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fastmcp

logger = logging.getLogger(__name__)

SERVER_NAME = "massgen_workflow_tools"
QUALITY_DIR = ".massgen-quality"

mcp = fastmcp.FastMCP(SERVER_NAME)


# ---------------------------------------------------------------------------
# Session helpers (shared with quality_server pattern)
# ---------------------------------------------------------------------------


def _safe_session_id(raw: str) -> str:
    """Return a filesystem-safe slug for use as a session directory name."""
    slug = re.sub(r"[^a-zA-Z0-9_-]", "_", raw).strip("_")
    return slug if slug and slug not in (".", "..") else "default"


def _get_session_dir() -> Path:
    """Resolve current session directory from session_metadata.json."""
    quality_root = Path.cwd() / QUALITY_DIR
    metadata_path = quality_root / "session_metadata.json"

    session_id = "default"
    if metadata_path.exists():
        try:
            with open(metadata_path) as f:
                metadata = json.load(f)
            session_id = _safe_session_id(metadata.get("session_id", "default"))
        except (json.JSONDecodeError, OSError):
            pass

    session_dir = quality_root / "sessions" / session_id
    # Validate the resolved path stays within the sessions root
    sessions_root = (quality_root / "sessions").resolve()
    if not session_dir.resolve().is_relative_to(sessions_root):
        session_dir = quality_root / "sessions" / "default"
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def _get_round_number(session_dir: Path) -> int:
    """Read the current round from state.json, or default to 1."""
    state_path = session_dir / "state.json"
    if state_path.exists():
        try:
            with open(state_path) as f:
                state = json.load(f)
            return state.get("round", 0) + 1
        except (json.JSONDecodeError, OSError):
            pass
    return 1


# ---------------------------------------------------------------------------
# Core logic (testable without MCP decorator)
# ---------------------------------------------------------------------------


async def _new_answer_impl(
    answer: str,
    file_paths: list[str] | None = None,
) -> str:
    """Submit a new answer and snapshot deliverables into the session directory."""
    paths = file_paths or []
    session_dir = _get_session_dir()
    round_num = _get_round_number(session_dir)

    # Create round snapshot directory
    round_dir = session_dir / f"round_{round_num:03d}"
    round_dir.mkdir(parents=True, exist_ok=True)

    # Create .scratch dir for this round's verification artifacts
    scratch_dir = round_dir / ".scratch" / "verification"
    scratch_dir.mkdir(parents=True, exist_ok=True)

    # Snapshot deliverable files into the round directory
    snapshot_dir = round_dir / "deliverables"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    workspace_root = Path.cwd().resolve()
    copied = []
    for fp in paths:
        src = Path(fp)
        if not src.is_absolute():
            src = Path.cwd() / src
        src_resolved = src.resolve()
        if not src_resolved.is_relative_to(workspace_root):
            logger.warning(f"Skipping path outside workspace: {fp}")
            continue
        if src_resolved.exists():
            dest = snapshot_dir / src_resolved.name
            try:
                if src_resolved.is_dir():
                    shutil.copytree(src_resolved, dest, dirs_exist_ok=True)
                else:
                    shutil.copy2(src_resolved, dest)
                copied.append(str(dest))
            except OSError as e:
                logger.warning(f"Could not snapshot {src_resolved}: {e}")

    # Write submission manifest
    manifest = {
        "round": round_num,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "answer_summary": answer,
        "original_paths": paths,
        "snapshot_paths": copied,
    }
    with open(round_dir / "submission.json", "w") as f:
        json.dump(manifest, f, indent=2)

    result: dict[str, Any] = {
        "status": "ok",
        "server": SERVER_NAME,
        "tool_name": "new_answer",
        "round": round_num,
        "session_dir": str(session_dir),
        "round_dir": str(round_dir),
        "scratch_dir": str(scratch_dir),
        "snapshots": copied,
        "arguments": {
            "answer": answer,
            "file_paths": paths,
        },
    }
    return json.dumps(result)


async def _vote_impl(
    choice: str,
    reasoning: str = "",
) -> str:
    """Vote to accept the current answer."""
    result: dict[str, Any] = {
        "status": "ok",
        "server": SERVER_NAME,
        "tool_name": "vote",
        "arguments": {
            "choice": choice,
            "reasoning": reasoning,
        },
    }
    return json.dumps(result)


# ---------------------------------------------------------------------------
# MCP tool registrations
# ---------------------------------------------------------------------------


@mcp.tool(
    name="new_answer",
    description=(
        "Submit a completed answer. Call this when you have produced or "
        "improved a deliverable and are ready to submit it for evaluation. "
        "Provide a summary of what was done and paths to the deliverable files. "
        "Files are automatically snapshotted into the session directory for "
        "tracking across rounds."
    ),
)
async def new_answer(answer: str, file_paths: list[str] | None = None) -> str:
    return await _new_answer_impl(answer, file_paths)


@mcp.tool(
    name="vote",
    description=(
        "Cast a vote to accept the current best answer and stop iterating. "
        "Only vote when you are confident that the quality bar has been met "
        "across all evaluation criteria. Provide reasoning for your decision."
    ),
)
async def vote(choice: str, reasoning: str = "") -> str:
    return await _vote_impl(choice, reasoning)


if __name__ == "__main__":
    mcp.run()
