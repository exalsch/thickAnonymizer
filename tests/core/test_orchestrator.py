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
    assert "[EMAIL_ADDRESS_1]" in out and "[IP_1]" in out
    assert report.totals["EMAIL_ADDRESS"] == 1

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
