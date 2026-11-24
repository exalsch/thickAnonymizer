"""detect_many: all fragments of a file through spaCy in one batch, same results.

A spreadsheet has thousands of short cells. Calling spaCy once per cell
pays its fixed cost thousands of times; one batched pipe pays it once.
The results must be exactly the ones detect() gives for each fragment.
"""
from thickanon.core.types import AnonymizeConfig
from thickanon.detectors import engine
from thickanon.detectors.engine import MAX_ANALYZE_CHARS, detect, detect_many

LONG = (
    "Maintenance log. " * 230
    + "Contact John Carter at john.carter@acme.com or 10.0.0.5. "
    + "Filler text without names. " * 150
    + "Escalate to Mary Jones via mary.jones@acme.com."
)

FRAGMENTS = [
    "John Carter emailed jane@acme.com from 10.0.0.5",
    "",
    "Nothing to see here.",
    "Server db01.corp.example.com runs on 192.168.1.20",
    LONG,
    "Mary Jones, IBAN DE89370400440532013000",
]


def test_long_fragment_is_really_split():
    assert len(LONG) > MAX_ANALYZE_CHARS


def test_same_entities_as_detect_per_fragment():
    config = AnonymizeConfig()
    assert detect_many(FRAGMENTS, config) == [detect(f, config) for f in FRAGMENTS]


def test_same_entities_with_a_deny_list():
    config = AnonymizeConfig(deny_list=["Carter", "Nothing"])
    assert detect_many(FRAGMENTS, config) == [detect(f, config) for f in FRAGMENTS]


def test_spacy_runs_once_per_batch_not_once_per_text(monkeypatch):
    analyzer = engine._base_analyzer("en")
    calls = {"batch": 0}
    real_batch = analyzer.nlp_engine.process_batch

    def counting_batch(*args, **kwargs):
        calls["batch"] += 1
        return real_batch(*args, **kwargs)

    def no_single_calls(*args, **kwargs):
        raise AssertionError("spaCy was called for a single text")

    monkeypatch.setattr(analyzer.nlp_engine, "process_batch", counting_batch)
    monkeypatch.setattr(analyzer.nlp_engine, "process_text", no_single_calls)
    detect_many(["cell %d John Carter" % i for i in range(300)], AnonymizeConfig())
    assert calls["batch"] == 1


def test_progress_counts_windows_up_to_the_total():
    seen = []
    detect_many(FRAGMENTS, AnonymizeConfig(), progress=lambda d, t: seen.append((d, t)))
    assert seen and seen[-1][0] == seen[-1][1]
    assert [d for d, _ in seen] == sorted(d for d, _ in seen)
