from thickanon.detectors.normalize import normalize_type


def test_known_aliases():
    assert normalize_type("EMAIL_ADDRESS") == "EMAIL"
    assert normalize_type("IP_ADDRESS") == "IP"
    assert normalize_type("DENY") == "TERM"


def test_unknown_passthrough():
    assert normalize_type("PERSON") == "PERSON"


def test_spaces_and_case_normalized():
    assert normalize_type("Job Title") == "JOB_TITLE"
