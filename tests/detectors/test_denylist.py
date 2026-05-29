from thickanon.detectors.recognizers import deny_list_recognizer

def test_denylist_matches_exact_terms():
    rec = deny_list_recognizer(["Project Falcon", "acme"])
    res = rec.analyze("Project Falcon ships at acme next week",
                      entities=["DENY"], nlp_artifacts=None)
    matched = sorted(r.entity_type for r in res)
    assert matched == ["DENY", "DENY"]
    assert all(r.score >= 0.99 for r in res)

def test_denylist_empty_is_safe():
    rec = deny_list_recognizer([])
    assert rec.analyze("nothing here", entities=["DENY"], nlp_artifacts=None) == []
