from collections import Counter
from pathlib import Path

from thickanon.core.types import AnonymizeConfig
from thickanon.core.mapping import MappingStore
from thickanon.core.anonymize import deanonymize_counted
from thickanon.core.backup import resolve_backup_root
from thickanon.core.report import BatchReport, DeanonReport
from thickanon.core.plan import apply_scan, scan_paths
from thickanon.io.registry import get_handler, UnsupportedFileType


def ensure_mapping_outside_root(mapping_path, root) -> None:
    """Guard: the mapping file (the reversible key) must live OUTSIDE the root
    folder being anonymized.

    If it sat inside root it could be anonymized itself, and, worse, it would
    be shared alongside the anonymized files, handing a recipient everything
    needed to fully de-anonymize them. Raises ValueError on violation.
    """
    mp = Path(mapping_path).resolve()
    rt = Path(root).resolve()
    if mp == rt or rt in mp.parents:
        raise ValueError(
            f"mapping file must be outside the root folder: {mp} is inside {rt}. "
            "Choose a mapping path in a different directory."
        )


def ensure_backup_outside_root(backup_root, root) -> None:
    """Guard: the backup folder must live OUTSIDE the root being anonymized.

    A backup inside root is anonymized by the next run over that root, which
    destroys the only copy of the originals. Raises ValueError on violation.

    A relative path is interpreted exactly as resolve_backup_root interprets
    it - against the root's parent, never the process working directory - so
    that checking a path and then backing up to it can never disagree about
    which folder was meant.
    """
    bp = resolve_backup_root(backup_root, root)
    rt = Path(root).resolve()
    if bp == rt or rt in bp.parents:
        raise ValueError(
            f"backup folder must be outside the root folder: {bp} is inside {rt}. "
            "Choose a backup folder in a different directory."
        )


def _approved_ids_from_callback(scan, review_callback) -> set:
    """Replay the legacy per-fragment review callback against a scan.

    The callback keeps its original contract:
    review_callback(flagged, fragment_text, path) -> list[Entity].
    Entity is a frozen dataclass, so the returned entities match candidates by
    value and the id lookup is exact.
    """
    if review_callback is None:
        return set()
    approved = set()
    for file_scan in scan.files:
        by_fragment = {}
        for candidate in file_scan.candidates:
            if candidate.band == "review":
                by_fragment.setdefault(candidate.fragment_index, []).append(candidate)
        for fragment_index in sorted(by_fragment):
            candidates = by_fragment[fragment_index]
            chosen = review_callback(
                [c.entity for c in candidates],
                file_scan.fragments[fragment_index],
                file_scan.path,
            )
            chosen = set(chosen or ())
            approved.update(c.id for c in candidates if c.entity in chosen)
    return approved


def anonymize_paths(paths, root, mapping: MappingStore, config: AnonymizeConfig,
                    backup_root=None, review_callback=None) -> BatchReport:
    """Anonymize files in place.

    Implemented as scan-then-apply: every file is read and analysed before any
    file is written, so a failure while reading leaves the batch untouched.

    review_callback(flagged, fragment_text, path) -> list[Entity] is called in
    QUICK_REVIEW mode to let a UI choose which gray-band entities to apply. If
    None, gray-band entities are NOT applied (safe default for headless).
    """
    scan = scan_paths(paths, root, config)
    approved = _approved_ids_from_callback(scan, review_callback)
    return apply_scan(scan, mapping, approved, backup_root)


def deanonymize_paths(paths, mapping: MappingStore, progress=None, cancel=None) -> DeanonReport:
    report = DeanonReport()
    paths = [Path(p) for p in paths]
    total = len(paths)
    for done, path in enumerate(paths, start=1):
        if cancel is not None and cancel():
            report.record_skip(path, "cancelled: not processed")
            if progress is not None:
                progress(done, total, str(path), "deanonymize")
            continue
        try:
            handler = get_handler(path)
        except UnsupportedFileType as exc:
            report.record_skip(path, f"unsupported: {exc}")
            if progress is not None:
                progress(done, total, str(path), "deanonymize")
            continue
        try:
            fragments = handler.read_fragments(path)
            new_fragments, restored, unknown = [], 0, Counter()
            for fragment in fragments:
                new_text, count, missing = deanonymize_counted(fragment, mapping)
                new_fragments.append(new_text)
                restored += count
                unknown.update(missing)
            handler.write_fragments(path, new_fragments)
        except Exception as exc:
            report.record_skip(path, f"error: {exc}")
            if progress is not None:
                progress(done, total, str(path), "deanonymize")
            continue
        report.record_file(path, restored, unknown)
        if progress is not None:
            progress(done, total, str(path), "deanonymize")
    return report
