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
