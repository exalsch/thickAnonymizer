import shutil
from pathlib import Path


def backup_file(src, root, backup_root) -> Path:
    src, root, backup_root = Path(src), Path(root), Path(backup_root)
    rel = src.relative_to(root)
    dest = backup_root / rel
    if dest.exists():
        # The existing backup is by definition the pristine copy from an
        # earlier run. Overwriting it with the already-anonymized file would
        # destroy the only remaining original.
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return dest


def resolve_backup_root(backup, root) -> Path:
    """Turn a user-supplied backup folder into an absolute path.

    A relative path resolves against the root's PARENT, not the process working
    directory. Resolving against the working directory is how a backup folder
    ends up inside the tree being anonymized, where the next run anonymizes the
    backups too.

    ``ensure_backup_outside_root`` applies the same rule, so the check and the
    copy always agree about which folder a relative path means.
    """
    path = Path(backup)
    if not path.is_absolute():
        path = Path(root).resolve().parent / path
    return path.resolve()
