import os
from pathlib import Path

import webview

from thickanon.core.types import AnonymizeConfig, ReviewMode
from thickanon.core.mapping import MappingStore
from thickanon.core.orchestrator import (
    anonymize_paths,
    deanonymize_paths,
    ensure_mapping_outside_root,
)
from thickanon.cli import _expand


def infer_root(paths) -> Path | None:
    """Best-effort root for a set of dropped/picked paths.

    A single directory is its own root; otherwise the common parent directory
    of all paths (files contribute their parent). Returns None for an empty
    selection.
    """
    paths = [Path(p) for p in paths if str(p).strip()]
    if not paths:
        return None
    if len(paths) == 1 and paths[0].is_dir():
        return paths[0]
    dirs = [p if p.is_dir() else p.parent for p in paths]
    return Path(os.path.commonpath([str(d) for d in dirs]))


def default_mapping_for_root(root) -> Path:
    """A default mapping path guaranteed to be OUTSIDE root.

    Placed beside root as ``<root.name>.thickanon-mapping.json`` in root's
    parent. Falls back to the user's home directory when root has no usable
    parent (e.g. a drive root).
    """
    root = Path(root).resolve()
    parent = root.parent
    if parent == root:  # drive root / filesystem anchor
        return Path.home() / "thickanon-mapping.json"
    return parent / f"{root.name}.thickanon-mapping.json"


class Api:
    def __init__(self):
        self.window = None  # set by app.run() after the window is created

    # ----- dialog actions (require a live window; no-op when headless) -----
    def pick_files(self):
        if self.window is None:
            return {"ok": False, "error": "no window"}
        result = self.window.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=True)
        return {"ok": True, "paths": list(result) if result else []}

    def pick_folder(self):
        if self.window is None:
            return {"ok": False, "error": "no window"}
        result = self.window.create_file_dialog(webview.FOLDER_DIALOG)
        return {"ok": True, "paths": list(result) if result else []}

    def pick_mapping(self, suggested_name="mapping.json"):
        if self.window is None:
            return {"ok": False, "error": "no window"}
        result = self.window.create_file_dialog(
            webview.SAVE_DIALOG, save_filename=suggested_name
        )
        # SAVE_DIALOG may return a str or a 1-tuple depending on platform/version
        if not result:
            return {"ok": True, "path": ""}
        path = result[0] if isinstance(result, (list, tuple)) else result
        return {"ok": True, "path": str(path)}

    # ----- default suggestion (pure logic; unit-testable) -----
    def suggest_defaults(self, files, root=""):
        """Given the chosen files and any root the user typed, return sensible
        {root, mapping} defaults so the user can just drag-and-go."""
        root_path = Path(root) if str(root).strip() else infer_root(files)
        if root_path is None:
            return {"ok": True, "root": "", "mapping": ""}
        return {
            "ok": True,
            "root": str(root_path),
            "mapping": str(default_mapping_for_root(root_path)),
        }

    # ----- core actions -----
    def anonymize(self, files, root, mapping_path, mode, deny, backup_dir, passphrase):
        try:
            # Infer a root when the user didn't set one (e.g. pure drag-and-drop),
            # and default the mapping to a path outside that root.
            root_path = Path(root) if str(root).strip() else infer_root(files)
            if root_path is None:
                return {"ok": False, "error": "no files selected"}
            if not str(mapping_path).strip():
                mapping_path = str(default_mapping_for_root(root_path))

            ensure_mapping_outside_root(mapping_path, root_path)
            cfg = AnonymizeConfig(mode=ReviewMode(mode), deny_list=deny or [])
            mapping = MappingStore()
            report = anonymize_paths(
                _expand(files), root_path, mapping, cfg,
                backup_root=Path(backup_dir) if backup_dir else None,
            )
            mapping.save(mapping_path, passphrase=passphrase or None)
            return {
                "ok": True,
                "summary": report.summary(),
                "report": report.to_dict(),
                "mapping_path": str(mapping_path),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def deanonymize(self, files, mapping_path, passphrase):
        try:
            if not str(mapping_path).strip():
                return {"ok": False, "error": "mapping file required to de-anonymize"}
            mapping = MappingStore.load(mapping_path, passphrase=passphrase or None)
            deanonymize_paths(_expand(files), mapping)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
