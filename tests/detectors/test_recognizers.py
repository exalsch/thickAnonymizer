from thickanon.detectors.recognizers import custom_recognizers

def _find(text, want_label):
    types = set()
    for rec in custom_recognizers():
        for res in rec.analyze(text, entities=rec.supported_entities, nlp_artifacts=None):
            types.add(res.entity_type)
    return want_label in types

def test_detects_ipv4():
    assert _find("server at 10.20.30.40 is down", "IP")

def test_detects_fqdn():
    assert _find("connect to db01.prod.acme.local now", "HOST")

def test_detects_email():
    assert _find("mail me at jane.doe@acme.com", "EMAIL_ADDRESS")

def test_credit_card_luhn_pass():
    assert _find("card 4539578763621486 expires soon", "CREDIT_CARD")

def test_credit_card_luhn_reject():
    # not a valid Luhn number -> should NOT be flagged as credit card
    assert not _find("ref 4539578763621487 here", "CREDIT_CARD")
