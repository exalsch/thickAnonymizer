"""The JS bridge. Thin: it validates input, delegates to core, and formats
results as JSON-safe dicts. Every method returns {"ok": bool, ...} and never
lets an exception cross into JavaScript.
"""
import importlib.util
import json
import os
import platform
import threading
import uuid
from pathlib import Path

import webview

from thickanon import __version__
from thickanon.core.backup import resolve_backup_root
from thickanon.core.mapping import MappingStore
from thickanon.core.orchestrator import (
    deanonymize_paths,
    ensure_backup_outside_root,
    ensure_mapping_outside_root,
)
from thickanon.core.plan import apply_scan, expand_paths, scan_paths
from thickanon.core.types import AnonymizeConfig, GLiNERConfig, ReviewMode
from thickanon.detectors import gliner_model

# Sending tens of thousands of review rows across the bridge would stall the
# page. Send a window of them and let the UI offer "approve all" for the rest.
REVIEW_LIMIT = 2000

# The allowlist is the security boundary for save_settings: a key that is not
# here can never reach disk. "passphrase" is deliberately absent. Selection-
# derived values (files, root, mapping, backup) are absent too: restoring them
# on the next launch would fight the auto-fill from the new selection.
SETTINGS_KEYS = (
    "mode", "deny", "backup_enabled",
    "gliner", "gliner_labels", "gliner_threshold", "gliner_gpu", "theme",
)


def settings_path() -> Path:
    base = os.environ.get("THICKANON_CONFIG_DIR") or os.environ.get("APPDATA")
    if base:
        return Path(base) / "thickAnonymizer" / "settings.json"
    return Path.home() / ".config" / "thickAnonymizer" / "settings.json"


def gliner_availability() -> tuple[bool, str]:
    """Can the neural backend actually run in THIS build?

    Probed with find_spec so importing torch (seconds) never happens just to
    render the settings panel. The reason is written for someone holding an
    exe, not a checkout: telling them to pip install is useless.
    """
    if importlib.util.find_spec("gliner") is None:
        return False, ("This build ships the regex + spaCy detector only. "
                       "Neural NER (GLiNER) is not included.")
    if importlib.util.find_spec("torch") is None:
        return False, ("GLiNER is present but its PyTorch runtime is not "
                       "bundled in this build.")
    return True, ""


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
    try:
        return Path(os.path.commonpath([str(d) for d in dirs]))
    except ValueError:
        # e.g. paths on different Windows drives have no common root
        return None


def _beside_root(root, suffix: str, home_fallback: str) -> Path:
    root = Path(root).resolve()
    parent = root.parent
    if parent == root:  # drive root / filesystem anchor
        return Path.home() / home_fallback
    return parent / f"{root.name}{suffix}"


def default_mapping_for_root(root) -> Path:
    """A default mapping path guaranteed to be OUTSIDE root."""
    return _beside_root(root, ".thickanon-mapping.json", "thickanon-mapping.json")


def default_backup_for_root(root) -> Path:
    """A default backup folder guaranteed to be OUTSIDE root."""
    return _beside_root(root, ".thickanon-backup", "thickanon-backup")


def preflight_mapping_target(mapping_path) -> None:
    """Fail before any file is written if the mapping could not be saved after.

    The mapping is the only key to the anonymized files. Discovering that its
    destination is unwritable AFTER every file has been overwritten - which,
    with backups off, is unrecoverable - is the worst possible ordering. This
    cannot be made race-proof, so apply() also has a rescue path; this check
    just catches the predictable cases up front with a clear message.
    """
    path = Path(mapping_path)
    if path.is_dir():
        raise ValueError(
            f"the mapping path {path} is a folder, not a file. "
            "Choose a file path for the mapping."
        )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            # Append mode checks writability without truncating a mapping the
            # user may still need.
            with path.open("ab"):
                pass
        else:
            probe = path.parent / f".thickanon-write-test-{uuid.uuid4().hex}"
            probe.write_bytes(b"")
            probe.unlink()
    except Exception as exc:
        raise ValueError(
            f"the mapping file cannot be written to {path}: {exc}. "
            "Choose a different mapping location before anonymizing."
        ) from exc


def save_mapping_or_rescue(mapping, mapping_path, passphrase):
    """Save the mapping, falling back to a rescue copy in the home directory.

    Called only after the files have already been rewritten. At that point the
    mapping is the sole way back, so a failed save must never be allowed to
    simply lose it. Returns (path_actually_used, warning_text).
    """
    try:
        mapping.save(mapping_path, passphrase=passphrase)
        return str(mapping_path), ""
    except Exception as exc:
        rescue = Path.home() / f"thickanon-RESCUE-mapping-{uuid.uuid4().hex[:8]}.json"
        try:
            mapping.save(rescue, passphrase=passphrase)
        except Exception:
            raise ValueError(
                f"the files were anonymized but the mapping could NOT be saved to "
                f"{mapping_path} ({exc}), and the rescue copy failed too. This "
                "anonymization is not reversible - restore the originals from your "
                "backup folder."
            ) from exc
        return str(rescue), (
            f"The mapping could not be saved to {mapping_path} ({exc}). "
            f"It was saved to {rescue} instead. Move it somewhere safe now - it is "
            "the only way to reverse this anonymization."
        )


class Api:
    def __init__(self):
        self.window = None  # set by app.run() after the window is created
        self._scan = None
        self._scan_id = None
        self._cancel = threading.Event()
        self._cancel_lock = threading.Lock()

    # ----- page -> python events -------------------------------------------
    def _emit(self, name: str, payload: dict) -> None:
        """Push an event to the page from a worker thread. Best effort."""
        if self.window is None:
            return
        try:
            self.window.evaluate_js(
                "window.thickanon && window.thickanon.on("
                f"{json.dumps(name)}, {json.dumps(payload)})"
            )
        except Exception:
            pass

    def _progress(self):
        def push(done, total, path, stage):
            self._emit("progress", {"done": done, "total": total,
                                    "path": path, "stage": stage})
        return push

    def on_files_dropped(self, paths) -> dict:
        """Called from Python by the native drop handler (see ui/app.py)."""
        clean = [str(p) for p in (paths or []) if p and str(p).strip()]
        self._emit("files", {"paths": clean})
        return {"ok": True, "paths": clean}

    # ----- environment ------------------------------------------------------
    def environment(self) -> dict:
        available, reason = gliner_availability()
        return {
            "ok": True,
            "version": __version__,
            "platform": platform.system(),
            "gliner": {"available": available, "reason": reason},
        }

    # ----- dialogs (require a live window; no-op when headless) -------------
    def pick_files(self) -> dict:
        if self.window is None:
            return {"ok": False, "error": "no window"}
        result = self.window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True)
        return {"ok": True, "paths": [str(p) for p in result] if result else []}

    def pick_folder(self) -> dict:
        if self.window is None:
            return {"ok": False, "error": "no window"}
        result = self.window.create_file_dialog(webview.FileDialog.FOLDER)
        return {"ok": True, "paths": [str(p) for p in result] if result else []}

    def pick_mapping(self, suggested_name="mapping.json") -> dict:
        if self.window is None:
            return {"ok": False, "error": "no window"}
        result = self.window.create_file_dialog(
            webview.FileDialog.SAVE, save_filename=suggested_name
        )
        # SAVE may return a str or a 1-tuple depending on platform/version
        if not result:
            return {"ok": True, "path": ""}
        path = result[0] if isinstance(result, (list, tuple)) else result
        return {"ok": True, "path": str(path)}

    def pick_backup(self) -> dict:
        return self.pick_folder()

    def save_report(self, report, suggested_name="thickanon-report.json") -> dict:
        """Write a finished report to a file the user chooses."""
        if self.window is None:
            return {"ok": False, "error": "no window"}
        result = self.window.create_file_dialog(
            webview.FileDialog.SAVE, save_filename=suggested_name
        )
        if not result:
            return {"ok": True, "path": ""}
        path = Path(result[0] if isinstance(result, (list, tuple)) else result)
        try:
            path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "path": str(path)}

    # ----- defaults (pure logic; unit-testable) ----------------------------
    def suggest_defaults(self, files, root="") -> dict:
        root_path = Path(root) if str(root).strip() else infer_root(files)
        if root_path is None:
            return {"ok": True, "root": "", "mapping": "", "backup": ""}
        root_path = root_path.resolve()
        return {
            "ok": True,
            "root": str(root_path),
            "mapping": str(default_mapping_for_root(root_path)),
            "backup": str(default_backup_for_root(root_path)),
        }

    # ----- settings ---------------------------------------------------------
    def load_settings(self) -> dict:
        try:
            raw = json.loads(settings_path().read_text(encoding="utf-8"))
            settings = {k: raw[k] for k in SETTINGS_KEYS if k in raw}
        except Exception:
            settings = {}
        return {"ok": True, "settings": settings}

    def save_settings(self, opts) -> dict:
        # The allowlist is the security control: "passphrase" is not in
        # SETTINGS_KEYS, so it can never reach disk.
        settings = {k: (opts or {})[k] for k in SETTINGS_KEYS if k in (opts or {})}
        try:
            path = settings_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "settings": settings}

    # ----- configuration ----------------------------------------------------
    def _config_from(self, opts) -> AnonymizeConfig:
        opts = opts or {}
        deny = opts.get("deny") or []
        if isinstance(deny, str):
            deny = [s.strip() for s in deny.split(",") if s.strip()]
        gliner_cfg = None
        if opts.get("gliner"):
            threshold = opts.get("gliner_threshold")
            kw = {
                "enabled": True,
                # 0 is a legitimate threshold; only None/"" falls back.
                "threshold": 0.5 if threshold in (None, "") else float(threshold),
                "gpu": bool(opts.get("gliner_gpu")),
            }
            labels = [s.strip() for s in str(opts.get("gliner_labels") or "").split(",") if s.strip()]
            if labels:
                kw["labels"] = labels
            gliner_cfg = GLiNERConfig(**kw)
        return AnonymizeConfig(
            mode=ReviewMode(opts.get("mode") or "quick_review"),
            deny_list=deny,
            gliner=gliner_cfg,
        )

    def _root_from(self, opts, files):
        root = opts.get("root")
        root_path = Path(root) if str(root or "").strip() else infer_root(files)
        if root_path is None:
            raise ValueError(
                "Could not work out a common root folder for this selection "
                "(files on different drives, for example). Set the root folder manually."
            )
        return root_path.resolve()

    # ----- actions ----------------------------------------------------------
    def _begin(self):
        """Start a cancellable operation with its own flag.

        Each operation gets a fresh Event so that starting one can never clear
        a cancel aimed at another. pywebview runs every bridge call on its own
        thread, so these really do overlap.
        """
        with self._cancel_lock:
            self._cancel = threading.Event()
            return self._cancel

    def cancel(self) -> dict:
        with self._cancel_lock:
            self._cancel.set()
        return {"ok": True}

    def scan(self, opts) -> dict:
        try:
            opts = dict(opts or {})
            files = opts.get("files") or []
            if not files:
                return {"ok": False, "error": "No files selected."}
            root_path = self._root_from(opts, files)
            cancel_event = self._begin()
            result = scan_paths(
                expand_paths(files), root_path, self._config_from(opts),
                progress=self._progress(), cancel=cancel_event.is_set,
            )
            self._scan = result
            self._scan_id = uuid.uuid4().hex

            review = []
            for file_scan in result.files:
                for candidate in file_scan.candidates:
                    if candidate.band != "review":
                        continue
                    row = candidate.to_dict()
                    row["path"] = str(file_scan.path)
                    review.append(row)
            review_total = len(review)

            return {
                "ok": True,
                "scan_id": self._scan_id,
                "root": str(root_path),
                "counts": result.counts(),
                "review": review[:REVIEW_LIMIT],
                "review_total": review_total,
                "review_truncated": review_total > REVIEW_LIMIT,
                "files": [
                    {"path": str(f.path), **f.band_counts()} for f in result.files
                ],
                "skipped": result.skipped,
                "warnings": result.warnings(),
                "cancelled": result.cancelled,
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def apply(self, scan_id, approved_ids, opts) -> dict:
        try:
            if self._scan is None or scan_id != self._scan_id:
                return {"ok": False, "error":
                        "This preview is no longer valid because the selection or "
                        "settings changed. Scan again."}
            opts = dict(opts or {})
            scan = self._scan
            root_path = scan.root

            backup_root = None
            if opts.get("backup_enabled", True):
                backup = str(opts.get("backup") or "").strip()
                if not backup:
                    backup = str(default_backup_for_root(root_path))
                backup_root = resolve_backup_root(backup, root_path)
                ensure_backup_outside_root(backup_root, root_path)

            mapping_path = str(opts.get("mapping") or "").strip()
            if not mapping_path:
                mapping_path = str(default_mapping_for_root(root_path))
            ensure_mapping_outside_root(mapping_path, root_path)
            preflight_mapping_target(mapping_path)

            approved = set(approved_ids or ())
            if opts.get("approve_all"):
                approved = {c.id for c in scan.review_candidates()}

            mapping = MappingStore()
            cancel_event = self._begin()
            try:
                report = apply_scan(
                    scan, mapping, approved, backup_root,
                    progress=self._progress(), cancel=cancel_event.is_set,
                )
            finally:
                # Any write at all retires the preview: the files on disk no
                # longer match the offsets this scan captured, so a second
                # apply would corrupt them and would copy the already-
                # anonymized files over the backup.
                self._scan = None
                self._scan_id = None
            mapping_path, mapping_warning = save_mapping_or_rescue(
                mapping, mapping_path, opts.get("passphrase") or None
            )

            return {
                "ok": True,
                "summary": report.summary(),
                "report": report.to_dict(),
                "mapping_path": str(mapping_path),
                "backup_root": str(backup_root) if backup_root else "",
                "cancelled": cancel_event.is_set(),
                "warning": mapping_warning,
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def deanonymize(self, opts) -> dict:
        try:
            opts = dict(opts or {})
            files = opts.get("files") or []
            if not files:
                return {"ok": False, "error": "No files selected."}
            mapping_path = str(opts.get("mapping") or "").strip()
            if not mapping_path:
                return {"ok": False, "error":
                        "A mapping file is required to de-anonymize."}
            mapping = MappingStore.load(mapping_path,
                                        passphrase=opts.get("passphrase") or None)
            cancel_event = self._begin()
            report = deanonymize_paths(
                expand_paths(files), mapping,
                progress=self._progress(), cancel=cancel_event.is_set,
            )
            return {"ok": True, "summary": report.summary(),
                    "report": report.to_dict()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def download_model(self) -> dict:
        try:
            available, reason = gliner_availability()
            if not available:
                return {"ok": False, "error": reason}
            gliner_model.load_model(GLiNERConfig())
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
