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
