from functools import lru_cache
from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
from thickanon.core.types import AnonymizeConfig, Entity
from thickanon.detectors.normalize import normalize_type
from thickanon.detectors.recognizers import custom_recognizers, deny_list_recognizer


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
        Entity(r.start, r.end, normalize_type(r.entity_type), r.score, text[r.start:r.end])
        for r in resolved
    ]
