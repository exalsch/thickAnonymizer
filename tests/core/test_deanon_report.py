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
