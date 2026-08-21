"""Two-phase anonymize: scan (read + detect, writes nothing) then apply (writes).

Splitting the pass in two lets a UI show exactly what will change before any
file is touched, and lets a human approve gray-band spans in one place instead
of once per text fragment.
"""
from dataclasses import dataclass, field
from pathlib import Path

from thickanon.core.decide import partition
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
        auto = review = 0
        for f in self.files:
            for c in f.candidates:
                by_type[c.entity.entity_type] = by_type.get(c.entity.entity_type, 0) + 1
                if c.band == "auto":
                    auto += 1
                else:
                    review += 1
        return {
            "files": len(self.files),
            "skipped": len(self.skipped),
            "auto": auto,
            "review": review,
            "by_type": by_type,
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
            fragments = handler.read_fragments(path)
            file_index = len(result.files)
            candidates: list[Candidate] = []
            for fragment_index, fragment in enumerate(fragments):
                result.text_bytes += len(fragment.encode("utf-8"))
                apply_now, flagged = partition(detect(fragment, config), config)
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
                FileScan(path=path, file_index=file_index,
                         fragments=fragments, candidates=candidates)
            )
        except Exception as exc:
            # One bad file must not abort the batch: record it and move on.
            result.skipped[str(path)] = f"error: {exc}"

        if progress is not None:
            progress(done, total, str(path), "scan")

    return result
