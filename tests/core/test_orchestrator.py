from pathlib import Path
from thickanon.core.types import AnonymizeConfig, ReviewMode
from thickanon.core.mapping import MappingStore
from thickanon.core.orchestrator import anonymize_paths, deanonymize_paths


def test_anonymize_then_deanonymize_roundtrip(tmp_path):
    root = tmp_path
    f = root / "note.txt"
    f.write_text("Email jane@acme.com from host 10.0.0.5", encoding="utf-8")

    cfg = AnonymizeConfig(mode=ReviewMode.AUTO_REDACT)
    mapping = MappingStore()
    report = anonymize_paths([f], root, mapping, cfg)

    out = f.read_text(encoding="utf-8")
    assert "jane@acme.com" not in out and "10.0.0.5" not in out
    assert "[EMAIL_1]" in out and "[IP_1]" in out
    assert report.totals["EMAIL"] == 1

    deanonymize_paths([f], mapping)
    assert f.read_text(encoding="utf-8") == "Email jane@acme.com from host 10.0.0.5"


def test_unsupported_file_skipped(tmp_path):
    img = tmp_path / "pic.png"; img.write_bytes(b"\x89PNG")
    report = anonymize_paths([img], tmp_path, MappingStore(), AnonymizeConfig())
    assert str(img) in report.skipped


def test_backup_created_when_requested(tmp_path):
    f = tmp_path / "a.txt"; f.write_text("John here", encoding="utf-8")
    backup_root = tmp_path / ".backup"
    anonymize_paths([f], tmp_path, MappingStore(),
                    AnonymizeConfig(mode=ReviewMode.AUTO_REDACT), backup_root=backup_root)
    assert (backup_root / "a.txt").read_text(encoding="utf-8") == "John here"


def test_failing_file_is_recorded_and_batch_continues(tmp_path, monkeypatch):
    # A file that errors during processing must not abort the batch; it should be
    # recorded as skipped and the remaining files still anonymized.
    bad = tmp_path / "bad.txt"; bad.write_text("John here", encoding="utf-8")
    good = tmp_path / "good.txt"; good.write_text("ping 10.0.0.9", encoding="utf-8")

    import thickanon.io.text as text_handler
    real_read = text_handler.read_fragments

    def flaky_read(path):
        if Path(path).name == "bad.txt":
            raise OSError("boom")
        return real_read(path)

    monkeypatch.setattr(text_handler, "read_fragments", flaky_read)

    cfg = AnonymizeConfig(mode=ReviewMode.AUTO_REDACT)
    report = anonymize_paths([bad, good], tmp_path, MappingStore(), cfg)

    assert str(bad) in report.skipped
    assert "boom" in report.skipped[str(bad)]
    # the good file was still processed despite the bad one failing first
    assert "10.0.0.9" not in good.read_text(encoding="utf-8")
    assert str(good) in report.files
