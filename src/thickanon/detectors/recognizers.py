from presidio_analyzer import Pattern, PatternRecognizer, EntityRecognizer, RecognizerResult

_IPV4 = r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"
# FQDN: at least two dot-separated labels ending in a 2+ letter TLD
_FQDN = r"\b(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}\b"
_EMAIL = r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b"
_IBAN = r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"

def _luhn_ok(number: str) -> bool:
    digits = [int(c) for c in number if c.isdigit()]
    if len(digits) < 13:
        return False
    total, parity = 0, len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0

class CreditCardRecognizer(EntityRecognizer):
    """Regex candidate + Luhn validation to cut false positives."""
    PATTERN = r"\b(?:\d[ -]?){13,19}\b"

    def __init__(self):
        super().__init__(supported_entities=["CREDIT_CARD"], name="LuhnCardRecognizer")

    def load(self):  # required hook, nothing to load
        pass

    def analyze(self, text, entities, nlp_artifacts=None):
        import re
        results = []
        for m in re.finditer(self.PATTERN, text):
            candidate = m.group()
            if _luhn_ok(candidate):
                results.append(
                    RecognizerResult("CREDIT_CARD", m.start(), m.end(), 0.9)
                )
        return results

def custom_recognizers() -> list:
    return [
        PatternRecognizer(
            supported_entity="IP",
            name="IpRecognizer",
            patterns=[Pattern("ipv4", _IPV4, 0.85)],
        ),
        PatternRecognizer(
            supported_entity="HOST",
            name="FqdnRecognizer",
            patterns=[Pattern("fqdn", _FQDN, 0.6)],
        ),
        PatternRecognizer(
            supported_entity="EMAIL_ADDRESS",
            name="EmailRecognizer",
            patterns=[Pattern("email", _EMAIL, 0.9)],
        ),
        PatternRecognizer(
            supported_entity="IBAN_CODE",
            name="IbanRecognizer",
            patterns=[Pattern("iban", _IBAN, 0.8)],
        ),
        CreditCardRecognizer(),
    ]
