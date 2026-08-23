from functools import lru_cache
from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
from thickanon.core.types import AnonymizeConfig, Entity
from thickanon.detectors.normalize import normalize_type
from thickanon.detectors.recognizers import custom_recognizers, deny_list_recognizer
from thickanon.detectors import gliner_model
from thickanon.detectors.gliner import gliner_detect, iter_chunks

# Presidio's pipeline is superlinear in document length: 80 KB takes about
# 3x as long as 40 KB. Analysing in overlapping windows is 2.7x faster on
# an 80 KB input and finds the same entities.
MAX_ANALYZE_CHARS = 4000
_CHUNK_OVERLAP = 200


@lru_cache(maxsize=4)
def _base_analyzer(language: str) -> AnalyzerEngine:
    registry = RecognizerRegistry()
    registry.load_predefined_recognizers(languages=[language])
    for rec in custom_recognizers():
        registry.add_recognizer(rec)
    return AnalyzerEngine(registry=registry, supported_languages=[language])


# When two candidates tie on score for the same span, prefer the recogniser
# that is specific about what it matched. A structured pattern like an IP or
# an IBAN knows what it found; DATE_TIME matching a bare ticket number does
# not. Lower sorts first, so lower wins.
_TYPE_PRIORITY = {
    "EMAIL": 0,
    "IP": 0,
    "IBAN": 0,
    "CREDIT_CARD": 0,
    "HOST": 1,
    "PHONE": 1,
    "TERM": 0,
    "PERSON": 2,
    "LOCATION": 3,
    "ORGANIZATION": 3,
    "DATE_TIME": 5,
}
_DEFAULT_PRIORITY = 4


def _resolve_overlaps(results) -> list:
    """Keep highest-score span; drop spans contained in / overlapping a kept one.

    Kept spans never overlap each other, so once they are held in start
    order only the neighbours around a candidate's insertion point can
    conflict with it. That keeps this O(n log n) rather than O(n^2), which
    matters because entity counts scale with document size.
    """
    import bisect

    ordered = sorted(
        results,
        key=lambda r: (
            -r.score,
            _TYPE_PRIORITY.get(r.entity_type, _DEFAULT_PRIORITY),
            r.start,
            -(r.end - r.start),
        ),
    )
    starts, kept = [], []
    for r in ordered:
        i = bisect.bisect_left(starts, r.start)
        clash = False
        for j in (i - 1, i):
            if 0 <= j < len(kept):
                k = kept[j]
                if not (r.end <= k.start or r.start >= k.end):
                    clash = True
                    break
        if clash:
            continue
        starts.insert(i, r.start)
        kept.insert(i, r)
    return kept


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


def _detect_once(text: str, config: AnonymizeConfig) -> list[Entity]:
    if config.gliner is not None and config.gliner.enabled:
        entities = _regex_denylist_entities(text, config)
        model = gliner_model.load_model(config.gliner)
        entities += gliner_detect(text, config.gliner, model)
    else:
        analyzer = _base_analyzer(config.language)
        ad_hoc = [deny_list_recognizer(config.deny_list)] if config.deny_list else []
        raw = analyzer.analyze(text=text, language=config.language, ad_hoc_recognizers=ad_hoc)
        entities = [Entity(r.start, r.end, normalize_type(r.entity_type), r.score,
                           text[r.start:r.end]) for r in raw]
    entities = [e for e in entities if e.score >= config.low_threshold]
    return _resolve_overlaps(entities)


def detect(text: str, config: AnonymizeConfig, progress=None) -> list[Entity]:
    """Detect entities, analysing long text in overlapping windows.

    progress(done_chunks, total_chunks) is called after each window so a
    caller can report movement while one large file is being scanned.
    """
    if len(text) <= MAX_ANALYZE_CHARS:
        entities = _detect_once(text, config)
        if progress is not None:
            progress(1, 1)
        return entities

    chunks = iter_chunks(text, MAX_ANALYZE_CHARS, _CHUNK_OVERLAP)
    seen, entities = set(), []
    for index, (base, chunk) in enumerate(chunks, start=1):
        for entity in _detect_once(chunk, config):
            # The windows overlap, so the same span can be found twice.
            key = (entity.entity_type, base + entity.start, base + entity.end)
            if key in seen:
                continue
            seen.add(key)
            entities.append(
                Entity(base + entity.start, base + entity.end,
                       entity.entity_type, entity.score, entity.text)
            )
        if progress is not None:
            progress(index, len(chunks))
    return _resolve_overlaps(entities)
