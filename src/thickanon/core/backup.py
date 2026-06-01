import shutil
from pathlib import Path


def backup_file(src, root, backup_root) -> Path:
    src, root, backup_root = Path(src), Path(root), Path(backup_root)
    rel = src.relative_to(root)
    dest = backup_root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return dest
