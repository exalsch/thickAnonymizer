import sys
from pathlib import Path

import pytest

from thickanon.core.backup import resolve_backup_root
from thickanon.core.orchestrator import ensure_backup_outside_root


def test_relative_backup_resolves_against_the_root_parent(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)  # the working directory must be irrelevant

    resolved = resolve_backup_root("backups", root)
    assert resolved == (tmp_path / "backups").resolve()


def test_absolute_backup_is_kept(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    target = tmp_path / "keys" / "b"
    assert resolve_backup_root(target, root) == target.resolve()


def test_backup_inside_root_is_rejected(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    with pytest.raises(ValueError):
        ensure_backup_outside_root(root / ".backup", root)
    with pytest.raises(ValueError):
        ensure_backup_outside_root(root / "sub" / ".backup", root)
    with pytest.raises(ValueError):
        ensure_backup_outside_root(root, root)


def test_backup_beside_root_is_allowed(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    ensure_backup_outside_root(tmp_path / "data.thickanon-backup", root)


def test_guard_interprets_a_relative_path_like_resolve_backup_root(tmp_path, monkeypatch):
    # The guard and the resolver must never disagree about what a relative
    # string means, or a caller can pass the check and still back up inside root.
    root = tmp_path / "data"
    root.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    assert resolve_backup_root("data/.backup", root) == (root / ".backup").resolve()
    with pytest.raises(ValueError):
        ensure_backup_outside_root("data/.backup", root)


def test_dotdot_traversal_back_into_root_is_rejected(tmp_path):
    root = tmp_path / "data"
    (root / "sub").mkdir(parents=True)
    with pytest.raises(ValueError):
        ensure_backup_outside_root(root / "sub" / ".." / ".backup", root)


def test_nonexistent_backup_inside_root_is_still_rejected(tmp_path):
    # The backup folder is normally created later, so the guard must work on a
    # path that does not exist yet.
    root = tmp_path / "data"
    root.mkdir()
    target = root / "deep" / "not" / "created" / "yet"
    assert not target.exists()
    with pytest.raises(ValueError):
        ensure_backup_outside_root(target, root)


@pytest.mark.skipif(sys.platform != "win32",
                    reason="path case-insensitivity is a Windows behaviour")
def test_case_only_difference_is_still_inside_root(tmp_path):
    root = tmp_path / "Data"
    (root / ".backup").mkdir(parents=True)
    disguised = tmp_path / "DATA" / ".backup"  # same folder, different case
    with pytest.raises(ValueError):
        ensure_backup_outside_root(disguised, root)
