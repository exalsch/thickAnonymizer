from thickanon.core.residual import residual_scan

def test_flags_leftover_ip_and_email():
    findings = residual_scan("clean [PERSON_1] but 10.0.0.9 and bob@x.com slipped")
    types = {f.entity_type for f in findings}
    assert "IP" in types and "EMAIL_ADDRESS" in types

def test_ignores_tokens_themselves():
    assert residual_scan("all good [PERSON_1] [IP_2] [HOST_3]") == []
