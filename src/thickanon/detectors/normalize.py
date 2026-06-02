_TYPE_NORMALIZE = {
    "EMAIL_ADDRESS": "EMAIL",
    "IP_ADDRESS": "IP",
    "IBAN_CODE": "IBAN",
    "DENY": "TERM",
}


def normalize_type(t: str) -> str:
    """Map a detector's raw entity type to the readable token vocabulary."""
    canonical = t.strip().upper().replace(" ", "_")
    return _TYPE_NORMALIZE.get(canonical, canonical)
