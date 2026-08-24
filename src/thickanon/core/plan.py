"""Two-phase anonymize: scan (read + detect, writes nothing) then apply (writes).

Splitting the pass in two lets a UI show exactly what will change before any
file is touched, and lets a human approve gray-band spans in one place instead
of once per text fragment.
"""
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from thickanon.core.anonymize import apply_tokens
from thickanon.core.backup import backup_file
from thickanon.core.decide import partition
from thickanon.core.report import BatchReport
from thickanon.core.residual import residual_scan
from thickanon.core.types import AnonymizeConfig, Entity
from thickanon.detectors.engine import detect
from thickanon.io.registry import UnsupportedFileType, get_handler

CONTEXT_RADIUS = 60
TEXT_WARN_BYTES = 200 * 1024 * 1024

# Whitespace that would break a one-line context snippet. Each is replaced by a
# single space, so replacement never shifts the highlight offsets.
_FLATTEN = str.maketrans({"\n": " ", "\r": " ", "\t": " "})


def expand_paths(paths) -> list[Path]:
    """Expand directories to their files; pass plain files through."""
    out: list[Path] = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            out.extend(f for f in p.rglob("*") if f.is_file())
        else:
            out.append(p)
    return out


def file_signature(path):
    """A cheap change-detector for one file: (size, mtime_ns), or None."""
    try:
        st = Path(path).stat()
        return (st.st_size, st.st_mtime_ns)
    except OSError:
        return None


def make_candidate_id(file_index: int, fragment_index: int, entity: Entity) -> str:
    """A stable id for one detected span within one scan."""
    return f"f{file_index}:g{fragment_index}:{entity.start}:{entity.end}:{entity.entity_type}"


def extract_context(fragment: str, entity: Entity, radius: int = CONTEXT_RADIUS):
    """Return (snippet, start, end) where snippet[start:end] is the entity text."""
    left = max(0, entity.start - radius)
    right = min(len(fragment), entity.end + radius)
    prefix = "..." if left > 0 else ""
    suffix = "..." if right < len(fragment) else ""
    snippet = (prefix + fragment[left:right] + suffix).translate(_FLATTEN)
    offset = len(prefix) - left
    return snippet, entity.start + offset, entity.end + offset


@dataclass(frozen=True)
class Candidate:
    id: str
    entity: Entity
    file_index: int
    fragment_index: int
    context: str
    context_start: int
    context_end: int
    band: str  # "auto" | "review"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.entity.entity_type,
            "score": round(float(self.entity.score), 3),
            "text": self.entity.text,
            "context": self.context,
            "context_start": self.context_start,
            "context_end": self.context_end,
            "band": self.band,
            "file_index": self.file_index,
        }


@dataclass
class FileScan:
    path: Path
    file_index: int
    signature: tuple | None = None
    fragments: list[str] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)

    def band_counts(self) -> dict:
        auto = sum(1 for c in self.candidates if c.band == "auto")
        return {"auto": auto, "review": len(self.candidates) - auto}


@dataclass
class ScanResult:
    root: Path
    files: list[FileScan] = field(default_factory=list)
    skipped: dict = field(default_factory=dict)
    text_bytes: int = 0
    cancelled: bool = False

    def auto_candidates(self) -> list[Candidate]:
        return [c for f in self.files for c in f.candidates if c.band == "auto"]

    def review_candidates(self) -> list[Candidate]:
        return [c for f in self.files for c in f.candidates if c.band == "review"]

    def counts(self) -> dict:
        by_type: dict[str, int] = {}
        auto_by_type: dict[str, int] = {}
        review_by_type: dict[str, int] = {}
        auto = review = 0
        for f in self.files:
            for c in f.candidates:
                etype = c.entity.entity_type
                by_type[etype] = by_type.get(etype, 0) + 1
                if c.band == "auto":
                    auto += 1
                    auto_by_type[etype] = auto_by_type.get(etype, 0) + 1
                else:
                    review += 1
                    review_by_type[etype] = review_by_type.get(etype, 0) + 1
        return {
            "files": len(self.files),
            "skipped": len(self.skipped),
            "auto": auto,
            "review": review,
            "by_type": by_type,
            "auto_by_type": auto_by_type,
            "review_by_type": review_by_type,
        }

    def warnings(self) -> list[str]:
        out = []
        if self.text_bytes > TEXT_WARN_BYTES:
            mb = self.text_bytes // (1024 * 1024)
            out.append(
                f"This selection holds about {mb} MB of text, which is kept in memory "
                "for the preview. Consider anonymizing it in smaller batches."
            )
        if self.cancelled:
            out.append("The scan was cancelled, so this preview is incomplete.")
        return out


def scan_paths(paths, root, config: AnonymizeConfig, progress=None, cancel=None) -> ScanResult:
    """Read and detect across paths without modifying anything on disk."""
    paths = [Path(p) for p in paths]
    result = ScanResult(root=Path(root))
    total = len(paths)

    for done, path in enumerate(paths, start=1):
        if cancel is not None and cancel():
            result.cancelled = True
            break
        try:
            handler = get_handler(path)
        except UnsupportedFileType as exc:
            result.skipped[str(path)] = f"unsupported: {exc}"
            if progress is not None:
                progress(done, total, str(path), "scan")
            continue

        try:
            fragments_signature = file_signature(path)
            fragments = handler.read_fragments(path)
            file_index = len(result.files)
            candidates: list[Candidate] = []
            for fragment_index, fragment in enumerate(fragments):
                result.text_bytes += len(fragment.encode("utf-8"))
                def chunk_progress(done_chunks, total_chunks, _done=done, _index=fragment_index):
                    # Only worth reporting when a fragment is large enough to be
                    # split; otherwise this fires once per fragment and adds noise.
                    if progress is None or total_chunks <= 1:
                        return
                    fraction = (_index + done_chunks / total_chunks) / max(1, len(fragments))
                    progress(round(_done - 1 + fraction, 3), total, str(path), "scan")

                apply_now, flagged = partition(detect(fragment, config, progress=chunk_progress), config)
                for band, group in (("auto", apply_now), ("review", flagged)):
                    for entity in group:
                        context, cstart, cend = extract_context(fragment, entity)
                        candidates.append(
                            Candidate(
                                id=make_candidate_id(file_index, fragment_index, entity),
                                entity=entity,
                                file_index=file_index,
                                fragment_index=fragment_index,
                                context=context,
                                context_start=cstart,
                                context_end=cend,
                                band=band,
                            )
                        )
            result.files.append(
                FileScan(path=path, file_index=file_index, signature=fragments_signature,
                         fragments=fragments, candidates=candidates)
            )
        except Exception as exc:
            # One bad file must not abort the batch: record it and move on.
            result.skipped[str(path)] = f"error: {exc}"

        if progress is not None:
            progress(done, total, str(path), "scan")

    return result


def apply_scan(scan: ScanResult, mapping, approved_ids=None, backup_root=None,
               output_root=None, progress=None, cancel=None) -> BatchReport:
    """Write the scan's decisions to disk.

    Auto-band candidates are always applied. Review-band candidates are applied
    only when their id is in approved_ids; the rest are reported as flagged.
    """
    approved = set(approved_ids or ())
    report = BatchReport()
    for path, reason in scan.skipped.items():
        report.record_skip(path, reason)

    total = len(scan.files)
    for done, file_scan in enumerate(scan.files, start=1):
        if cancel is not None and cancel():
            report.record_skip(file_scan.path, "cancelled: not processed")
            if progress is not None:
                progress(done, total, str(file_scan.path), "apply")
            continue

        if file_scan.signature is not None and file_signature(file_scan.path) != file_scan.signature:
            # The preview describes content that is no longer on disk. Writing
            # it back would silently discard whatever changed, or recreate a
            # file the user deleted.
            report.record_skip(file_scan.path, "changed on disk since the preview: not written")
            if progress is not None:
                progress(done, total, str(file_scan.path), "apply")
            continue

        selected, left = [], []
        for candidate in file_scan.candidates:
            if candidate.band == "auto" or candidate.id in approved:
                selected.append(candidate)
            else:
                left.append(candidate)

        try:
            if backup_root is not None:
                try:
                    backup_file(file_scan.path, scan.root, backup_root)
                except ValueError as exc:
                    raise ValueError(
                        f"this file is not inside the root folder, so it cannot be "
                        f"backed up: {exc}"
                    ) from exc

            by_fragment: dict[int, list[Entity]] = {}
            for candidate in selected:
                by_fragment.setdefault(candidate.fragment_index, []).append(candidate.entity)

            new_fragments, residual_all = [], []
            for index, fragment in enumerate(file_scan.fragments):
                new_text = apply_tokens(fragment, by_fragment.get(index, []), mapping)
                new_fragments.append(new_text)
                residual_all += residual_scan(new_text)

            write_target = file_scan.path
            if output_root is not None:
                # Copy first, then rewrite the copy. The office handlers reopen
                # the file they were given, so the destination must already be
                # a valid document rather than an empty file.
                write_target = Path(output_root) / file_scan.path.relative_to(scan.root)
                write_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file_scan.path, write_target)

            get_handler(write_target).write_fragments(write_target, new_fragments)
        except Exception as exc:
            report.record_skip(file_scan.path, f"error: {exc}")
            if progress is not None:
                progress(done, total, str(file_scan.path), "apply")
            continue

        report.record_file(
            file_scan.path,
            [c.entity for c in selected],
            [c.entity for c in left],
            residual_all,
        )
        if progress is not None:
            progress(done, total, str(file_scan.path), "apply")

    return report
