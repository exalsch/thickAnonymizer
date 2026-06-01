from thickanon.core.types import Entity
from thickanon.core.report import BatchReport


def test_report_counts_and_flags():
    r = BatchReport()
    r.record_file("a.txt", applied=[Entity(0,1,"PERSON",0.9,"x"), Entity(2,3,"IP",0.9,"y")],
                  flagged=[Entity(4,5,"PERSON",0.5,"z")], residual=[])
    r.record_skip("photo.png", "unsupported: .png")
    d = r.to_dict()
    assert d["totals"]["PERSON"] == 2  # 1 applied + 1 flagged counts toward found
    assert d["totals"]["IP"] == 1
    assert d["files"]["a.txt"]["flagged_count"] == 1
    assert d["skipped"] == {"photo.png": "unsupported: .png"}
    assert "PERSON" in r.summary()  # human-readable string
