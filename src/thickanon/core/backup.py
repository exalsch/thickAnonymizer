import shutil
from pathlib import Path


def backup_file(src, root, backup_root) -> Path:
    src, root, backup_root = Path(src), Path(root), Path(backup_root)
    rel = src.relative_to(root)
    dest = backup_root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return dest


def resolve_backup_root(backup, root) -> Path:
    """Turn a user-supplied backup folder into an absolute path.

    A relative path resolves against the root's PARENT, not the process working
    directory. Resolving against the working directory is how a backup folder
    ends up inside the tree being anonymized, where the next run anonymizes the
    backups too.
    """
    path = Path(backup)
    if not path.is_absolute():
        path = Path(root).resolve().parent / path
    return path.resolve()
