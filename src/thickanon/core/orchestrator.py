from pathlib import Path

from thickanon.core.types import AnonymizeConfig
from thickanon.core.mapping import MappingStore
from thickanon.core.decide import partition
from thickanon.core.anonymize import apply_tokens, deanonymize
from thickanon.core.residual import residual_scan
from thickanon.core.report import BatchReport
from thickanon.core.backup import backup_file
from thickanon.detectors.engine import detect
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


def anonymize_paths(paths, root, mapping: MappingStore, config: AnonymizeConfig,
                    backup_root=None, review_callback=None) -> BatchReport:
    """Anonymize files in place.

    review_callback(flagged, fragment_text, path) -> list[Entity] is called in
    QUICK_REVIEW mode to let a UI choose which gray-band entities to apply. If
    None, gray-band entities are NOT applied (safe default for headless).
    """
    report = BatchReport()
    for path in paths:
        path = Path(path)
        try:
            handler = get_handler(path)
        except UnsupportedFileType as exc:
            report.record_skip(path, f"unsupported: {exc}")
            continue

        try:
            if backup_root is not None:
                backup_file(path, root, backup_root)

            fragments = handler.read_fragments(path)
            new_fragments, applied_all, flagged_all, residual_all = [], [], [], []
            for frag in fragments:
                entities = detect(frag, config)
                apply_now, flagged = partition(entities, config)
                if flagged and review_callback is not None:
                    approved = review_callback(flagged, frag, path)
                    apply_now = apply_now + list(approved)
                    flagged = [e for e in flagged if e not in approved]
                new_text = apply_tokens(frag, apply_now, mapping)
                residual = residual_scan(new_text)
                new_fragments.append(new_text)
                applied_all += apply_now
                flagged_all += flagged
                residual_all += residual
            handler.write_fragments(path, new_fragments)
        except Exception as exc:
            # One bad file must not abort the whole batch: record it and move on.
            report.record_skip(path, f"error: {exc}")
            continue
        report.record_file(path, applied_all, flagged_all, residual_all)
    return report


def deanonymize_paths(paths, mapping: MappingStore) -> None:
    for path in paths:
        path = Path(path)
        try:
            handler = get_handler(path)
        except UnsupportedFileType:
            continue
        frags = handler.read_fragments(path)
        handler.write_fragments(path, [deanonymize(f, mapping) for f in frags])
