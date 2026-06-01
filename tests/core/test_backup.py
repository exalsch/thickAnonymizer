from pathlib import Path
from thickanon.core.backup import backup_file

def test_backup_copies_preserving_relative_layout(tmp_path):
    root = tmp_path / "data"; (root / "sub").mkdir(parents=True)
    src = root / "sub" / "a.txt"; src.write_text("secret", encoding="utf-8")
    backup_root = tmp_path / ".backup"

    dest = backup_file(src, root, backup_root)

    assert dest == backup_root / "sub" / "a.txt"
    assert dest.read_text(encoding="utf-8") == "secret"
    assert src.exists()  # original untouched (copy, not move)
