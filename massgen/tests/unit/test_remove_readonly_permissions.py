"""Tests for _remove_readonly permission fix.

The _remove_readonly handler in _safe_rmtree must set S_IRWXU (0700)
not S_IWRITE (0200), so that partially-failed rmtree leaves directories
traversable rather than write-only.
"""

import os
import stat

from massgen.filesystem_manager._filesystem_manager import _remove_readonly


def test_remove_readonly_sets_rwx_on_directory(tmp_path):
    """After _remove_readonly, a directory should have owner rwx (0700+)."""
    d = tmp_path / "locked_dir"
    d.mkdir()
    os.chmod(d, 0o000)

    called = []
    _remove_readonly(lambda p: called.append(p), str(d), None)

    mode = os.stat(d).st_mode
    assert mode & stat.S_IRWXU == stat.S_IRWXU, f"Expected S_IRWXU (0o700) but got {oct(mode & 0o777)}"
    assert called == [str(d)]


def test_remove_readonly_sets_rwx_on_file(tmp_path):
    """After _remove_readonly, a file should have at least owner rwx."""
    f = tmp_path / "locked_file.txt"
    f.write_text("test")
    os.chmod(f, 0o000)

    removed = []
    _remove_readonly(lambda p: removed.append(p), str(f), None)

    mode = os.stat(f).st_mode
    assert mode & stat.S_IRWXU == stat.S_IRWXU
