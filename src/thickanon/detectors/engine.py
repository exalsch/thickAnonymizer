from functools import lru_cache
from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
from thickanon.core.types import AnonymizeConfig, Entity
from thickanon.detectors.recognizers import custom_recognizers, deny_list_recognizer

_TYPE_NORMALIZE = {
    "EMAIL_ADDRESS": "EMAIL",
    "IP_ADDRESS": "IP",      # Presidio's builtin IPv6/IPv4 -> align with our custom IP
    "IBAN_CODE": "IBAN",
    "PHONE_NUMBER": "PHONE",
    "DENY": "TERM",          # deny-list hits read as [TERM_1]
}


@lru_cache(maxsize=4)
def _base_analyzer(language: str) -> AnalyzerEngine:
    registry = RecognizerRegistry()
    registry.load_predefined_recognizers(languages=[language])
    for rec in custom_recognizers():
        registry.add_recognizer(rec)
    return AnalyzerEngine(registry=registry, supported_languages=[language])


def _resolve_overlaps(results) -> list:
    """Keep highest-score span; drop spans contained in / overlapping a kept one."""
    ordered = sorted(results, key=lambda r: (-r.score, r.start, -(r.end - r.start)))
    kept = []
    for r in ordered:
        if any(not (r.end <= k.start or r.start >= k.end) for k in kept):
            continue  # overlaps an already-kept higher-score span
        kept.append(r)
    return sorted(kept, key=lambda r: r.start)


def detect(text: str, config: AnonymizeConfig) -> list[Entity]:
    analyzer = _base_analyzer(config.language)
    ad_hoc = [deny_list_recognizer(config.deny_list)] if config.deny_list else []
    raw = analyzer.analyze(
        text=text, language=config.language, ad_hoc_recognizers=ad_hoc
    )
    raw = [r for r in raw if r.score >= config.low_threshold]
    resolved = _resolve_overlaps(raw)
    return [
        Entity(r.start, r.end, _TYPE_NORMALIZE.get(r.entity_type, r.entity_type), r.score, text[r.start:r.end])
        for r in resolved
    ]
