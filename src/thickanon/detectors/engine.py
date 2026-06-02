from functools import lru_cache
from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
from thickanon.core.types import AnonymizeConfig, Entity
from thickanon.detectors.normalize import normalize_type
from thickanon.detectors.recognizers import custom_recognizers, deny_list_recognizer
from thickanon.detectors import llm_model
from thickanon.detectors.llm import llm_detect


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


def _regex_denylist_entities(text: str, config) -> list[Entity]:
    """Run custom regex recognizers + deny-list directly (no spaCy NLP)."""
    results = []
    for rec in custom_recognizers():
        results += rec.analyze(text, rec.supported_entities, None)
    if config.deny_list:
        dl = deny_list_recognizer(config.deny_list)
        results += dl.analyze(text, ["DENY"], None)
    return [Entity(r.start, r.end, normalize_type(r.entity_type), r.score,
                   text[r.start:r.end]) for r in results]


def detect(text: str, config: AnonymizeConfig) -> list[Entity]:
    if config.llm is not None and config.llm.enabled:
        entities = _regex_denylist_entities(text, config)
        runner = llm_model.load_runner(config.llm)
        entities += llm_detect(text, config.llm, runner)
    else:
        analyzer = _base_analyzer(config.language)
        ad_hoc = [deny_list_recognizer(config.deny_list)] if config.deny_list else []
        raw = analyzer.analyze(text=text, language=config.language, ad_hoc_recognizers=ad_hoc)
        entities = [Entity(r.start, r.end, normalize_type(r.entity_type), r.score,
                           text[r.start:r.end]) for r in raw]
    entities = [e for e in entities if e.score >= config.low_threshold]
    return _resolve_overlaps(entities)
