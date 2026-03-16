"""Tests for CLI --cwd-context handling."""

from massgen.cli import apply_cli_cwd_context_path


def test_apply_cli_cwd_context_path_adds_read_entry(tmp_path, monkeypatch):
    """Should add CWD as read-only context path when missing."""
    monkeypatch.chdir(tmp_path)
    config = {}

    apply_cli_cwd_context_path(config, "ro")

    assert config["orchestrator"]["context_paths"] == [
        {
            "path": str(tmp_path.resolve()),
            "permission": "read",
        },
    ]


def test_apply_cli_cwd_context_path_adds_write_entry_with_alias(tmp_path, monkeypatch):
    """Should accept rw alias and map to write permission."""
    monkeypatch.chdir(tmp_path)
    config = {}

    apply_cli_cwd_context_path(config, "rw")

    assert config["orchestrator"]["context_paths"] == [
        {
            "path": str(tmp_path.resolve()),
            "permission": "write",
        },
    ]


def test_apply_cli_cwd_context_path_updates_existing_permission_and_preserves_fields(
    tmp_path,
    monkeypatch,
):
    """Should update existing CWD entry permission without dropping metadata."""
    monkeypatch.chdir(tmp_path)
    config = {
        "orchestrator": {
            "context_paths": [
                {
                    "path": str(tmp_path.resolve()),
                    "permission": "write",
                    "protected_paths": [".env"],
                },
            ],
        },
    }

    apply_cli_cwd_context_path(config, "ro")

    assert len(config["orchestrator"]["context_paths"]) == 1
    entry = config["orchestrator"]["context_paths"][0]
    assert entry["path"] == str(tmp_path.resolve())
    assert entry["permission"] == "read"
    assert entry["protected_paths"] == [".env"]


def test_apply_cli_cwd_context_path_deduplicates_relative_existing_entry(tmp_path, monkeypatch):
    """Should not duplicate when an existing relative path resolves to CWD."""
    monkeypatch.chdir(tmp_path)
    config = {
        "orchestrator": {
            "context_paths": [
                {"path": ".", "permission": "read"},
            ],
        },
    }

    apply_cli_cwd_context_path(config, "rw")

    assert len(config["orchestrator"]["context_paths"]) == 1
    entry = config["orchestrator"]["context_paths"][0]
    assert entry["path"] == str(tmp_path.resolve())
    assert entry["permission"] == "write"


def test_apply_cli_cwd_context_path_noop_when_not_set(tmp_path, monkeypatch):
    """Should be a no-op when cwd context mode is not provided."""
    monkeypatch.chdir(tmp_path)
    config = {"orchestrator": {"context_paths": [{"path": "/tmp/other", "permission": "read"}]}}

    apply_cli_cwd_context_path(config, None)

    assert config["orchestrator"]["context_paths"] == [{"path": "/tmp/other", "permission": "read"}]
