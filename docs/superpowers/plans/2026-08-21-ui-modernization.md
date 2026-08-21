# Desktop UI Modernization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the thickAnonymizer desktop shell into a correct, reviewable, recoverable application shipped as one self-contained Windows exe.

**Architecture:** Anonymize is split into two phases in `core/plan.py`: `scan_paths()` reads and detects but writes nothing, `apply_scan()` writes. `anonymize_paths()` becomes a thin wrapper over both so the CLI and all existing tests are untouched. The pywebview shell drives those two phases with a review step in between, pushing progress to the page from the worker thread.

**Tech Stack:** Python 3.13, pywebview 6.2.1 (EdgeChromium/WebView2), Presidio + spaCy `en_core_web_lg`, pytest 9, PyInstaller 6.22.

**Spec:** `docs/superpowers/specs/2026-08-21-ui-modernization-design.md`

## Global Constraints

- Python `>=3.11`. The dev venv is `venv/` at the repo root; run everything through `./venv/Scripts/python.exe`.
- **The existing 82 passing tests are the regression gate.** They must pass untouched after every task. Never edit an existing test to make new code pass; if an existing test fails, the new code is wrong.
- Run the full suite with `./venv/Scripts/python.exe -m pytest -q`.
- No em dashes or en dashes anywhere, including code comments and docs. Use a plain hyphen.
- The mapping file must stay outside the root. The guard `ensure_mapping_outside_root` is called by *callers* (CLI, UI), never inside `anonymize_paths`. The new backup guard follows the same rule: `tests/core/test_orchestrator.py::test_backup_created_when_requested` deliberately passes a backup folder inside the root, so `anonymize_paths` must not enforce the guard.
- The passphrase is never written to disk in settings, logs, or reports.
- The default exe build stays slim: `torch` and `transformers` remain in `_EXCLUDES` in `packaging/thickanon.spec`.
- Entity type names in tokens come from `detectors/normalize.normalize_type`; do not introduce new type strings.
- **One deviation from the spec, deliberate:** `apply_scan()` does **not** take a `config` parameter. Band assignment is decided during `scan_paths`, so the config is unused at apply time and is dropped rather than carried as a dead argument. Everything else matches the spec.

---

### Task 1: Scan phase (`core/plan.py`)

**Files:**
- Create: `src/thickanon/core/plan.py`
- Create: `tests/core/test_plan.py`

**Interfaces:**
- Consumes: `core.types.Entity`, `core.types.AnonymizeConfig`, `core.decide.partition`, `detectors.engine.detect`, `io.registry.get_handler`, `io.registry.UnsupportedFileType`
- Produces:
  - `expand_paths(paths) -> list[Path]`
  - `make_candidate_id(file_index: int, fragment_index: int, entity: Entity) -> str`
  - `extract_context(fragment: str, entity: Entity, radius: int = 60) -> tuple[str, int, int]`
  - `Candidate` (frozen dataclass: `id, entity, file_index, fragment_index, context, context_start, context_end, band`) with `.to_dict()`
  - `FileScan` (dataclass: `path, file_index, fragments, candidates`) with `.band_counts()`
  - `ScanResult` (dataclass: `root, files, skipped, text_bytes, cancelled`) with `.review_candidates()`, `.auto_candidates()`, `.counts()`, `.warnings()`
  - `scan_paths(paths, root, config, progress=None, cancel=None) -> ScanResult`
  - `TEXT_WARN_BYTES` constant

- [ ] **Step 1: Write the failing tests**

Create `tests/core/test_plan.py`:

```python
from pathlib import Path

import pytest

from thickanon.core.plan import (
    Candidate,
    ScanResult,
    expand_paths,
    extract_context,
    make_candidate_id,
    scan_paths,
)
from thickanon.core.types import AnonymizeConfig, Entity, ReviewMode


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_expand_paths_walks_directories(tmp_path):
    _write(tmp_path / "a.txt", "a")
    _write(tmp_path / "sub" / "b.txt", "b")
    found = {p.name for p in expand_paths([tmp_path])}
    assert found == {"a.txt", "b.txt"}
    # a plain file is passed through unchanged
    assert expand_paths([tmp_path / "a.txt"]) == [tmp_path / "a.txt"]


def test_make_candidate_id_is_stable_and_distinct():
    e1 = Entity(4, 9, "PERSON", 0.8, "Alice")
    e2 = Entity(4, 9, "EMAIL", 0.8, "Alice")
    assert make_candidate_id(0, 3, e1) == "f0:g3:4:9:PERSON"
    assert make_candidate_id(0, 3, e1) == make_candidate_id(0, 3, e1)
    assert make_candidate_id(0, 3, e1) != make_candidate_id(0, 3, e2)
    assert make_candidate_id(1, 3, e1) != make_candidate_id(0, 3, e1)


def test_extract_context_highlights_the_span():
    fragment = "please email jane@acme.com today"
    entity = Entity(13, 26, "EMAIL", 0.9, "jane@acme.com")
    context, start, end = extract_context(fragment, entity, radius=5)
    assert context[start:end] == "jane@acme.com"
    assert context.startswith("...")   # text was trimmed on the left
    assert context.endswith("...")     # and on the right


def test_extract_context_replaces_newlines_without_shifting_offsets():
    fragment = "line one\njane@acme.com\nline three"
    entity = Entity(9, 22, "EMAIL", 0.9, "jane@acme.com")
    context, start, end = extract_context(fragment, entity)
    assert "\n" not in context
    assert context[start:end] == "jane@acme.com"


def test_scan_writes_nothing_and_finds_candidates(tmp_path):
    f = _write(tmp_path / "note.txt", "ping 10.0.0.5")
    before = f.read_text(encoding="utf-8")

    scan = scan_paths([f], tmp_path, AnonymizeConfig(mode=ReviewMode.AUTO_REDACT))

    assert f.read_text(encoding="utf-8") == before, "scan must not modify files"
    assert len(scan.files) == 1
    assert scan.files[0].fragments == [before]
    types = {c.entity.entity_type for c in scan.files[0].candidates}
    assert "IP" in types


def test_scan_bands_follow_the_review_mode(tmp_path):
    # HOST scores 0.6 from the FQDN recognizer: below high_threshold (0.65),
    # above low_threshold (0.35), so it is the gray band.
    f = _write(tmp_path / "note.txt", "see intranet.example.com for details")

    review = scan_paths([f], tmp_path, AnonymizeConfig(mode=ReviewMode.QUICK_REVIEW))
    assert [c.band for c in review.files[0].candidates] == ["review"]

    redact = scan_paths([f], tmp_path, AnonymizeConfig(mode=ReviewMode.AUTO_REDACT))
    assert [c.band for c in redact.files[0].candidates] == ["auto"]

    skip = scan_paths([f], tmp_path, AnonymizeConfig(mode=ReviewMode.AUTO_SKIP))
    assert skip.files[0].candidates == []


def test_scan_records_unsupported_and_failing_files(tmp_path, monkeypatch):
    img = tmp_path / "pic.png"
    img.write_bytes(b"\x89PNG")
    bad = _write(tmp_path / "bad.txt", "x")
    good = _write(tmp_path / "good.txt", "ping 10.0.0.9")

    import thickanon.io.text as text_handler

    real_read = text_handler.read_fragments

    def flaky_read(path):
        if Path(path).name == "bad.txt":
            raise OSError("boom")
        return real_read(path)

    monkeypatch.setattr(text_handler, "read_fragments", flaky_read)

    scan = scan_paths([img, bad, good], tmp_path, AnonymizeConfig())

    assert "unsupported" in scan.skipped[str(img)]
    assert "boom" in scan.skipped[str(bad)]
    assert [f.path for f in scan.files] == [good]
    # a skipped file must not consume a file_index
    assert scan.files[0].file_index == 0


def test_scan_reports_progress_once_per_path(tmp_path):
    a = _write(tmp_path / "a.txt", "ping 10.0.0.1")
    b = _write(tmp_path / "b.txt", "ping 10.0.0.2")
    seen = []
    scan_paths([a, b], tmp_path, AnonymizeConfig(),
               progress=lambda done, total, path, stage: seen.append((done, total, stage)))
    assert seen == [(1, 2, "scan"), (2, 2, "scan")]


def test_scan_stops_when_cancelled(tmp_path):
    a = _write(tmp_path / "a.txt", "ping 10.0.0.1")
    b = _write(tmp_path / "b.txt", "ping 10.0.0.2")
    scan = scan_paths([a, b], tmp_path, AnonymizeConfig(), cancel=lambda: True)
    assert scan.cancelled is True
    assert scan.files == []


def test_counts_and_warnings(tmp_path):
    f = _write(tmp_path / "note.txt", "mail jane@acme.com and ping 10.0.0.5")
    scan = scan_paths([f], tmp_path, AnonymizeConfig(mode=ReviewMode.AUTO_REDACT))
    counts = scan.counts()
    assert counts["files"] == 1
    assert counts["auto"] == len(scan.auto_candidates())
    assert counts["review"] == len(scan.review_candidates())
    assert counts["by_type"]["EMAIL"] >= 1
    assert scan.warnings() == []


def test_warning_when_extracted_text_is_huge(tmp_path):
    scan = ScanResult(root=tmp_path, text_bytes=300 * 1024 * 1024)
    assert any("memory" in w.lower() for w in scan.warnings())


def test_candidate_to_dict_is_json_safe(tmp_path):
    import json

    f = _write(tmp_path / "note.txt", "ping 10.0.0.5")
    scan = scan_paths([f], tmp_path, AnonymizeConfig(mode=ReviewMode.AUTO_REDACT))
    payload = scan.files[0].candidates[0].to_dict()
    json.dumps(payload)  # must not raise
    assert set(payload) >= {"id", "type", "score", "text", "context",
                            "context_start", "context_end", "band", "file_index"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/Scripts/python.exe -m pytest tests/core/test_plan.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'thickanon.core.plan'`

- [ ] **Step 3: Write `src/thickanon/core/plan.py`**

```python
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
```

- [ ] **Step 4: Run the new tests**

Run: `./venv/Scripts/python.exe -m pytest tests/core/test_plan.py -q`
Expected: all pass.

- [ ] **Step 5: Run the full suite**

Run: `./venv/Scripts/python.exe -m pytest -q`
Expected: 82 previously-passing tests still pass, plus the new ones.

- [ ] **Step 6: Commit**

```bash
git add src/thickanon/core/plan.py tests/core/test_plan.py
git commit -m "feat(core): scan phase that detects without writing"
```

---

### Task 2: Apply phase and the `anonymize_paths` wrapper

**Files:**
- Modify: `src/thickanon/core/plan.py` (append `apply_scan`)
- Modify: `src/thickanon/core/orchestrator.py:31-73` (rewrite `anonymize_paths`)
- Modify: `src/thickanon/cli.py:14-22` (delete `_expand`, alias to `expand_paths`)
- Modify: `tests/core/test_plan.py` (append apply tests)

**Interfaces:**
- Consumes: everything from Task 1, plus `core.anonymize.apply_tokens`, `core.residual.residual_scan`, `core.report.BatchReport`, `core.backup.backup_file`
- Produces:
  - `apply_scan(scan, mapping, approved_ids=None, backup_root=None, progress=None, cancel=None) -> BatchReport`
  - `anonymize_paths(paths, root, mapping, config, backup_root=None, review_callback=None) -> BatchReport` (signature unchanged)
  - `cli._expand` remains importable as an alias of `expand_paths`

- [ ] **Step 1: Write the failing tests**

Append to `tests/core/test_plan.py`:

```python
from thickanon.core.mapping import MappingStore
from thickanon.core.plan import apply_scan


def test_apply_writes_auto_candidates_only_by_default(tmp_path):
    f = _write(tmp_path / "note.txt", "mail jane@acme.com about intranet.example.com")
    scan = scan_paths([f], tmp_path, AnonymizeConfig(mode=ReviewMode.QUICK_REVIEW))
    report = apply_scan(scan, MappingStore())

    out = f.read_text(encoding="utf-8")
    assert "jane@acme.com" not in out           # EMAIL scores 0.9 -> auto band
    assert "intranet.example.com" in out        # HOST scores 0.6 -> review band, unapproved
    assert report.files[str(f)]["flagged_count"] == 1


def test_apply_writes_approved_review_candidates(tmp_path):
    f = _write(tmp_path / "note.txt", "see intranet.example.com for details")
    scan = scan_paths([f], tmp_path, AnonymizeConfig(mode=ReviewMode.QUICK_REVIEW))
    approved = [c.id for c in scan.review_candidates()]
    assert approved, "the fixture must produce a review-band candidate"

    apply_scan(scan, MappingStore(), approved_ids=approved)
    assert "intranet.example.com" not in f.read_text(encoding="utf-8")


def test_apply_ignores_unknown_ids(tmp_path):
    f = _write(tmp_path / "note.txt", "see intranet.example.com for details")
    scan = scan_paths([f], tmp_path, AnonymizeConfig(mode=ReviewMode.QUICK_REVIEW))
    apply_scan(scan, MappingStore(), approved_ids=["f9:g9:0:1:NOPE"])
    assert "intranet.example.com" in f.read_text(encoding="utf-8")


def test_apply_carries_scan_skips_into_the_report(tmp_path):
    img = tmp_path / "pic.png"
    img.write_bytes(b"\x89PNG")
    scan = scan_paths([img], tmp_path, AnonymizeConfig())
    report = apply_scan(scan, MappingStore())
    assert str(img) in report.skipped


def test_apply_backs_up_before_writing(tmp_path):
    root = tmp_path / "data"
    f = _write(root / "note.txt", "ping 10.0.0.5")
    backup = tmp_path / "backup"
    scan = scan_paths([f], root, AnonymizeConfig(mode=ReviewMode.AUTO_REDACT))
    apply_scan(scan, MappingStore(), backup_root=backup)

    assert (backup / "note.txt").read_text(encoding="utf-8") == "ping 10.0.0.5"
    assert "10.0.0.5" not in f.read_text(encoding="utf-8")


def test_apply_reports_progress_and_honours_cancel(tmp_path):
    a = _write(tmp_path / "a.txt", "ping 10.0.0.1")
    b = _write(tmp_path / "b.txt", "ping 10.0.0.2")
    scan = scan_paths([a, b], tmp_path, AnonymizeConfig(mode=ReviewMode.AUTO_REDACT))

    seen = []
    apply_scan(scan, MappingStore(),
               progress=lambda done, total, path, stage: seen.append((done, total, stage)))
    assert seen == [(1, 2, "apply"), (2, 2, "apply")]

    # a cancelled run leaves the files untouched and says so in the report
    c = _write(tmp_path / "c.txt", "ping 10.0.0.3")
    scan2 = scan_paths([c], tmp_path, AnonymizeConfig(mode=ReviewMode.AUTO_REDACT))
    report = apply_scan(scan2, MappingStore(), cancel=lambda: True)
    assert c.read_text(encoding="utf-8") == "ping 10.0.0.3"
    assert "cancelled" in report.skipped[str(c)]


def test_apply_records_write_failure_and_continues(tmp_path, monkeypatch):
    a = _write(tmp_path / "a.txt", "ping 10.0.0.1")
    b = _write(tmp_path / "b.txt", "ping 10.0.0.2")
    scan = scan_paths([a, b], tmp_path, AnonymizeConfig(mode=ReviewMode.AUTO_REDACT))

    import thickanon.io.text as text_handler

    real_write = text_handler.write_fragments

    def flaky_write(path, fragments):
        if Path(path).name == "a.txt":
            raise OSError("disk full")
        return real_write(path, fragments)

    monkeypatch.setattr(text_handler, "write_fragments", flaky_write)

    report = apply_scan(scan, MappingStore())
    assert "disk full" in report.skipped[str(a)]
    assert str(b) in report.files
    assert "10.0.0.2" not in b.read_text(encoding="utf-8")


def test_review_callback_still_drives_anonymize_paths(tmp_path):
    from thickanon.core.orchestrator import anonymize_paths

    f = _write(tmp_path / "note.txt", "see intranet.example.com for details")
    seen = {}

    def approve_everything(flagged, fragment_text, path):
        seen["fragment"] = fragment_text
        seen["path"] = Path(path)
        return list(flagged)

    anonymize_paths([f], tmp_path, MappingStore(),
                    AnonymizeConfig(mode=ReviewMode.QUICK_REVIEW),
                    review_callback=approve_everything)

    assert seen["path"] == f
    assert seen["fragment"] == "see intranet.example.com for details"
    assert "intranet.example.com" not in f.read_text(encoding="utf-8")


def test_review_callback_rejecting_leaves_the_text(tmp_path):
    from thickanon.core.orchestrator import anonymize_paths

    f = _write(tmp_path / "note.txt", "see intranet.example.com for details")
    anonymize_paths([f], tmp_path, MappingStore(),
                    AnonymizeConfig(mode=ReviewMode.QUICK_REVIEW),
                    review_callback=lambda flagged, text, path: [])
    assert "intranet.example.com" in f.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/Scripts/python.exe -m pytest tests/core/test_plan.py -q`
Expected: `ImportError: cannot import name 'apply_scan'`

- [ ] **Step 3: Append `apply_scan` to `src/thickanon/core/plan.py`**

Add these imports at the top of the file, next to the existing ones:

```python
from thickanon.core.anonymize import apply_tokens
from thickanon.core.backup import backup_file
from thickanon.core.report import BatchReport
from thickanon.core.residual import residual_scan
```

Then append:

```python
def apply_scan(scan: ScanResult, mapping, approved_ids=None, backup_root=None,
               progress=None, cancel=None) -> BatchReport:
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

        selected, left = [], []
        for candidate in file_scan.candidates:
            if candidate.band == "auto" or candidate.id in approved:
                selected.append(candidate)
            else:
                left.append(candidate)

        try:
            if backup_root is not None:
                backup_file(file_scan.path, scan.root, backup_root)

            by_fragment: dict[int, list[Entity]] = {}
            for candidate in selected:
                by_fragment.setdefault(candidate.fragment_index, []).append(candidate.entity)

            new_fragments, residual_all = [], []
            for index, fragment in enumerate(file_scan.fragments):
                new_text = apply_tokens(fragment, by_fragment.get(index, []), mapping)
                new_fragments.append(new_text)
                residual_all += residual_scan(new_text)

            get_handler(file_scan.path).write_fragments(file_scan.path, new_fragments)
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
```

- [ ] **Step 4: Rewrite `anonymize_paths` in `src/thickanon/core/orchestrator.py`**

Replace lines 31-73 (the whole `anonymize_paths` function) with:

```python
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
```

Replace the now-unused import block at the top of `orchestrator.py` with:

```python
from pathlib import Path

from thickanon.core.types import AnonymizeConfig
from thickanon.core.mapping import MappingStore
from thickanon.core.anonymize import deanonymize
from thickanon.core.report import BatchReport
from thickanon.core.plan import apply_scan, scan_paths
from thickanon.io.registry import get_handler, UnsupportedFileType
```

- [ ] **Step 5: Point `cli._expand` at the shared helper**

In `src/thickanon/cli.py`, delete the `_expand` function body (lines 14-22) and replace it with:

```python
from thickanon.core.plan import expand_paths

# Kept as a module-level name because ui/api.py and older callers import it.
_expand = expand_paths
```

- [ ] **Step 6: Run the full suite**

Run: `./venv/Scripts/python.exe -m pytest -q`
Expected: everything passes. `tests/core/test_orchestrator.py` and `tests/test_cli.py` are the proof that the refactor preserved behaviour. **If any of them fail, the refactor is wrong: fix `plan.py` or `orchestrator.py`, never the test.**

- [ ] **Step 7: Commit**

```bash
git add src/thickanon/core/plan.py src/thickanon/core/orchestrator.py src/thickanon/cli.py tests/core/test_plan.py
git commit -m "refactor(core): anonymize_paths becomes scan + apply"
```

---

### Task 3: De-anonymize reports what it did

**Files:**
- Modify: `src/thickanon/core/anonymize.py:18-22`
- Modify: `src/thickanon/core/report.py` (append `DeanonReport`)
- Modify: `src/thickanon/core/orchestrator.py:76-84`
- Modify: `src/thickanon/cli.py:89-92`
- Create: `tests/core/test_deanon_report.py`

**Interfaces:**
- Produces:
  - `core.anonymize.deanonymize_counted(text, mapping) -> tuple[str, int, Counter]`
  - `core.report.DeanonReport` with `record_file(path, restored, unknown)`, `record_skip(path, reason)`, `total_restored()`, `summary()`, `to_dict()`
  - `core.orchestrator.deanonymize_paths(paths, mapping, progress=None, cancel=None) -> DeanonReport`

- [ ] **Step 1: Write the failing tests**

Create `tests/core/test_deanon_report.py`:

```python
from collections import Counter

from thickanon.core.anonymize import deanonymize, deanonymize_counted
from thickanon.core.mapping import MappingStore
from thickanon.core.orchestrator import deanonymize_paths
from thickanon.core.report import DeanonReport


def _mapping_with(value: str, entity_type: str) -> tuple[MappingStore, str]:
    mapping = MappingStore()
    return mapping, mapping.token_for(value, entity_type)


def test_deanonymize_counted_counts_restored_tokens():
    mapping, token = _mapping_with("10.0.0.5", "IP")
    text, restored, unknown = deanonymize_counted(f"ping {token} and {token}", mapping)
    assert text == "ping 10.0.0.5 and 10.0.0.5"
    assert restored == 2
    assert unknown == Counter()


def test_deanonymize_counted_reports_unknown_tokens():
    mapping = MappingStore()
    text, restored, unknown = deanonymize_counted("hello [PERSON_9]", mapping)
    assert text == "hello [PERSON_9]"        # left verbatim
    assert restored == 0
    assert unknown == Counter({"[PERSON_9]": 1})


def test_deanonymize_wrapper_still_returns_text_only():
    mapping, token = _mapping_with("10.0.0.5", "IP")
    assert deanonymize(f"ping {token}", mapping) == "ping 10.0.0.5"


def test_deanon_report_summarises():
    report = DeanonReport()
    report.record_file("a.txt", 3, Counter({"[PERSON_9]": 1}))
    report.record_file("b.txt", 1, Counter())
    report.record_skip("c.png", "unsupported: .png")
    assert report.total_restored() == 4
    text = report.summary()
    assert "4" in text
    assert "[PERSON_9]" in text
    assert "c.png" in text or "skipped: 1" in text


def test_deanonymize_paths_returns_a_report(tmp_path):
    mapping, token = _mapping_with("10.0.0.5", "IP")
    f = tmp_path / "note.txt"
    f.write_text(f"ping {token}", encoding="utf-8")
    img = tmp_path / "pic.png"
    img.write_bytes(b"\x89PNG")

    report = deanonymize_paths([f, img], mapping)

    assert f.read_text(encoding="utf-8") == "ping 10.0.0.5"
    assert report.files[str(f)] == 1
    assert "unsupported" in report.skipped[str(img)]


def test_deanonymize_paths_flags_a_wrong_mapping(tmp_path):
    f = tmp_path / "note.txt"
    f.write_text("ping [IP_1] and [PERSON_2]", encoding="utf-8")
    report = deanonymize_paths([f], MappingStore())
    assert report.total_restored() == 0
    assert set(report.unknown_tokens) == {"[IP_1]", "[PERSON_2]"}


def test_deanonymize_paths_records_failures(tmp_path, monkeypatch):
    f = tmp_path / "note.txt"
    f.write_text("ping [IP_1]", encoding="utf-8")

    import thickanon.io.text as text_handler

    monkeypatch.setattr(text_handler, "read_fragments",
                        lambda path: (_ for _ in ()).throw(OSError("boom")))
    report = deanonymize_paths([f], MappingStore())
    assert "boom" in report.skipped[str(f)]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/Scripts/python.exe -m pytest tests/core/test_deanon_report.py -q`
Expected: `ImportError: cannot import name 'deanonymize_counted'`

- [ ] **Step 3: Add `deanonymize_counted` to `src/thickanon/core/anonymize.py`**

Add `from collections import Counter` at the top, then replace the existing `deanonymize` function with:

```python
def deanonymize_counted(text: str, mapping: MappingStore) -> tuple[str, int, Counter]:
    """Restore tokens and report what happened.

    Returns (new_text, tokens_restored, unknown_tokens). A token with no mapping
    entry is left verbatim and counted as unknown: it means the caller loaded
    the wrong mapping file, which used to fail silently.
    """
    restored = 0
    unknown: Counter = Counter()

    def repl(match):
        nonlocal restored
        token = match.group()
        original = mapping.value_for(token)
        if original is None:
            unknown[token] += 1
            return token
        restored += 1
        return original

    return _TOKEN_RE.sub(repl, text), restored, unknown


def deanonymize(text: str, mapping: MappingStore) -> str:
    return deanonymize_counted(text, mapping)[0]
```

- [ ] **Step 4: Add `DeanonReport` to `src/thickanon/core/report.py`**

Append:

```python
class DeanonReport:
    def __init__(self):
        self.files = {}
        self.unknown_tokens = Counter()
        self.skipped = {}

    def record_file(self, path, restored, unknown=None):
        self.files[str(path)] = restored
        if unknown:
            self.unknown_tokens.update(unknown)

    def record_skip(self, path, reason):
        self.skipped[str(path)] = reason

    def total_restored(self) -> int:
        return sum(self.files.values())

    def to_dict(self) -> dict:
        return {
            "files": self.files,
            "unknown_tokens": dict(self.unknown_tokens),
            "skipped": self.skipped,
            "total_restored": self.total_restored(),
        }

    def summary(self) -> str:
        lines = [
            f"Tokens restored: {self.total_restored()} "
            f"across {len(self.files)} file(s), skipped: {len(self.skipped)}"
        ]
        if self.unknown_tokens:
            shown = ", ".join(sorted(self.unknown_tokens)[:5])
            lines.append(
                f"  UNKNOWN TOKENS: {sum(self.unknown_tokens.values())} "
                f"({shown}) - this mapping does not match these files"
            )
        for path, reason in self.skipped.items():
            lines.append(f"  skipped {path}: {reason}")
        return "\n".join(lines)
```

- [ ] **Step 5: Rewrite `deanonymize_paths` in `src/thickanon/core/orchestrator.py`**

Replace the existing function with:

```python
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
```

Update the orchestrator imports to add:

```python
from collections import Counter

from thickanon.core.anonymize import deanonymize_counted
from thickanon.core.report import BatchReport, DeanonReport
```

(`deanonymize` is no longer used by the orchestrator; drop it from the import list.)

- [ ] **Step 6: Print the report from the CLI**

In `src/thickanon/cli.py`, replace the final three lines of `main` with:

```python
    mapping = MappingStore.load(ns.mapping, passphrase=ns.passphrase)
    report = deanonymize_paths(_expand(ns.paths), mapping)
    print(report.summary())
    if report.unknown_tokens:
        print(
            "WARNING: some tokens had no entry in this mapping. Check that you "
            "loaded the mapping produced by the same anonymize run.",
            file=sys.stderr,
        )
    return 0
```

- [ ] **Step 7: Run the full suite**

Run: `./venv/Scripts/python.exe -m pytest -q`
Expected: all pass. `tests/test_cli.py::test_cli_anonymize_and_deanonymize` asserts `rc == 0` and the round trip, both still true.

- [ ] **Step 8: Commit**

```bash
git add src/thickanon/core/anonymize.py src/thickanon/core/report.py src/thickanon/core/orchestrator.py src/thickanon/cli.py tests/core/test_deanon_report.py
git commit -m "feat(core): de-anonymize reports restored and unknown tokens"
```

---

### Task 4: Backup paths that cannot land inside the root

**Files:**
- Modify: `src/thickanon/core/backup.py`
- Modify: `src/thickanon/core/orchestrator.py` (add `ensure_backup_outside_root` next to the mapping guard)
- Create: `tests/core/test_backup_paths.py`

**Interfaces:**
- Produces:
  - `core.backup.resolve_backup_root(backup, root) -> Path` - relative paths resolve against the root's **parent**, never the process working directory
  - `core.orchestrator.ensure_backup_outside_root(backup_root, root) -> None` - raises `ValueError` when the backup folder is the root or sits inside it

**Note:** neither helper is called from `anonymize_paths` or `apply_scan`. `tests/core/test_orchestrator.py::test_backup_created_when_requested` deliberately backs up into `tmp_path/.backup` while the root is `tmp_path`, and must keep passing. The guard belongs at the UI and CLI boundary, exactly like `ensure_mapping_outside_root`.

- [ ] **Step 1: Write the failing tests**

Create `tests/core/test_backup_paths.py`:

```python
from pathlib import Path

import pytest

from thickanon.core.backup import resolve_backup_root
from thickanon.core.orchestrator import ensure_backup_outside_root


def test_relative_backup_resolves_against_the_root_parent(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)  # the working directory must be irrelevant

    resolved = resolve_backup_root("backups", root)
    assert resolved == (tmp_path / "backups").resolve()


def test_absolute_backup_is_kept(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    target = tmp_path / "keys" / "b"
    assert resolve_backup_root(target, root) == target.resolve()


def test_backup_inside_root_is_rejected(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    with pytest.raises(ValueError):
        ensure_backup_outside_root(root / ".backup", root)
    with pytest.raises(ValueError):
        ensure_backup_outside_root(root / "sub" / ".backup", root)
    with pytest.raises(ValueError):
        ensure_backup_outside_root(root, root)


def test_backup_beside_root_is_allowed(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    ensure_backup_outside_root(tmp_path / "data.thickanon-backup", root)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/Scripts/python.exe -m pytest tests/core/test_backup_paths.py -q`
Expected: `ImportError: cannot import name 'resolve_backup_root'`

- [ ] **Step 3: Add `resolve_backup_root` to `src/thickanon/core/backup.py`**

```python
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
```

- [ ] **Step 4: Add `ensure_backup_outside_root` to `src/thickanon/core/orchestrator.py`**

Place it directly below `ensure_mapping_outside_root`:

```python
def ensure_backup_outside_root(backup_root, root) -> None:
    """Guard: the backup folder must live OUTSIDE the root being anonymized.

    A backup inside root is anonymized by the next run over that root, which
    destroys the only copy of the originals. Raises ValueError on violation.
    """
    bp = Path(backup_root).resolve()
    rt = Path(root).resolve()
    if bp == rt or rt in bp.parents:
        raise ValueError(
            f"backup folder must be outside the root folder: {bp} is inside {rt}. "
            "Choose a backup folder in a different directory."
        )
```

- [ ] **Step 5: Run the full suite**

Run: `./venv/Scripts/python.exe -m pytest -q`
Expected: all pass, including `test_backup_created_when_requested`, which is unaffected because the guard is not wired into `anonymize_paths`.

- [ ] **Step 6: Commit**

```bash
git add src/thickanon/core/backup.py src/thickanon/core/orchestrator.py tests/core/test_backup_paths.py
git commit -m "feat(core): backup path resolution and outside-root guard"
```

---

### Task 5: UI bridge rewrite (`ui/api.py`)

**Files:**
- Rewrite: `src/thickanon/ui/api.py`
- Modify: `tests/ui/test_api.py` (rewrite the anonymize tests for the new API, keep the pure-helper tests)

**Interfaces:**
- Consumes: everything from Tasks 1-4
- Produces the `Api` methods the page calls:
  - `environment() -> {"ok", "version", "platform", "gliner": {"available", "reason"}}`
  - `pick_files() / pick_folder() -> {"ok", "paths"}`
  - `pick_mapping(suggested_name) -> {"ok", "path"}`
  - `pick_backup() -> {"ok", "paths"}` (delegates to `pick_folder`)
  - `save_report(report, suggested_name="thickanon-report.json") -> {"ok", "path"}`
  - `suggest_defaults(files, root="") -> {"ok", "root", "mapping", "backup"}`
  - `scan(opts) -> {"ok", "scan_id", "root", "counts", "review", "review_total", "review_truncated", "files", "skipped", "warnings", "cancelled"}`
  - `apply(scan_id, approved_ids, opts) -> {"ok", "summary", "report", "mapping_path", "backup_root"}`
  - `deanonymize(opts) -> {"ok", "summary", "report"}`
  - `cancel() -> {"ok"}`
  - `download_model() -> {"ok"}`
  - `load_settings() -> {"ok", "settings"}` / `save_settings(opts) -> {"ok", "settings"}`
  - `on_files_dropped(paths) -> {"ok", "paths"}` (called from Python by the drop handler in Task 6)
- Also produces module-level helpers reused by tests and Task 6: `infer_root`, `default_mapping_for_root`, `default_backup_for_root`, `gliner_availability`, `settings_path`, `SETTINGS_KEYS`

- [ ] **Step 1: Write the failing tests**

Rewrite `tests/ui/test_api.py`. Keep `test_infer_root_single_dir_and_common_parent`, `test_default_mapping_is_outside_root`, `test_suggest_defaults_infers_root_and_mapping` and `test_suggest_defaults_empty_when_no_common_root` from the existing file exactly as they are, and replace everything else with:

```python
import json
from pathlib import Path

from thickanon.ui.api import (
    Api,
    default_backup_for_root,
    default_mapping_for_root,
    gliner_availability,
    infer_root,
    settings_path,
)


def _root_with_file(tmp_path, text="mail jane@acme.com and ping 10.0.0.3"):
    root = tmp_path / "data"
    root.mkdir()
    f = root / "n.txt"
    f.write_text(text, encoding="utf-8")
    return root, f


def test_environment_reports_version_and_gliner(tmp_path):
    env = Api().environment()
    assert env["ok"] is True
    assert env["version"]
    assert set(env["gliner"]) == {"available", "reason"}
    if not env["gliner"]["available"]:
        assert "pip install" not in env["gliner"]["reason"].lower()


def test_gliner_availability_reason_is_end_user_language():
    available, reason = gliner_availability()
    assert isinstance(available, bool)
    if not available:
        assert reason and "pip" not in reason.lower()


def test_scan_previews_without_writing(tmp_path):
    root, f = _root_with_file(tmp_path)
    before = f.read_text(encoding="utf-8")
    api = Api()

    result = api.scan({"files": [str(f)], "root": str(root), "mode": "auto_redact"})

    assert result["ok"] is True
    assert f.read_text(encoding="utf-8") == before
    assert result["counts"]["auto"] >= 2
    assert result["scan_id"]
    json.dumps(result)  # the whole payload must cross the JS bridge


def test_scan_then_apply_writes_and_saves_the_mapping(tmp_path):
    root, f = _root_with_file(tmp_path)
    api = Api()
    scan = api.scan({"files": [str(f)], "root": str(root), "mode": "auto_redact"})
    applied = api.apply(scan["scan_id"], [], {
        "mapping": str(tmp_path / "m.json"),
        "backup_enabled": False,
    })

    assert applied["ok"] is True, applied
    out = f.read_text(encoding="utf-8")
    assert "10.0.0.3" not in out and "jane@acme.com" not in out
    assert Path(applied["mapping_path"]).exists()
    assert "IP" in applied["summary"]


def test_apply_applies_only_approved_review_candidates(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    f = root / "n.txt"
    f.write_text("see intranet.example.com for details", encoding="utf-8")
    api = Api()

    scan = api.scan({"files": [str(f)], "root": str(root), "mode": "quick_review"})
    assert scan["review"], "the fixture must produce a review-band candidate"

    api.apply(scan["scan_id"], [], {"mapping": str(tmp_path / "m1.json"),
                                    "backup_enabled": False})
    assert "intranet.example.com" in f.read_text(encoding="utf-8")

    scan = api.scan({"files": [str(f)], "root": str(root), "mode": "quick_review"})
    ids = [c["id"] for c in scan["review"]]
    api.apply(scan["scan_id"], ids, {"mapping": str(tmp_path / "m2.json"),
                                     "backup_enabled": False})
    assert "intranet.example.com" not in f.read_text(encoding="utf-8")


def test_apply_approve_all_covers_a_truncated_review_list(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    f = root / "n.txt"
    f.write_text("see intranet.example.com for details", encoding="utf-8")
    api = Api()
    scan = api.scan({"files": [str(f)], "root": str(root), "mode": "quick_review"})

    api.apply(scan["scan_id"], [], {"mapping": str(tmp_path / "m.json"),
                                    "backup_enabled": False, "approve_all": True})
    assert "intranet.example.com" not in f.read_text(encoding="utf-8")


def test_apply_with_a_stale_scan_id_is_refused(tmp_path):
    root, f = _root_with_file(tmp_path)
    api = Api()
    api.scan({"files": [str(f)], "root": str(root), "mode": "auto_redact"})
    result = api.apply("not-a-real-scan", [], {"mapping": str(tmp_path / "m.json")})
    assert result["ok"] is False
    assert "scan again" in result["error"].lower()
    assert "10.0.0.3" in f.read_text(encoding="utf-8")


def test_apply_rejects_mapping_inside_root(tmp_path):
    root, f = _root_with_file(tmp_path)
    api = Api()
    scan = api.scan({"files": [str(f)], "root": str(root), "mode": "auto_redact"})
    result = api.apply(scan["scan_id"], [], {"mapping": str(root / "m.json"),
                                             "backup_enabled": False})
    assert result["ok"] is False
    assert "outside the root" in result["error"]
    assert "10.0.0.3" in f.read_text(encoding="utf-8")


def test_apply_rejects_backup_inside_root(tmp_path):
    root, f = _root_with_file(tmp_path)
    api = Api()
    scan = api.scan({"files": [str(f)], "root": str(root), "mode": "auto_redact"})
    result = api.apply(scan["scan_id"], [], {
        "mapping": str(tmp_path / "m.json"),
        "backup_enabled": True,
        "backup": str(root / ".backup"),
    })
    assert result["ok"] is False
    assert "outside the root" in result["error"]


def test_apply_backs_up_by_default(tmp_path):
    root, f = _root_with_file(tmp_path)
    api = Api()
    scan = api.scan({"files": [str(f)], "root": str(root), "mode": "auto_redact"})
    result = api.apply(scan["scan_id"], [], {"mapping": str(tmp_path / "m.json")})

    assert result["ok"] is True, result
    backup = Path(result["backup_root"])
    assert backup == default_backup_for_root(root)
    assert (backup / "n.txt").read_text(encoding="utf-8").count("10.0.0.3") == 1


def test_default_backup_is_outside_root(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    backup = default_backup_for_root(root)
    assert backup.parent == tmp_path
    assert root not in backup.parents and backup != root


def test_roundtrip_through_the_api(tmp_path):
    root, f = _root_with_file(tmp_path, "ping 10.0.0.3")
    mapping_path = str(tmp_path / "m.json")
    api = Api()
    scan = api.scan({"files": [str(f)], "root": str(root), "mode": "auto_redact"})
    api.apply(scan["scan_id"], [], {"mapping": mapping_path, "backup_enabled": False})

    result = api.deanonymize({"files": [str(f)], "mapping": mapping_path})
    assert result["ok"] is True
    assert f.read_text(encoding="utf-8") == "ping 10.0.0.3"
    assert result["report"]["total_restored"] == 1


def test_deanonymize_without_a_mapping_is_refused(tmp_path):
    api = Api()
    result = api.deanonymize({"files": ["x.txt"], "mapping": ""})
    assert result["ok"] is False
    assert "mapping" in result["error"].lower()


def test_errors_come_back_as_dicts_not_exceptions(tmp_path):
    api = Api()
    result = api.deanonymize({"files": [], "mapping": str(tmp_path / "missing.json")})
    assert result["ok"] is False
    assert "error" in result


def test_scan_requires_files():
    result = Api().scan({"files": []})
    assert result["ok"] is False
    assert "no files" in result["error"].lower()


def test_settings_roundtrip_never_stores_the_passphrase(tmp_path, monkeypatch):
    monkeypatch.setenv("THICKANON_CONFIG_DIR", str(tmp_path))
    api = Api()
    api.save_settings({"mode": "auto_redact", "deny": "acme", "backup_enabled": False,
                       "passphrase": "hunter2", "unknown_key": "dropped"})

    raw = settings_path().read_text(encoding="utf-8")
    assert "hunter2" not in raw
    assert "unknown_key" not in raw

    loaded = Api().load_settings()
    assert loaded["ok"] is True
    assert loaded["settings"]["mode"] == "auto_redact"
    assert loaded["settings"]["deny"] == "acme"
    assert "passphrase" not in loaded["settings"]


def test_load_settings_survives_a_corrupt_file(tmp_path, monkeypatch):
    monkeypatch.setenv("THICKANON_CONFIG_DIR", str(tmp_path))
    settings_path().parent.mkdir(parents=True, exist_ok=True)
    settings_path().write_text("{not json", encoding="utf-8")
    result = Api().load_settings()
    assert result["ok"] is True
    assert result["settings"] == {}


def test_suggest_defaults_includes_a_backup_path(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    f = root / "n.txt"
    f.write_text("hi", encoding="utf-8")
    res = Api().suggest_defaults([str(f)], root="")
    assert Path(res["backup"]).resolve() == default_backup_for_root(root)


def test_save_report_needs_a_window():
    result = Api().save_report({"totals": {}}, "r.json")
    assert result["ok"] is False


def test_save_report_writes_json(tmp_path):
    class FakeWindow:
        def create_file_dialog(self, *_args, **_kwargs):
            return (str(tmp_path / "r.json"),)

    api = Api()
    api.window = FakeWindow()
    result = api.save_report({"totals": {"IP": 2}}, "r.json")
    assert result["ok"] is True
    assert json.loads(Path(result["path"]).read_text(encoding="utf-8")) == {"totals": {"IP": 2}}


def test_on_files_dropped_records_paths():
    api = Api()
    result = api.on_files_dropped(["C:/a.txt", "", None, "C:/b.txt"])
    assert result["ok"] is True
    assert result["paths"] == ["C:/a.txt", "C:/b.txt"]


def test_gliner_threshold_of_zero_survives(tmp_path):
    root, f = _root_with_file(tmp_path)
    api = Api()
    cfg = api._config_from({"mode": "auto_redact", "gliner": True, "gliner_threshold": 0})
    assert cfg.gliner is not None
    assert cfg.gliner.threshold == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/Scripts/python.exe -m pytest tests/ui/test_api.py -q`
Expected: `ImportError: cannot import name 'default_backup_for_root'`

- [ ] **Step 3: Rewrite `src/thickanon/ui/api.py`**

```python
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


class Api:
    def __init__(self):
        self.window = None  # set by app.run() after the window is created
        self._scan = None
        self._scan_id = None
        self._cancel = threading.Event()

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
    def cancel(self) -> dict:
        self._cancel.set()
        return {"ok": True}

    def scan(self, opts) -> dict:
        try:
            opts = dict(opts or {})
            files = opts.get("files") or []
            if not files:
                return {"ok": False, "error": "No files selected."}
            root_path = self._root_from(opts, files)
            self._cancel.clear()
            result = scan_paths(
                expand_paths(files), root_path, self._config_from(opts),
                progress=self._progress(), cancel=self._cancel.is_set,
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

            mapping_path = str(opts.get("mapping") or "").strip()
            if not mapping_path:
                mapping_path = str(default_mapping_for_root(root_path))
            ensure_mapping_outside_root(mapping_path, root_path)

            backup_root = None
            if opts.get("backup_enabled", True):
                backup = str(opts.get("backup") or "").strip()
                if not backup:
                    backup = str(default_backup_for_root(root_path))
                backup_root = resolve_backup_root(backup, root_path)
                ensure_backup_outside_root(backup_root, root_path)

            approved = set(approved_ids or ())
            if opts.get("approve_all"):
                approved = {c.id for c in scan.review_candidates()}

            mapping = MappingStore()
            self._cancel.clear()
            report = apply_scan(
                scan, mapping, approved, backup_root,
                progress=self._progress(), cancel=self._cancel.is_set,
            )
            mapping.save(mapping_path, passphrase=opts.get("passphrase") or None)

            # The scan describes files that have now changed on disk; retiring it
            # forces a fresh scan rather than a second apply over stale offsets.
            self._scan = None
            self._scan_id = None

            return {
                "ok": True,
                "summary": report.summary(),
                "report": report.to_dict(),
                "mapping_path": str(mapping_path),
                "backup_root": str(backup_root) if backup_root else "",
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
            self._cancel.clear()
            report = deanonymize_paths(
                expand_paths(files), mapping,
                progress=self._progress(), cancel=self._cancel.is_set,
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
```

- [ ] **Step 4: Run the UI tests**

Run: `./venv/Scripts/python.exe -m pytest tests/ui/test_api.py -q`
Expected: all pass.

- [ ] **Step 5: Run the full suite**

Run: `./venv/Scripts/python.exe -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/thickanon/ui/api.py tests/ui/test_api.py
git commit -m "feat(ui): scan/apply bridge with progress, settings and honest GLiNER state"
```

---

### Task 6: Window shell (`ui/app.py`)

**Files:**
- Rewrite: `src/thickanon/ui/app.py`
- Modify: `src/thickanon/__main__.py:36-41`
- Create: `tests/ui/test_app.py`

**Interfaces:**
- Consumes: `ui.api.Api`
- Produces: `webview2_present() -> bool`, `dropped_paths(event) -> list[str]`, `close_splash() -> None`, `run() -> int`

- [ ] **Step 1: Write the failing tests**

Create `tests/ui/test_app.py`:

```python
import sys

import pytest

from thickanon.ui.app import close_splash, dropped_paths, webview2_present


def test_dropped_paths_reads_the_pywebview_full_path():
    event = {"dataTransfer": {"files": [
        {"name": "a.txt", "pywebviewFullPath": "C:/data/a.txt"},
        {"name": "b.txt", "pywebviewFullPath": "C:/data/b.txt"},
    ]}}
    assert dropped_paths(event) == ["C:/data/a.txt", "C:/data/b.txt"]


def test_dropped_paths_drops_entries_without_a_real_path():
    # A backend that cannot supply paths must yield nothing, never a bare name.
    event = {"dataTransfer": {"files": [{"name": "a.txt"}, {"name": "b.txt", "pywebviewFullPath": ""}]}}
    assert dropped_paths(event) == []


def test_dropped_paths_tolerates_junk():
    assert dropped_paths(None) == []
    assert dropped_paths({}) == []
    assert dropped_paths({"dataTransfer": {}}) == []
    assert dropped_paths({"dataTransfer": {"files": None}}) == []


@pytest.mark.skipif(sys.platform != "win32", reason="WebView2 is a Windows runtime")
def test_webview2_present_on_this_dev_machine():
    # The dev machine runs the app, so the runtime must be detected. A check
    # that returns False here would block a working machine.
    assert webview2_present() is True


def test_webview2_present_is_true_off_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert webview2_present() is True


def test_close_splash_is_safe_without_pyinstaller():
    close_splash()  # must not raise outside a bundled exe
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/Scripts/python.exe -m pytest tests/ui/test_app.py -q`
Expected: `ImportError: cannot import name 'close_splash'`

- [ ] **Step 3: Rewrite `src/thickanon/ui/app.py`**

```python
"""Desktop window: preflight the renderer, create the window, wire native drops."""
import sys
import webbrowser
from pathlib import Path

import webview
from webview.dom import DOMEventHandler

from thickanon.ui.api import Api

WEBVIEW2_URL = "https://developer.microsoft.com/microsoft-edge/webview2/"

# Well-known Evergreen WebView2 Runtime client id in the EdgeUpdate registry.
_WEBVIEW2_CLIENT = r"Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


def webview2_present() -> bool:
    """Is the Edge WebView2 Runtime installed?

    Without it pywebview silently falls back to MSHTML and renders the page
    unusably. A failed check returns True: a false negative must never block a
    machine that would have worked.
    """
    if sys.platform != "win32":
        return True
    try:
        import winreg

        candidates = (
            (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\{_WEBVIEW2_CLIENT}"),
            (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\{_WEBVIEW2_CLIENT}"),
            (winreg.HKEY_CURRENT_USER, rf"SOFTWARE\{_WEBVIEW2_CLIENT}"),
        )
        for hive, key in candidates:
            try:
                with winreg.OpenKey(hive, key) as handle:
                    version, _ = winreg.QueryValueEx(handle, "pv")
                    if version and version != "0.0.0.0":
                        return True
            except OSError:
                continue
        return False
    except Exception:
        return True


def message_box(title: str, text: str) -> None:
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)
            return
        except Exception:
            pass
    print(f"{title}: {text}", file=sys.stderr)


def close_splash() -> None:
    """Dismiss the PyInstaller splash screen. No-op outside a bundled exe."""
    try:
        import pyi_splash  # provided only inside a PyInstaller bundle

        pyi_splash.close()
    except Exception:
        pass


def dropped_paths(event) -> list[str]:
    """Pull real filesystem paths out of a pywebview drop event.

    pywebview injects pywebviewFullPath per file on WebView2. Anything without
    one is discarded: a bare File.name is a filename, not a path, and using it
    would resolve against the process working directory.
    """
    files = ((event or {}).get("dataTransfer") or {}).get("files") or []
    return [str(f.get("pywebviewFullPath")) for f in files if f.get("pywebviewFullPath")]


def _wire_drop(window, api: Api) -> None:
    def on_drop(event):
        api.on_files_dropped(dropped_paths(event))

    try:
        element = window.dom.get_element("#drop")
        if element is not None:
            element.events.drop += DOMEventHandler(
                on_drop, prevent_default=True, stop_propagation=True
            )
    except Exception:
        # Drag-and-drop is a convenience; the Browse buttons always work.
        pass


def run() -> int:
    if not webview2_present():
        close_splash()
        message_box(
            "thickAnonymizer",
            "Microsoft Edge WebView2 Runtime is required to show the app window.\n\n"
            f"Install the Evergreen Runtime from:\n{WEBVIEW2_URL}\n\n"
            "The command-line mode works without it.",
        )
        webbrowser.open(WEBVIEW2_URL)
        return 1

    html = Path(__file__).parent / "web" / "index.html"
    api = Api()
    window = webview.create_window(
        "thickAnonymizer", url=html.as_uri(), js_api=api,
        width=1060, height=840, min_size=(760, 620),
    )
    api.window = window  # let the bridge open dialogs and push progress

    def on_loaded(*_args):
        _wire_drop(window, api)
        close_splash()

    window.events.loaded += on_loaded
    webview.start()
    return 0


if __name__ == "__main__":
    sys.exit(run())
```

- [ ] **Step 4: Propagate the exit code in `src/thickanon/__main__.py`**

Replace the GUI branch (lines 36-41) with:

```python
    # No arguments -> desktop GUI.
    _hide_console_on_windows()
    from thickanon.ui.app import run

    return run()
```

- [ ] **Step 5: Run the tests**

Run: `./venv/Scripts/python.exe -m pytest tests/ui/test_app.py -q`
Expected: all pass.

- [ ] **Step 6: Run the full suite**

Run: `./venv/Scripts/python.exe -m pytest -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/thickanon/ui/app.py src/thickanon/__main__.py tests/ui/test_app.py
git commit -m "feat(ui): WebView2 preflight, native drag-and-drop, splash handoff"
```

---

### Task 7: Page structure and styling (`ui/web/index.html`, `ui/web/app.css`)

**Files:**
- Rewrite: `src/thickanon/ui/web/index.html`
- Create: `src/thickanon/ui/web/app.css`
- Create: `tests/ui/test_web_assets.py`

**Interfaces:**
- Produces the DOM contract Task 8 scripts against. Every id below is load-bearing; renaming one breaks `app.js` and the contract test.
- Consumed by Task 6: the element `#drop` is what `ui/app.py::_wire_drop` attaches the native drop handler to.

- [ ] **Step 1: Write the failing contract test**

Create `tests/ui/test_web_assets.py`:

```python
import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[2] / "src" / "thickanon" / "ui" / "web"

REQUIRED_IDS = [
    # files
    "drop", "browse-files", "browse-folder", "clear-files", "files", "file-count",
    # settings
    "mode", "root", "mapping", "choose-mapping", "backup-enabled", "backup",
    "choose-backup", "pass", "pass-confirm", "pass-confirm-row", "deny",
    # advanced
    "advanced", "gliner", "gliner-note", "gliner-labels", "gliner-threshold",
    "gliner-gpu", "download-model",
    # actions
    "scan", "deanonymize", "cancel",
    # progress
    "progress", "progress-bar", "progress-label", "progress-file",
    # review
    "review", "review-groups", "review-count", "review-approve-all",
    "review-reject-all", "review-apply", "review-cancel", "review-truncated",
    # report
    "report", "report-headline", "report-types", "report-files", "report-skipped",
    "report-residual", "report-copy", "report-save",
    # chrome
    "version", "theme-toggle", "banner",
]


def _read(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


def test_the_three_assets_exist():
    for name in ("index.html", "app.css", "app.js"):
        assert (WEB / name).is_file(), f"{name} is missing"


def test_html_links_the_split_assets():
    html = _read("index.html")
    assert 'href="app.css"' in html
    assert 'src="app.js"' in html


@pytest.mark.parametrize("element_id", REQUIRED_IDS)
def test_required_element_is_present(element_id):
    assert f'id="{element_id}"' in _read("index.html"), f"#{element_id} is missing"


def test_no_inline_event_handlers():
    html = _read("index.html")
    found = re.findall(r'\son[a-z]+\s*=\s*"', html)
    assert found == [], f"inline handlers found: {found}"


def test_no_file_path_fallback_anywhere():
    # File.path does not exist in WebView2. Reading it and falling back to
    # File.name is the original drag-and-drop bug; paths come from Python.
    js = _read("app.js")
    assert ".path ||" not in js
    assert "dataTransfer.files" not in js


def test_page_declares_a_theme_for_both_schemes():
    css = _read("app.css")
    assert "prefers-color-scheme: dark" in css
    assert ':root[data-theme="dark"]' in css
    assert ':root[data-theme="light"]' in css
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./venv/Scripts/python.exe -m pytest tests/ui/test_web_assets.py -q`
Expected: failures for the missing `app.css` and `app.js`, and for every missing id.

- [ ] **Step 3: Write `src/thickanon/ui/web/index.html`**

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>thickAnonymizer</title>
<link rel="stylesheet" href="app.css">
</head>
<body>

<header class="topbar">
  <div class="brand">
    <span class="mark" aria-hidden="true">TA</span>
    <div>
      <h1>thickAnonymizer</h1>
      <p class="tagline">Replace sensitive values with readable tokens before sharing files with an AI tool.</p>
    </div>
  </div>
  <div class="topbar-actions">
    <span id="version" class="version"></span>
    <button id="theme-toggle" class="btn ghost small" type="button">Theme</button>
  </div>
</header>

<div id="banner" class="banner" role="alert" hidden></div>

<main>

  <section class="card">
    <h2><span class="step">1</span> Choose files</h2>
    <div id="drop" class="dropzone">
      <strong>Drag files or a folder here</strong>
      <span class="muted">or use the buttons below</span>
    </div>
    <div class="btn-row">
      <button id="browse-files" class="btn ghost" type="button">Browse files...</button>
      <button id="browse-folder" class="btn ghost" type="button">Browse folder...</button>
      <button id="clear-files" class="btn ghost" type="button" hidden>Clear all</button>
      <span id="file-count" class="muted" aria-live="polite"></span>
    </div>
    <ul id="files" class="chips"></ul>
  </section>

  <section class="card">
    <h2><span class="step">2</span> Settings</h2>

    <div class="grid">
      <div class="field">
        <label for="mode">Review mode</label>
        <select id="mode">
          <option value="quick_review">Quick review - I approve the uncertain ones</option>
          <option value="auto_redact">Automatic - redact everything uncertain</option>
          <option value="auto_skip">Automatic - skip everything uncertain</option>
        </select>
        <p class="hint">Quick review lists uncertain detections before anything is written.</p>
      </div>
      <div class="field">
        <label for="root">Root folder</label>
        <input id="root" type="text" placeholder="(worked out from your selection)" spellcheck="false">
        <p class="hint">Paths in the mapping are recorded relative to this folder.</p>
      </div>
    </div>

    <div class="field">
      <label for="mapping">Mapping file <span class="req">must be outside the root folder</span></label>
      <div class="with-button">
        <input id="mapping" type="text" placeholder="(auto: beside the root folder)" spellcheck="false">
        <button id="choose-mapping" class="btn ghost" type="button">Choose...</button>
      </div>
      <p class="hint">This file is the reversible key. It is the sensitive artefact - keep it out of anything you share.</p>
    </div>

    <div class="field">
      <label class="check">
        <input id="backup-enabled" type="checkbox" checked>
        <span>Back up the originals before editing</span>
      </label>
      <div class="with-button">
        <input id="backup" type="text" placeholder="(auto: beside the root folder)" spellcheck="false">
        <button id="choose-backup" class="btn ghost" type="button">Choose...</button>
      </div>
      <p class="hint">Files are edited in place. With backups off, the originals are gone.</p>
    </div>

    <div class="grid">
      <div class="field">
        <label for="pass">Passphrase <span class="muted">(optional, encrypts the mapping)</span></label>
        <input id="pass" type="password" autocomplete="new-password">
      </div>
      <div class="field" id="pass-confirm-row" hidden>
        <label for="pass-confirm">Confirm passphrase</label>
        <input id="pass-confirm" type="password" autocomplete="new-password">
        <p class="hint">A typo here cannot be recovered: the mapping would be unreadable.</p>
      </div>
    </div>

    <div class="field">
      <label for="deny">Always replace these terms <span class="muted">(comma separated)</span></label>
      <input id="deny" type="text" placeholder="Project Falcon, acme, contoso.local" spellcheck="false">
    </div>

    <details id="advanced">
      <summary>Advanced: neural detection</summary>
      <p id="gliner-note" class="hint"></p>
      <label class="check">
        <input id="gliner" type="checkbox">
        <span>Use neural NER (GLiNER, higher recall, much slower)</span>
      </label>
      <div class="grid">
        <div class="field">
          <label for="gliner-labels">Labels <span class="muted">(comma separated)</span></label>
          <input id="gliner-labels" type="text" placeholder="person, organization, email" spellcheck="false">
        </div>
        <div class="field">
          <label for="gliner-threshold">Threshold</label>
          <input id="gliner-threshold" type="number" min="0" max="1" step="0.05" value="0.5">
        </div>
      </div>
      <label class="check">
        <input id="gliner-gpu" type="checkbox">
        <span>Use the GPU (needs a CUDA build of PyTorch)</span>
      </label>
      <button id="download-model" class="btn ghost" type="button">Download the GLiNER model</button>
    </details>
  </section>

  <section class="card">
    <h2><span class="step">3</span> Run</h2>
    <div class="btn-row">
      <button id="scan" class="btn primary" type="button">Scan and preview</button>
      <button id="deanonymize" class="btn secondary" type="button">De-anonymize</button>
      <button id="cancel" class="btn ghost" type="button" hidden>Cancel</button>
    </div>
    <p class="hint">Scanning reads and analyses your files but writes nothing. You see what will change before it happens.</p>

    <div id="progress" class="progress" hidden>
      <div class="progress-track"><div id="progress-bar" class="progress-bar"></div></div>
      <p id="progress-label" class="muted" aria-live="polite"></p>
      <p id="progress-file" class="path"></p>
    </div>
  </section>

  <section id="report" class="card" hidden>
    <h2>Result</h2>
    <p id="report-residual" class="alert danger" hidden></p>
    <div id="report-headline" class="headline"></div>
    <div id="report-types" class="chips readonly"></div>
    <h3>Files</h3>
    <div class="table-wrap"><table id="report-files"></table></div>
    <h3 id="report-skipped-h">Skipped</h3>
    <div class="table-wrap"><table id="report-skipped"></table></div>
    <div class="btn-row">
      <button id="report-copy" class="btn ghost" type="button">Copy report</button>
      <button id="report-save" class="btn ghost" type="button">Save report as JSON</button>
    </div>
  </section>

</main>

<dialog id="review">
  <form method="dialog" class="review-shell">
    <header class="review-head">
      <h2>Uncertain detections</h2>
      <p id="review-count" class="muted"></p>
      <p id="review-truncated" class="alert warn" hidden></p>
      <div class="btn-row">
        <button id="review-approve-all" class="btn ghost" type="button">Approve all</button>
        <button id="review-reject-all" class="btn ghost" type="button">Reject all</button>
      </div>
    </header>
    <div id="review-groups" class="review-body"></div>
    <footer class="review-foot">
      <button id="review-cancel" class="btn ghost" type="button">Cancel</button>
      <button id="review-apply" class="btn primary" type="button">Apply</button>
    </footer>
  </form>
</dialog>

<script src="app.js"></script>
</body>
</html>
```

- [ ] **Step 4: Write `src/thickanon/ui/web/app.css`**

The palette lives entirely in custom properties on `:root`, redefined under
`@media (prefers-color-scheme: dark)` guarded with `:root:not([data-theme="light"])`, and
again under `:root[data-theme="dark"]` and `:root[data-theme="light"]` so the manual toggle
wins in both directions.

```css
:root {
  --bg: #f6f7f9;
  --surface: #ffffff;
  --surface-2: #f0f2f5;
  --border: #d8dce3;
  --text: #14181f;
  --muted: #5c6472;
  --accent: #2563eb;
  --accent-text: #ffffff;
  --ok: #0f7b52;
  --warn: #9a6200;
  --warn-bg: #fdf3d8;
  --danger: #b42318;
  --danger-bg: #fdeceb;
  --focus: #2563eb;
  --radius: 10px;
  --gap: 16px;
  --font: system-ui, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  --mono: ui-monospace, "Cascadia Mono", Consolas, monospace;
  color-scheme: light;
}

:root:not([data-theme="light"]) { }

@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #0e1117;
    --surface: #161b23;
    --surface-2: #1d232d;
    --border: #2c3440;
    --text: #e6e9ef;
    --muted: #97a1b0;
    --accent: #4d8dff;
    --accent-text: #08111f;
    --ok: #3ddc9a;
    --warn: #ffcc66;
    --warn-bg: #33290f;
    --danger: #ff8a80;
    --danger-bg: #3a1d1b;
    --focus: #6ba4ff;
    color-scheme: dark;
  }
}

:root[data-theme="dark"] {
  --bg: #0e1117;
  --surface: #161b23;
  --surface-2: #1d232d;
  --border: #2c3440;
  --text: #e6e9ef;
  --muted: #97a1b0;
  --accent: #4d8dff;
  --accent-text: #08111f;
  --ok: #3ddc9a;
  --warn: #ffcc66;
  --warn-bg: #33290f;
  --danger: #ff8a80;
  --danger-bg: #3a1d1b;
  --focus: #6ba4ff;
  color-scheme: dark;
}

:root[data-theme="light"] {
  --bg: #f6f7f9;
  --surface: #ffffff;
  --surface-2: #f0f2f5;
  --border: #d8dce3;
  --text: #14181f;
  --muted: #5c6472;
  --accent: #2563eb;
  --accent-text: #ffffff;
  --ok: #0f7b52;
  --warn: #9a6200;
  --warn-bg: #fdf3d8;
  --danger: #b42318;
  --danger-bg: #fdeceb;
  --focus: #2563eb;
  color-scheme: light;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  font-family: var(--font);
  font-size: 14px;
  line-height: 1.5;
  background: var(--bg);
  color: var(--text);
}

:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: 2px;
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap);
  padding: 18px 24px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}
.brand { display: flex; align-items: center; gap: 12px; }
.mark {
  display: grid;
  place-items: center;
  width: 36px; height: 36px;
  border-radius: 9px;
  background: var(--accent);
  color: var(--accent-text);
  font-weight: 700;
  letter-spacing: .5px;
}
.topbar h1 { margin: 0; font-size: 17px; }
.tagline { margin: 2px 0 0; color: var(--muted); font-size: 12.5px; }
.topbar-actions { display: flex; align-items: center; gap: 10px; }
.version { color: var(--muted); font-size: 12px; }

main {
  max-width: 940px;
  margin: 0 auto;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: var(--gap);
}

.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px;
}
.card h2 {
  margin: 0 0 16px;
  font-size: 15px;
  display: flex;
  align-items: center;
  gap: 10px;
}
.card h3 { font-size: 13px; margin: 18px 0 8px; color: var(--muted); }
.step {
  display: grid; place-items: center;
  width: 22px; height: 22px;
  border-radius: 50%;
  background: var(--surface-2);
  color: var(--muted);
  font-size: 12px;
}

.dropzone {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 34px;
  border: 2px dashed var(--border);
  border-radius: var(--radius);
  background: var(--surface-2);
  text-align: center;
  transition: border-color .12s, background .12s;
}
.dropzone.over { border-color: var(--accent); background: var(--surface); }

.btn-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 12px; }

.btn {
  font: inherit;
  padding: 9px 16px;
  border-radius: 8px;
  border: 1px solid transparent;
  cursor: pointer;
  background: var(--surface-2);
  color: var(--text);
}
.btn:hover:not(:disabled) { filter: brightness(1.06); }
.btn:disabled { opacity: .5; cursor: not-allowed; }
.btn.ghost { background: transparent; border-color: var(--border); }
.btn.small { padding: 5px 10px; font-size: 12px; }
.btn.primary { background: var(--accent); color: var(--accent-text); font-weight: 600; }
.btn.secondary { background: transparent; border-color: var(--ok); color: var(--ok); font-weight: 600; }

.grid { display: grid; grid-template-columns: 1fr 1fr; gap: var(--gap); }
@media (max-width: 720px) { .grid { grid-template-columns: 1fr; } }

.field { margin-bottom: 14px; }
.field label { display: block; margin-bottom: 5px; font-weight: 600; font-size: 13px; }
.field label.check { display: flex; align-items: center; gap: 8px; font-weight: 500; }
.field label.check input { width: auto; }
input[type="text"], input[type="password"], input[type="number"], select {
  width: 100%;
  font: inherit;
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--surface-2);
  color: var(--text);
}
.with-button { display: flex; gap: 8px; }
.with-button input { flex: 1; }
.hint { margin: 5px 0 0; font-size: 12px; color: var(--muted); }
.muted { color: var(--muted); }
.req { font-weight: 500; font-size: 12px; color: var(--warn); }
.path { font-family: var(--mono); font-size: 12px; color: var(--muted); word-break: break-all; }

.chips { list-style: none; margin: 12px 0 0; padding: 0; display: flex; flex-wrap: wrap; gap: 6px; max-height: 180px; overflow: auto; }
.chips li {
  display: flex; align-items: center; gap: 6px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 4px 6px 4px 12px;
  font-size: 12px;
  font-family: var(--mono);
}
.chips.readonly li { padding: 4px 12px; font-family: var(--font); }
.chips button {
  border: 0; background: transparent; color: var(--muted);
  cursor: pointer; font-size: 14px; line-height: 1; padding: 2px 6px; border-radius: 999px;
}
.chips button:hover { color: var(--danger); }

details#advanced { border-top: 1px solid var(--border); padding-top: 12px; }
details#advanced summary { cursor: pointer; font-weight: 600; font-size: 13px; }
details#advanced[data-unavailable="true"] .check,
details#advanced[data-unavailable="true"] .field,
details#advanced[data-unavailable="true"] #download-model { opacity: .5; }

.progress { margin-top: 16px; }
.progress-track { height: 6px; border-radius: 999px; background: var(--surface-2); overflow: hidden; }
.progress-bar { height: 100%; width: 0; background: var(--accent); transition: width .15s linear; }

.headline { display: flex; flex-wrap: wrap; gap: 20px; margin-bottom: 12px; }
.headline div { display: flex; flex-direction: column; }
.headline b { font-size: 22px; }
.headline span { font-size: 12px; color: var(--muted); }

.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--border); }
th { color: var(--muted); font-weight: 600; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
td.file { font-family: var(--mono); word-break: break-all; }

.alert { border-radius: 8px; padding: 10px 12px; margin: 0 0 12px; font-size: 13px; }
.alert.danger { background: var(--danger-bg); color: var(--danger); border: 1px solid var(--danger); }
.alert.warn { background: var(--warn-bg); color: var(--warn); border: 1px solid var(--warn); }

.banner { margin: 0; border-radius: 0; padding: 10px 24px; font-size: 13px; background: var(--danger-bg); color: var(--danger); }
.banner.info { background: var(--surface-2); color: var(--text); }

dialog#review {
  width: min(860px, 94vw);
  max-height: 88vh;
  padding: 0;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  color: var(--text);
}
dialog#review::backdrop { background: rgba(0, 0, 0, .55); }
.review-shell { display: flex; flex-direction: column; max-height: 88vh; }
.review-head { padding: 18px 20px; border-bottom: 1px solid var(--border); }
.review-head h2 { margin: 0; font-size: 15px; }
.review-body { overflow: auto; padding: 8px 20px; }
.review-foot { display: flex; justify-content: flex-end; gap: 8px; padding: 14px 20px; border-top: 1px solid var(--border); }

.review-group { margin: 14px 0; }
.review-group header { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
.review-group h3 { margin: 0; font-size: 13px; color: var(--text); }
.review-row { display: flex; gap: 10px; align-items: flex-start; padding: 7px 0; border-bottom: 1px solid var(--border); }
.review-row input { margin-top: 3px; }
.review-row .snippet { font-family: var(--mono); font-size: 12px; word-break: break-word; }
.review-row mark { background: var(--warn-bg); color: var(--warn); border-radius: 3px; padding: 0 2px; }
.review-row .meta { margin-left: auto; text-align: right; white-space: nowrap; font-size: 11.5px; color: var(--muted); }
```

- [ ] **Step 5: Run the contract test**

Run: `./venv/Scripts/python.exe -m pytest tests/ui/test_web_assets.py -q`
Expected: everything except the `app.js` checks passes. `test_the_three_assets_exist` and `test_no_file_path_fallback_anywhere` still fail because `app.js` does not exist yet. That is expected; Task 8 creates it.

- [ ] **Step 6: Commit**

```bash
git add src/thickanon/ui/web/index.html src/thickanon/ui/web/app.css tests/ui/test_web_assets.py
git commit -m "feat(ui): rebuilt page structure and light/dark stylesheet"
```

---

### Task 8: Page behaviour (`ui/web/app.js`)

**Files:**
- Create: `src/thickanon/ui/web/app.js`
- Delete: nothing (the old inline `<script>` went away with the Task 7 rewrite)

**Interfaces:**
- Consumes: the DOM ids from Task 7 and the `Api` methods from Task 5.
- Produces: `window.thickanon.on(name, payload)` - the single entry point `ui/api.py::_emit` calls. It must exist before any Python event can arrive, so it is assigned at the top of the file, not inside a load handler.
- Event names it must handle: `"progress"` with `{done, total, path, stage}`, and `"files"` with `{paths}`.

- [ ] **Step 1: Write `src/thickanon/ui/web/app.js`**

```javascript
'use strict';

// Python pushes events here from its worker threads (see ui/api.py::_emit).
// Assigned immediately so an event that arrives during start-up is not lost.
window.thickanon = {
  on: function (name, payload) {
    if (name === 'progress') { onProgress(payload); }
    else if (name === 'files') { addFiles(payload && payload.paths); }
  }
};

const $ = (id) => document.getElementById(id);

const state = {
  files: [],
  env: null,
  scanId: null,
  review: [],
  reviewTotal: 0,
  reviewTruncated: false,
  approved: new Set(),
  report: null,
  busy: false,
  startedAt: 0
};

const DETECTION_INPUTS = ['mode', 'deny', 'gliner', 'gliner-labels', 'gliner-threshold', 'gliner-gpu'];

/* ---------- small helpers ---------- */

function api() {
  return (window.pywebview && window.pywebview.api) || null;
}

function banner(message, kind) {
  const el = $('banner');
  if (!message) { el.hidden = true; el.textContent = ''; return; }
  el.textContent = message;
  el.className = 'banner' + (kind === 'info' ? ' info' : '');
  el.hidden = false;
}

function basename(path) {
  const parts = String(path).split(/[\\/]/);
  return parts[parts.length - 1] || path;
}

function setBusy(busy) {
  state.busy = busy;
  $('scan').disabled = busy;
  $('deanonymize').disabled = busy;
  $('cancel').hidden = !busy;
  $('progress').hidden = !busy;
  if (busy) {
    state.startedAt = performance.now();
    setProgress(0, 0, '', '');
  }
}

function setProgress(done, total, path, stage) {
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  $('progress-bar').style.width = pct + '%';
  const elapsed = Math.round((performance.now() - state.startedAt) / 1000);
  const verb = stage === 'apply' ? 'Writing' : stage === 'deanonymize' ? 'Restoring' : 'Scanning';
  $('progress-label').textContent = total
    ? `${verb} ${done} of ${total} (${pct}%) - ${elapsed}s`
    : `${verb}...`;
  $('progress-file').textContent = path || '';
}

function onProgress(p) {
  setProgress(p.done, p.total, p.path, p.stage);
}

/* ---------- file selection ---------- */

function addFiles(paths) {
  if (!paths || !paths.length) { return; }
  for (const p of paths) {
    if (p && state.files.indexOf(p) === -1) { state.files.push(p); }
  }
  invalidateScan();
  renderFiles();
  applyDefaults();
}

function removeFile(path) {
  state.files = state.files.filter((p) => p !== path);
  invalidateScan();
  renderFiles();
}

function renderFiles() {
  const list = $('files');
  list.textContent = '';
  for (const path of state.files) {
    const li = document.createElement('li');
    const label = document.createElement('span');
    label.textContent = basename(path);
    label.title = path;
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.textContent = '\u00d7';
    remove.setAttribute('aria-label', 'Remove ' + basename(path));
    remove.addEventListener('click', () => removeFile(path));
    li.append(label, remove);
    list.appendChild(li);
  }
  const n = state.files.length;
  $('file-count').textContent = n ? `${n} item${n === 1 ? '' : 's'} selected` : '';
  $('clear-files').hidden = n === 0;
}

async function applyDefaults() {
  if (!state.files.length || !api()) { return; }
  const res = await api().suggest_defaults(state.files, $('root').value);
  if (!res || !res.ok) { return; }
  if (!$('root').value && res.root) { $('root').value = res.root; }
  if (!$('mapping').value && res.mapping) { $('mapping').value = res.mapping; }
  if (!$('backup').value && res.backup) { $('backup').value = res.backup; }
}

/* ---------- settings ---------- */

function collectOpts() {
  return {
    files: state.files,
    root: $('root').value,
    mapping: $('mapping').value,
    mode: $('mode').value,
    deny: $('deny').value,
    backup_enabled: $('backup-enabled').checked,
    backup: $('backup').value,
    passphrase: $('pass').value,
    gliner: $('gliner').checked,
    gliner_labels: $('gliner-labels').value,
    // '' means "unset"; 0 is a real threshold and must survive.
    gliner_threshold: $('gliner-threshold').value === '' ? null : Number($('gliner-threshold').value),
    gliner_gpu: $('gliner-gpu').checked
  };
}

function persistableSettings() {
  // Only preferences. Selection-derived paths and the passphrase are excluded
  // here as well as by the allowlist in ui/api.py.
  return {
    mode: $('mode').value,
    deny: $('deny').value,
    backup_enabled: $('backup-enabled').checked,
    gliner: $('gliner').checked,
    gliner_labels: $('gliner-labels').value,
    gliner_threshold: $('gliner-threshold').value,
    gliner_gpu: $('gliner-gpu').checked,
    theme: document.documentElement.getAttribute('data-theme') || ''
  };
}

function passphraseProblem() {
  const pass = $('pass').value;
  if (!pass) { return null; }
  if (pass !== $('pass-confirm').value) {
    return 'The passphrase and its confirmation do not match.';
  }
  return null;
}

function invalidateScan() {
  state.scanId = null;
}

/* ---------- scan / apply ---------- */

async function doScan() {
  if (!state.files.length) { banner('Choose some files first.'); return; }
  const problem = passphraseProblem();
  if (problem) { banner(problem); return; }
  banner('');
  $('report').hidden = true;
  setBusy(true);
  try {
    const res = await api().scan(collectOpts());
    if (!res.ok) { banner(res.error); return; }
    state.scanId = res.scan_id;
    state.review = res.review || [];
    state.reviewTotal = res.review_total || 0;
    state.reviewTruncated = !!res.review_truncated;
    state.approved = new Set(state.review.map((c) => c.id));
    if (!$('root').value && res.root) { $('root').value = res.root; }
    for (const w of res.warnings || []) { banner(w, 'info'); }
    if (state.reviewTotal > 0) {
      openReview(res);
    } else {
      await confirmAndApply(res);
    }
  } finally {
    setBusy(false);
  }
}

function summariseScan(scan) {
  const c = scan.counts;
  const parts = [`${c.auto} certain replacement${c.auto === 1 ? '' : 's'} across ${c.files} file${c.files === 1 ? '' : 's'}`];
  if (c.review) { parts.push(`${c.review} need your decision`); }
  if (c.skipped) { parts.push(`${c.skipped} file${c.skipped === 1 ? '' : 's'} skipped`); }
  return parts.join(', ');
}

async function confirmAndApply(scan) {
  const target = $('backup-enabled').checked
    ? 'Originals are backed up first.'
    : 'Originals are overwritten with no backup.';
  const ok = window.confirm(`${summariseScan(scan)}.\n\n${target}\n\nWrite these changes now?`);
  if (!ok) { return; }
  await doApply([]);
}

async function doApply(approvedIds, approveAll) {
  if (!state.scanId) { banner('The preview expired. Scan again.'); return; }
  setBusy(true);
  try {
    const opts = collectOpts();
    opts.approve_all = !!approveAll;
    const res = await api().apply(state.scanId, approvedIds, opts);
    state.scanId = null;
    if (!res.ok) { banner(res.error); return; }
    banner('');
    renderReport(res, 'anonymize');
  } finally {
    setBusy(false);
  }
}

async function doDeanonymize() {
  if (!state.files.length) { banner('Choose some files first.'); return; }
  if (!$('mapping').value) { banner('Choose the mapping file that was saved when these files were anonymized.'); return; }
  banner('');
  $('report').hidden = true;
  setBusy(true);
  try {
    const res = await api().deanonymize(collectOpts());
    if (!res.ok) { banner(res.error); return; }
    renderReport(res, 'deanonymize');
  } finally {
    setBusy(false);
  }
}

/* ---------- review overlay ---------- */

function openReview(scan) {
  $('review-count').textContent =
    `${state.reviewTotal} detection${state.reviewTotal === 1 ? '' : 's'} were not confident enough to replace automatically. Everything ticked will be replaced.`;
  const truncated = $('review-truncated');
  if (state.reviewTruncated) {
    truncated.textContent =
      `Showing the first ${state.review.length} of ${state.reviewTotal}. "Approve all" still covers every one of them.`;
    truncated.hidden = false;
  } else {
    truncated.hidden = true;
  }
  renderReviewGroups();
  $('review').showModal();
}

function renderReviewGroups() {
  const host = $('review-groups');
  host.textContent = '';
  const groups = new Map();
  for (const c of state.review) {
    if (!groups.has(c.type)) { groups.set(c.type, []); }
    groups.get(c.type).push(c);
  }
  for (const [type, items] of [...groups.entries()].sort()) {
    const section = document.createElement('section');
    section.className = 'review-group';

    const head = document.createElement('header');
    const title = document.createElement('h3');
    title.textContent = `${type} (${items.length})`;
    const approve = document.createElement('button');
    approve.type = 'button';
    approve.className = 'btn ghost small';
    approve.textContent = 'Approve all';
    approve.addEventListener('click', () => setGroup(items, true));
    const reject = document.createElement('button');
    reject.type = 'button';
    reject.className = 'btn ghost small';
    reject.textContent = 'Reject all';
    reject.addEventListener('click', () => setGroup(items, false));
    head.append(title, approve, reject);
    section.appendChild(head);

    for (const c of items) { section.appendChild(reviewRow(c)); }
    host.appendChild(section);
  }
  updateApplyLabel();
}

function reviewRow(candidate) {
  const row = document.createElement('div');
  row.className = 'review-row';

  const box = document.createElement('input');
  box.type = 'checkbox';
  box.checked = state.approved.has(candidate.id);
  box.dataset.id = candidate.id;
  box.addEventListener('change', () => {
    if (box.checked) { state.approved.add(candidate.id); }
    else { state.approved.delete(candidate.id); }
    updateApplyLabel();
  });

  // Built with createTextNode + <mark>, never innerHTML: the snippet is file
  // content and must never be parsed as markup.
  const snippet = document.createElement('div');
  snippet.className = 'snippet';
  const text = candidate.context;
  snippet.appendChild(document.createTextNode(text.slice(0, candidate.context_start)));
  const mark = document.createElement('mark');
  mark.textContent = text.slice(candidate.context_start, candidate.context_end);
  snippet.appendChild(mark);
  snippet.appendChild(document.createTextNode(text.slice(candidate.context_end)));

  const meta = document.createElement('div');
  meta.className = 'meta';
  meta.textContent = `${Math.round(candidate.score * 100)}% - ${basename(candidate.path)}`;
  meta.title = candidate.path;

  row.append(box, snippet, meta);
  return row;
}

function setGroup(items, checked) {
  for (const c of items) {
    if (checked) { state.approved.add(c.id); } else { state.approved.delete(c.id); }
  }
  for (const box of $('review-groups').querySelectorAll('input[type="checkbox"]')) {
    if (items.some((c) => c.id === box.dataset.id)) { box.checked = checked; }
  }
  updateApplyLabel();
}

function updateApplyLabel() {
  const n = state.approved.size;
  $('review-apply').textContent = `Apply (${n} approved)`;
}

/* ---------- report ---------- */

function makeTable(table, headers, rows) {
  table.textContent = '';
  const head = table.createTHead().insertRow();
  for (const h of headers) {
    const th = document.createElement('th');
    th.textContent = h;
    head.appendChild(th);
  }
  const body = table.createTBody();
  for (const cells of rows) {
    const tr = body.insertRow();
    cells.forEach((value, i) => {
      const td = tr.insertCell();
      td.textContent = value;
      td.className = i === 0 ? 'file' : 'num';
    });
  }
}

function renderReport(res, kind) {
  state.report = res.report;
  const headline = $('report-headline');
  headline.textContent = '';

  const add = (value, label) => {
    const box = document.createElement('div');
    const b = document.createElement('b');
    b.textContent = String(value);
    const s = document.createElement('span');
    s.textContent = label;
    box.append(b, s);
    headline.appendChild(box);
  };

  const types = $('report-types');
  types.textContent = '';
  const residual = $('report-residual');

  if (kind === 'anonymize') {
    const r = res.report;
    const applied = Object.values(r.files).reduce((a, f) => a + f.applied_count, 0);
    const left = Object.values(r.files).reduce((a, f) => a + f.flagged_count, 0);
    add(applied, 'values replaced');
    add(Object.keys(r.files).length, 'files written');
    add(left, 'left in place');
    add(Object.keys(r.skipped).length, 'files skipped');

    for (const [type, n] of Object.entries(r.totals).sort()) {
      const li = document.createElement('li');
      li.textContent = `${type}: ${n}`;
      types.appendChild(li);
    }

    if (r.residual_total > 0) {
      residual.textContent =
        `${r.residual_total} value${r.residual_total === 1 ? '' : 's'} matching an email or IP pattern are still present in the written files. Review them before sharing anything.`;
      residual.hidden = false;
    } else {
      residual.hidden = true;
    }

    makeTable($('report-files'), ['File', 'Replaced', 'Left', 'Residual'],
      Object.entries(r.files).map(([p, f]) => [p, f.applied_count, f.flagged_count, f.residual_count]));

    const extra = [];
    if (res.mapping_path) { extra.push('Mapping saved to: ' + res.mapping_path); }
    if (res.backup_root) { extra.push('Originals backed up to: ' + res.backup_root); }
    banner(extra.join('   |   '), 'info');
  } else {
    const r = res.report;
    add(r.total_restored, 'values restored');
    add(Object.keys(r.files).length, 'files written');
    add(Object.keys(r.skipped).length, 'files skipped');

    const unknown = Object.entries(r.unknown_tokens);
    if (unknown.length) {
      residual.textContent =
        `${unknown.length} token${unknown.length === 1 ? '' : 's'} in these files have no entry in this mapping (${unknown.slice(0, 5).map((u) => u[0]).join(', ')}). This is usually the wrong mapping file.`;
      residual.hidden = false;
    } else {
      residual.hidden = true;
    }

    makeTable($('report-files'), ['File', 'Restored'],
      Object.entries(r.files).map(([p, n]) => [p, n]));
    banner('');
  }

  const skipped = Object.entries(res.report.skipped);
  $('report-skipped-h').hidden = skipped.length === 0;
  $('report-skipped').hidden = skipped.length === 0;
  makeTable($('report-skipped'), ['File', 'Reason'], skipped.map(([p, why]) => [p, why]));

  $('report').hidden = false;
  $('report').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function copyReport() {
  if (!state.report) { return; }
  const text = JSON.stringify(state.report, null, 2);
  try {
    await navigator.clipboard.writeText(text);
    banner('Report copied to the clipboard.', 'info');
  } catch (err) {
    // Clipboard access can be refused in an embedded webview; fall back to a
    // selection the user can copy with the keyboard.
    const area = document.createElement('textarea');
    area.value = text;
    document.body.appendChild(area);
    area.select();
    banner('Could not reach the clipboard. The report is selected - press Ctrl+C.', 'info');
    setTimeout(() => area.remove(), 15000);
  }
}

async function saveReport() {
  if (!state.report || !api()) { return; }
  const res = await api().save_report(state.report, 'thickanon-report.json');
  if (!res.ok) { banner(res.error); return; }
  if (res.path) { banner('Report saved to: ' + res.path, 'info'); }
}

/* ---------- theme ---------- */

function applyTheme(theme) {
  if (theme) { document.documentElement.setAttribute('data-theme', theme); }
  else { document.documentElement.removeAttribute('data-theme'); }
}

function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme');
  const dark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const next = current ? (current === 'dark' ? 'light' : '') : (dark ? 'light' : 'dark');
  applyTheme(next);
  saveSettings();
}

async function saveSettings() {
  if (api()) { await api().save_settings(persistableSettings()); }
}

/* ---------- start-up ---------- */

function bind() {
  $('browse-files').addEventListener('click', () => browse('files'));
  $('browse-folder').addEventListener('click', () => browse('folder'));
  $('clear-files').addEventListener('click', () => { state.files = []; invalidateScan(); renderFiles(); });
  $('choose-mapping').addEventListener('click', chooseMapping);
  $('choose-backup').addEventListener('click', chooseBackup);
  $('scan').addEventListener('click', doScan);
  $('deanonymize').addEventListener('click', doDeanonymize);
  $('cancel').addEventListener('click', () => api() && api().cancel());
  $('download-model').addEventListener('click', downloadModel);
  $('theme-toggle').addEventListener('click', toggleTheme);
  $('report-copy').addEventListener('click', copyReport);
  $('report-save').addEventListener('click', saveReport);

  $('pass').addEventListener('input', () => {
    $('pass-confirm-row').hidden = $('pass').value === '';
  });
  $('backup-enabled').addEventListener('change', () => {
    $('backup').disabled = !$('backup-enabled').checked;
    saveSettings();
  });
  for (const id of DETECTION_INPUTS) {
    $(id).addEventListener('change', () => { invalidateScan(); saveSettings(); });
  }
  $('deny').addEventListener('input', invalidateScan);

  $('review-approve-all').addEventListener('click', () => setGroup(state.review, true));
  $('review-reject-all').addEventListener('click', () => setGroup(state.review, false));
  $('review-cancel').addEventListener('click', () => $('review').close());
  $('review-apply').addEventListener('click', async () => {
    const approveAll = state.reviewTruncated && state.approved.size === state.review.length;
    $('review').close();
    await doApply([...state.approved], approveAll);
  });

  // Visual feedback only. The drop itself is handled in Python, which is the
  // only place a real filesystem path is available.
  const drop = $('drop');
  drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragenter', (e) => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', () => drop.classList.remove('over'));
}

async function browse(kind) {
  if (!api()) { return; }
  const res = kind === 'folder' ? await api().pick_folder() : await api().pick_files();
  if (res && res.ok && res.paths) { addFiles(res.paths); }
}

async function chooseMapping() {
  const suggested = $('mapping').value ? basename($('mapping').value) : 'thickanon-mapping.json';
  const res = await api().pick_mapping(suggested);
  if (res && res.ok && res.path) { $('mapping').value = res.path; }
}

async function chooseBackup() {
  const res = await api().pick_backup();
  if (res && res.ok && res.paths && res.paths.length) { $('backup').value = res.paths[0]; }
}

async function downloadModel() {
  banner('Downloading the GLiNER model. This can take several minutes.', 'info');
  const res = await api().download_model();
  banner(res.ok ? 'GLiNER model is ready.' : res.error, res.ok ? 'info' : '');
}

async function start() {
  bind();
  renderFiles();
  if (!api()) {
    banner('The Python bridge is not available. Start the app with the thickAnonymizer executable.');
    return;
  }
  const env = await api().environment();
  state.env = env;
  $('version').textContent = 'v' + env.version;

  const advanced = $('advanced');
  if (!env.gliner.available) {
    advanced.dataset.unavailable = 'true';
    $('gliner-note').textContent = env.gliner.reason;
    for (const id of ['gliner', 'gliner-labels', 'gliner-threshold', 'gliner-gpu', 'download-model']) {
      $(id).disabled = true;
    }
  } else {
    $('gliner-note').textContent = 'Slower and heavier than the default detector, but catches more names and organisations.';
  }

  const saved = await api().load_settings();
  const s = (saved && saved.settings) || {};
  if (s.mode) { $('mode').value = s.mode; }
  if (s.deny) { $('deny').value = s.deny; }
  if (s.backup_enabled === false) { $('backup-enabled').checked = false; $('backup').disabled = true; }
  if (s.gliner && env.gliner.available) { $('gliner').checked = true; }
  if (s.gliner_labels) { $('gliner-labels').value = s.gliner_labels; }
  if (s.gliner_threshold !== undefined && s.gliner_threshold !== null) {
    $('gliner-threshold').value = s.gliner_threshold;
  }
  if (s.gliner_gpu) { $('gliner-gpu').checked = true; }
  applyTheme(s.theme || '');
}

if (window.pywebview) {
  start();
} else {
  window.addEventListener('pywebviewready', start);
}
```

- [ ] **Step 2: Run the contract test**

Run: `./venv/Scripts/python.exe -m pytest tests/ui/test_web_assets.py -q`
Expected: all pass now that `app.js` exists.

- [ ] **Step 3: Run the full suite**

Run: `./venv/Scripts/python.exe -m pytest -q`
Expected: all pass.

- [ ] **Step 4: Smoke-test the real window**

Run: `./venv/Scripts/python.exe -m thickanon.ui.app`

Check, and note the result next to this step:
1. The window opens with no console errors.
2. Drag a folder onto the drop zone. The chips show real filenames, and Root / Mapping / Backup fill in with absolute paths.
3. Set mode to Quick review and press **Scan and preview**. The progress bar advances, then the review overlay lists uncertain detections with the value highlighted in its surrounding text.
4. Untick one row, press **Apply**. The report appears with per-file counts, and the unticked value is still present in the file.
5. Press **De-anonymize** with the saved mapping. The report shows the restored count.
6. Toggle the theme. Both schemes are legible.

**Observed result (2026-08-21, Task 10 documentation pass):** OUTSTANDING - not yet run.
This is an interactive manual walkthrough of the live desktop window; nobody has
performed it. Left unchecked deliberately. The automated suite and the CLI path have
been exercised (see Task 9 Step 10 below), but this interactive GUI walkthrough has not.

- [ ] **Step 5: Commit**

```bash
git add src/thickanon/ui/web/app.js
git commit -m "feat(ui): scan-review-apply flow, live progress, audit report"
```

---

### Task 9: Self-contained exe

**Files:**
- Create: `packaging/make_icon.py`
- Create: `packaging/icon.ico` (generated)
- Create: `packaging/splash.png` (generated)
- Create: `packaging/version_info.txt`
- Create: `packaging/build.ps1`
- Rewrite: `packaging/thickanon.spec`
- Create: `tests/test_packaging.py`

**Interfaces:**
- Consumes: `src/thickanon/ui/web/{index.html,app.css,app.js}` from Tasks 7-8.
- Produces: `dist/thickAnonymizer.exe`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_packaging.py`:

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "packaging" / "thickanon.spec"


def test_spec_bundles_every_web_asset():
    spec = SPEC.read_text(encoding="utf-8")
    for name in ("index.html", "app.css", "app.js"):
        assert name in spec, f"{name} is not bundled by the PyInstaller spec"


def test_spec_keeps_the_slim_build():
    spec = SPEC.read_text(encoding="utf-8")
    assert '"torch"' in spec and '"transformers"' in spec, "the slim build must keep the excludes"
    assert "console=True" in spec, "the hybrid CLI/GUI exe must stay console-subsystem"


def test_spec_wires_icon_version_and_splash():
    spec = SPEC.read_text(encoding="utf-8")
    assert "icon.ico" in spec
    assert "version_info.txt" in spec
    assert "Splash(" in spec


def test_generated_artifacts_are_committed():
    assert (ROOT / "packaging" / "icon.ico").is_file()
    assert (ROOT / "packaging" / "splash.png").is_file()
    assert (ROOT / "packaging" / "version_info.txt").is_file()


def test_every_web_asset_referenced_by_the_page_exists():
    web = ROOT / "src" / "thickanon" / "ui" / "web"
    html = (web / "index.html").read_text(encoding="utf-8")
    for name in ("app.css", "app.js"):
        assert name in html and (web / name).is_file()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./venv/Scripts/python.exe -m pytest tests/test_packaging.py -q`
Expected: failures for the missing icon, splash, version info and spec wiring.

- [ ] **Step 3: Write `packaging/make_icon.py`**

```python
"""Generate packaging/icon.ico and packaging/splash.png.

Run once; the outputs are committed so a build machine does not need Pillow:
    python packaging/make_icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
ACCENT = (37, 99, 235, 255)
INK = (255, 255, 255, 255)
SPLASH_BG = (14, 17, 23, 255)


def _font(size: int):
    for name in ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _centered(draw, box, text, font, fill):
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    x = box[0] + (box[2] - box[0] - (right - left)) / 2 - left
    y = box[1] + (box[3] - box[1] - (bottom - top)) / 2 - top
    draw.text((x, y), text, font=font, fill=fill)


def make_icon() -> Path:
    size = 256
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((8, 8, size - 8, size - 8), radius=48, fill=ACCENT)
    _centered(draw, (8, 8, size - 8, size - 8), "TA", _font(120), INK)
    out = HERE / "icon.ico"
    image.save(out, sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    return out


def make_splash() -> Path:
    width, height = 460, 280
    image = Image.new("RGBA", (width, height), SPLASH_BG)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((width / 2 - 44, 44, width / 2 + 44, 132), radius=22, fill=ACCENT)
    _centered(draw, (width / 2 - 44, 44, width / 2 + 44, 132), "TA", _font(48), INK)
    _centered(draw, (0, 150, width, 186), "thickAnonymizer", _font(26), INK)
    _centered(draw, (0, 186, width, 214), "Starting up, this takes a moment...",
              _font(14), (151, 161, 176, 255))
    out = HERE / "splash.png"
    image.convert("RGB").save(out)
    return out


if __name__ == "__main__":
    print(make_icon())
    print(make_splash())
```

- [ ] **Step 4: Generate the artefacts**

Run: `./venv/Scripts/python.exe packaging/make_icon.py`
Expected: prints the two paths; `packaging/icon.ico` and `packaging/splash.png` now exist.

- [ ] **Step 5: Write `packaging/version_info.txt`**

```python
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=(0, 1, 0, 0),
    prodvers=(0, 1, 0, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0),
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', 'Alex Schick'),
        StringStruct('FileDescription', 'thickAnonymizer - mass file anonymizer'),
        StringStruct('FileVersion', '0.1.0.0'),
        StringStruct('InternalName', 'thickAnonymizer'),
        StringStruct('LegalCopyright', 'MIT License. Copyright 2026 Alex Schick.'),
        StringStruct('OriginalFilename', 'thickAnonymizer.exe'),
        StringStruct('ProductName', 'thickAnonymizer'),
        StringStruct('ProductVersion', '0.1.0.0'),
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
```

- [ ] **Step 6: Rewrite `packaging/thickanon.spec`**

```python
# packaging/thickanon.spec
# Build: pyinstaller packaging/thickanon.spec   (or packaging/build.ps1)
#
# Produces a single hybrid exe (dist/thickAnonymizer.exe):
#   - double-click / no args  -> desktop GUI (console hidden on launch)
#   - `thickAnonymizer.exe anonymize ...` / `anon ...` etc. -> CLI
# Built as a console-subsystem exe so CLI stdio, piping and exit codes work;
# the GUI path hides the console window (see thickanon/__main__.py).
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

# Paths in a .spec are resolved relative to the spec file's directory, so anchor
# everything to the project root (the parent of packaging/) via SPECPATH.
ROOT = os.path.dirname(os.path.abspath(SPECPATH))
SRC = os.path.join(ROOT, "src")
PKG = os.path.join(ROOT, "packaging")

datas, binaries, hiddenimports = [], [], []
for pkg in ["en_core_web_lg", "presidio_analyzer", "presidio_anonymizer"]:
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

# Optional GLiNER backend: bundle the gliner package (and its CPU torch/transformers/
# onnxruntime deps) only if installed. The default build excludes torch/transformers
# (see _EXCLUDES) for a slim CPU-only exe; to ship GLiNER, install the [gliner] extra
# AND remove "torch"/"transformers" from _EXCLUDES before building.
try:
    for _pkg in ("gliner", "onnxruntime"):
        _d, _b, _h = collect_all(_pkg)
        datas += _d; binaries += _b; hiddenimports += _h
except Exception:
    pass

# ensure all of our own modules are bundled (the entry imports them lazily)
hiddenimports += collect_submodules("thickanon")

# bundle the web UI: every asset the page links to must be listed here, or the
# exe ships an unstyled, inert window.
_WEB = os.path.join(SRC, "thickanon", "ui", "web")
datas += [
    (os.path.join(_WEB, "index.html"), "thickanon/ui/web"),
    (os.path.join(_WEB, "app.css"), "thickanon/ui/web"),
    (os.path.join(_WEB, "app.js"), "thickanon/ui/web"),
]

# torch is present in the dev env (so thinc auto-registers it), but the
# en_core_web_lg CNN pipeline runs on thinc/numpy and does not need it for
# inference. Excluding the torch + CUDA stack drops ~2GB; thinc falls back
# cleanly when torch is unimportable.
_EXCLUDES = [
    "torch", "torchvision", "torchaudio", "torchgen", "functorch",
    "nvidia", "triton", "transformers",
]

a = Analysis([os.path.join(SRC, "thickanon/__main__.py")], pathex=[SRC], datas=datas,
             binaries=binaries, hiddenimports=hiddenimports, excludes=_EXCLUDES)
pyz = PYZ(a.pure)

# A one-file exe of this size takes roughly 15 seconds to unpack before any of
# our code runs. Without a splash a double-click looks like nothing happened.
# ui/app.py closes it once the window has loaded.
splash = Splash(
    os.path.join(PKG, "splash.png"),
    binaries=a.binaries,
    datas=a.datas,
    text_pos=None,
)

exe = EXE(pyz, a.scripts, splash, splash.binaries, a.binaries, a.datas,
          name="thickAnonymizer",
          console=True,
          icon=os.path.join(PKG, "icon.ico"),
          version=os.path.join(PKG, "version_info.txt"))
```

- [ ] **Step 7: Write `packaging/build.ps1`**

```powershell
#Requires -Version 5.1
<#
  Build the self-contained Windows exe.
      .\packaging\build.ps1
  Prints the resulting path, size and SHA256 so a shared copy can be verified.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root 'venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    throw "No virtualenv at $python. Create one and run: pip install -e `".[dev]`""
}

if (-not (Test-Path (Join-Path $root 'packaging\icon.ico'))) {
    Write-Host 'Generating icon and splash...'
    & $python (Join-Path $root 'packaging\make_icon.py')
}

Write-Host 'Cleaning previous build...'
foreach ($stale in @('build\thickanon', 'dist\thickAnonymizer.exe')) {
    $path = Join-Path $root $stale
    if (Test-Path $path) { Remove-Item -Recurse -Force $path }
}

Write-Host 'Running PyInstaller (this takes several minutes)...'
& $python -m PyInstaller --noconfirm (Join-Path $root 'packaging\thickanon.spec')
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

$exe = Join-Path $root 'dist\thickAnonymizer.exe'
if (-not (Test-Path $exe)) { throw "Build reported success but $exe is missing" }

$sizeMb = [math]::Round((Get-Item $exe).Length / 1MB, 1)
$hash = (Get-FileHash $exe -Algorithm SHA256).Hash

Write-Host ''
Write-Host "Built:  $exe"
Write-Host "Size:   $sizeMb MB"
Write-Host "SHA256: $hash"
```

- [ ] **Step 8: Run the packaging test**

Run: `./venv/Scripts/python.exe -m pytest tests/test_packaging.py -q`
Expected: all pass.

- [x] **Step 9: Build the exe**

Run: `powershell -ExecutionPolicy Bypass -File packaging\build.ps1`
Expected: `dist/thickAnonymizer.exe` exists; the script prints its size (roughly 590 MB) and SHA256.

If PyInstaller reports `Splash` is undefined, the installed PyInstaller predates splash support. Check with `./venv/Scripts/python.exe -m PyInstaller --version` (6.22.2 supports it) before changing the spec.

**Observed result:** Built successfully. `dist/thickAnonymizer.exe` exists at
**488.2 MB** (not the ~590 MB estimated above; that figure was an estimate and the
measured size is the one to trust going forward). SHA256:
`5018B0E45A77D99A2E1CA8344C2D79197CBB5CC699B5097D8FCD2B314531750F`.

- [x] **Step 10: Smoke-test the exe**

Run each of these and record the result next to this step:

```
dist\thickAnonymizer.exe --help
dist\thickAnonymizer.exe anon _sandbox\data --root _sandbox\data --mapping _sandbox\keys\m.json --mode auto_redact
```

Expected: the CLI prints help and then a report, the shell waits for it, and the exit code is 0.

Then double-click `dist\thickAnonymizer.exe` in Explorer. Expected: the splash appears within a second or two, the window replaces it, no console window remains, and a scan/review/apply cycle works exactly as it did from the checkout.

**Observed result:** CLI half PASSED - `--help`, `anon` and `deanon` all exit 0 from the
built exe, and a round-trip anonymize/de-anonymize restored every token. GUI half
OUTSTANDING - the double-click launch of `dist\thickAnonymizer.exe` has not been
performed by anyone; this is the one thing about the packaged app that remains
unverified. Do not treat the desktop window as confirmed working from the exe until
someone actually runs this step.

- [ ] **Step 11: Commit**

```bash
git add packaging tests/test_packaging.py
git commit -m "build: icon, version resource, splash screen and one-command build"
```

---

### Task 10: Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-08-21-ui-modernization.md` (tick the manual steps with their observed results)

- [ ] **Step 1: Rewrite the README's Desktop app section**

Replace the existing "## Desktop app" section with:

```markdown
## Desktop app

    python -m thickanon.ui.app

Or double-click `thickAnonymizer.exe`.

The app works in three steps.

1. **Choose files.** Drag files or a folder onto the window, or use
   **Browse files... / Browse folder...**. **Root folder**, **Mapping file** and
   **Backup folder** fill in automatically, always placed *beside* the root and
   never inside it.
2. **Scan and preview.** Nothing is written yet. The app reads and analyses every
   file and tells you what it found. In **Quick review** mode, detections it is not
   confident about are listed with the value highlighted in its surrounding text, so
   you approve or reject them in one pass.
3. **Apply.** The approved replacements are written, originals are copied to the
   backup folder first, and the mapping is saved. The report shows per-file counts,
   skipped files with reasons, and a loud warning if any email or IP pattern survived
   into the written files.

**De-anonymize** takes the AI's output plus the mapping file and restores the real
values. It reports how many tokens it restored, and warns when a file contains tokens
this mapping does not know about, which almost always means the wrong mapping file.

Backups are **on by default**. Files are edited in place, so with backups off the
originals are gone.

### Requirements for the exe

The desktop window needs the **Microsoft Edge WebView2 Runtime**, which ships with
Windows 11 and current Windows 10. If it is missing, the app says so and links to the
download instead of opening a broken window. The command-line mode does not need it.
```

- [ ] **Step 2: Update the build section of the README**

Replace the "## Build a Windows .exe" section with:

```markdown
## Build a Windows .exe (single hybrid binary)

    .\packaging\build.ps1
    # dist/thickAnonymizer.exe  (about 590 MB)

The script cleans the previous build, runs PyInstaller, and prints the size and SHA256
of the result so a shared copy can be verified. `pyinstaller packaging/thickanon.spec`
still works if you prefer to drive it yourself.

One exe does **both** roles, dispatching on its arguments (`thickanon/__main__.py`):

- **Double-click** (no arguments) -> a splash appears while the one-file archive
  unpacks, then the desktop **GUI**. The exe is a console binary, so a console window
  flashes briefly and is then hidden; only the app window remains.
- **From a terminal** with arguments -> the **CLI**, e.g.
  `thickAnonymizer.exe anon C:\data --root C:\data --mapping C:\keys\map.json --mode auto_redact`.
  Because it is a console-subsystem exe, the shell waits for it, stdout/stderr pipe and
  redirect normally, and the exit code propagates.

The spaCy model, the web UI and the splash are bundled inside the exe; no Python install
is needed on the target machine.

The build excludes the PyTorch/CUDA stack: the `en_core_web_lg` pipeline is a CNN model
that runs on thinc/numpy, so torch is unused for inference and dropping it takes the exe
from ~3.1 GB to under 600 MB. The default exe therefore ships the **regex + spaCy**
detector only, and the app's neural-NER controls are disabled with an explanation rather
than failing at run time. To bundle the **optional GLiNER** backend, install the
`[gliner]` extra and remove `"torch"`/`"transformers"` from `_EXCLUDES` in
`packaging/thickanon.spec` before building - the exe will grow accordingly.
```

- [ ] **Step 3: Correct the Known limitations section**

In `## Known limitations`, replace the first two bullets with:

```markdown
- **Residual leaks are REPORTED, not blocked:** in `auto_skip` mode and in non-interactive
  `quick_review`, the output file may still contain low-confidence PII. Check the report's
  residual-leak warning before sharing anything.
- **CLI `quick_review` (the default) drops uncertain detections** because there is no
  interactive reviewer on the CLI; use `--mode auto_redact` or the desktop app, which
  lists them for approval.
```

And add:

```markdown
- **The desktop app holds the extracted text of the whole selection in memory** while
  you preview it. It warns above roughly 200 MB of text; anonymize very large trees in
  batches.
```

- [ ] **Step 4: Run the full suite one last time**

Run: `./venv/Scripts/python.exe -m pytest -q`
Expected: every test passes. Record the exact count.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/superpowers/plans/2026-08-21-ui-modernization.md
git commit -m "docs: desktop app walkthrough, build script, corrected limitations"
```

---

## Self-review notes

**Spec coverage:**

| Spec section | Task |
|---|---|
| D1 broken drag-and-drop | 6 (`dropped_paths`, native drop wiring), 8 (visual state only), 7 (`#drop`) |
| D2 quick_review does nothing | 1, 2 (bands + apply), 5 (`scan`/`apply`), 8 (review overlay) |
| D3 GLiNER trap in the exe | 5 (`gliner_availability`), 8 (disabled controls + reason) |
| D4 relative backup path | 4 (`resolve_backup_root`, `ensure_backup_outside_root`), 5 (wiring), 7 (default on) |
| D5 threshold 0 becomes 0.5 | 5 (`_config_from`), 8 (`collectOpts` sends null, not 0-as-falsy) |
| D6 mapping dialog name | 8 (`chooseMapping` passes the derived basename) |
| D7 no progress or cancel | 1, 2, 3 (progress/cancel params), 5 (`_emit`), 7 (`#progress`), 8 (`onProgress`) |
| D8 report discarded | 7 (`#report`), 8 (`renderReport`) |
| D9 de-anonymize reports nothing | 3 (`DeanonReport`), 8 |
| D10 no passphrase confirmation | 7 (`#pass-confirm`), 8 (`passphraseProblem`) |
| D11 no settings persistence | 5 (`load_settings`/`save_settings`), 8 |
| D12 WebView2 fallback | 6 (`webview2_present`) |
| Spec 4.1-4.3 two-phase + wrapper | 1, 2 |
| Spec 4.4 de-anonymize report | 3 |
| Spec 5 API surface | 5 |
| Spec 6 page and styling | 7, 8 |
| Spec 7 packaging | 9 |
| Spec 8 preflight | 6 |
| Spec 9 error handling | 1, 2, 3 (per-file skips, cancel), 5 (stale scan_id, ok/error contract) |
| Spec 10 testing | every task; regression gate stated in Global Constraints |
| Spec 11 trade-offs | 1 (`warnings()` for memory), 9 (splash), 8 (confirm click) |

**Type consistency check:** `Candidate.id` / `.band` / `.to_dict()` keys are defined in Task 1 and consumed unchanged in Tasks 2, 5 and 8. `progress(done, total, path, stage)` has the same four positional parameters in `scan_paths` (Task 1), `apply_scan` (Task 2), `deanonymize_paths` (Task 3), `Api._progress` (Task 5) and `onProgress` (Task 8). `apply_scan(scan, mapping, approved_ids, backup_root, progress, cancel)` is called with that exact order in Task 2's wrapper and Task 5's `Api.apply`. `BatchReport.to_dict()` keys (`totals`, `files`, `skipped`, `residual_total`) and `files[path]` keys (`applied_count`, `flagged_count`, `residual_count`) come from the existing `core/report.py` and are read with those names in Task 8. `DeanonReport.to_dict()` keys (`files`, `unknown_tokens`, `skipped`, `total_restored`) are defined in Task 3 and read in Task 8.

**Known ordering constraint:** Task 7's contract test fails on two assertions until Task 8 lands. That is stated in Task 7 Step 5 rather than hidden, so an executor does not treat it as a defect.
