from pathlib import Path

from thickanon.core.types import AnonymizeConfig
from thickanon.core.mapping import MappingStore
from thickanon.core.anonymize import deanonymize
from thickanon.core.report import BatchReport
from thickanon.core.plan import apply_scan, scan_paths
from thickanon.io.registry import get_handler, UnsupportedFileType


def ensure_mapping_outside_root(mapping_path, root) -> None:
    """Guard: the mapping file (the reversible key) must live OUTSIDE the root
    folder being anonymized.

    If it sat inside root it could be anonymized itself, and — worse — it would
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


def deanonymize_paths(paths, mapping: MappingStore) -> None:
    for path in paths:
        path = Path(path)
        try:
            handler = get_handler(path)
        except UnsupportedFileType:
            continue
        frags = handler.read_fragments(path)
        handler.write_fragments(path, [deanonymize(f, mapping) for f in frags])
