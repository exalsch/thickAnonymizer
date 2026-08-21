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


def test_apply_refuses_a_file_that_changed_since_the_scan(tmp_path):
    f = _write(tmp_path / "note.txt", "ping 10.0.0.5")
    scan = scan_paths([f], tmp_path, AnonymizeConfig(mode=ReviewMode.AUTO_REDACT))
    # the user edits the file while the preview is on screen
    _write(tmp_path / "note.txt", "a much longer edit the user made, no PII here")

    report = apply_scan(scan, MappingStore())

    assert f.read_text(encoding="utf-8") == "a much longer edit the user made, no PII here"
    assert "changed on disk" in report.skipped[str(f)]
    assert str(f) not in report.files


def test_apply_does_not_recreate_a_file_deleted_after_the_scan(tmp_path):
    f = _write(tmp_path / "note.txt", "ping 10.0.0.5")
    scan = scan_paths([f], tmp_path, AnonymizeConfig(mode=ReviewMode.AUTO_REDACT))
    f.unlink()

    report = apply_scan(scan, MappingStore())

    assert not f.exists()
    assert "changed on disk" in report.skipped[str(f)]
