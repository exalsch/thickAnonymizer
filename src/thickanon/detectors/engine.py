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


def _gliner_enabled(config: AnonymizeConfig) -> bool:
    return config.gliner is not None and config.gliner.enabled


def _detect_once(text: str, config: AnonymizeConfig, progress=None) -> list[Entity]:
    if _gliner_enabled(config):
        entities = _regex_denylist_entities(text, config)
        model = gliner_model.load_model(config.gliner)
        entities += gliner_detect(text, config.gliner, model, progress)
    else:
        entities = _analyze_spacy(text, config)
    return _keep(entities, config)


def _keep(entities, config) -> list[Entity]:
    return _resolve_overlaps([e for e in entities if e.score >= config.low_threshold])


def _ad_hoc(config):
    return [deny_list_recognizer(config.deny_list)] if config.deny_list else []


def _analyze_spacy(text, config, nlp_artifacts=None, ad_hoc=None) -> list[Entity]:
    analyzer = _base_analyzer(config.language)
    raw = analyzer.analyze(text=text, language=config.language,
                           ad_hoc_recognizers=_ad_hoc(config) if ad_hoc is None else ad_hoc,
                           nlp_artifacts=nlp_artifacts)
    return [Entity(r.start, r.end, normalize_type(r.entity_type), r.score,
                   text[r.start:r.end]) for r in raw]


def _windows(text):
    """The (base, window) pairs detect() analyses a text in."""
    if len(text) <= MAX_ANALYZE_CHARS:
        return [(0, text)]
    return iter_chunks(text, MAX_ANALYZE_CHARS, _CHUNK_OVERLAP)


def _merge_windows(per_window) -> list[Entity]:
    """Combine the entities of one text's windows: [(base, entities), ...]."""
    if len(per_window) == 1 and per_window[0][0] == 0:
        return per_window[0][1]
    seen, entities = set(), []
    for base, found in per_window:
        for entity in found:
            # The windows overlap, so the same span can be found twice.
            key = (entity.entity_type, base + entity.start, base + entity.end)
            if key in seen:
                continue
            seen.add(key)
            entities.append(
                Entity(base + entity.start, base + entity.end,
                       entity.entity_type, entity.score, entity.text)
            )
    return _resolve_overlaps(entities)


# spaCy's fixed cost per call dominates for short texts such as spreadsheet
# cells. 128 texts per batch measured best (docs/reviews/2026-11-23-performance-review.md).
_BATCH_SIZE = 128


def detect_many(texts, config: AnonymizeConfig, progress=None) -> list[list[Entity]]:
    """detect() for each text, with all windows of all texts in one spaCy batch.

    Returns exactly what [detect(t, config) for t in texts] returns. The
    recognizers and the context enhancer get the same spaCy output as in a
    single call; only the number of calls into spaCy changes.
    progress(done_windows, total_windows) is called as the windows complete.
    """
    texts = list(texts)
    if _gliner_enabled(config):
        results = []
        for index, text in enumerate(texts, start=1):
            results.append(detect(text, config))
            if progress is not None:
                progress(index, len(texts))
        return results

    jobs = [(i, base, window) for i, text in enumerate(texts) for base, window in _windows(text)]
    analyzer = _base_analyzer(config.language)
    ad_hoc = _ad_hoc(config)
    artifacts = analyzer.nlp_engine.process_batch(
        [window for _, _, window in jobs], config.language, batch_size=_BATCH_SIZE)
    per_text = [[] for _ in texts]
    for done, ((i, base, _), (window, nlp_artifacts)) in enumerate(zip(jobs, artifacts), start=1):
        found = _keep(_analyze_spacy(window, config, nlp_artifacts, ad_hoc), config)
        per_text[i].append((base, found))
        if progress is not None:
            progress(done, len(jobs))
    return [_merge_windows(windows) for windows in per_text]


def detect(text: str, config: AnonymizeConfig, progress=None) -> list[Entity]:
    """Detect entities, analysing long text in overlapping windows.

    progress(done_chunks, total_chunks) is called after each window so a
    caller can report movement while one large file is being scanned.

    The character windows exist for spaCy, whose cost grows faster than the
    text. GLiNER windows the text by words itself and keeps only spans that a
    window sees whole, so in GLiNER mode the text is not cut here: a cut would
    leave the part of a name before the cut as a separate, partial span.
    """
    if _gliner_enabled(config):
        return _detect_once(text, config, progress)
    windows = _windows(text)
    per_window = []
    for index, (base, window) in enumerate(windows, start=1):
        per_window.append((base, _detect_once(window, config)))
        if progress is not None:
            progress(index, len(windows))
    return _merge_windows(per_window)
