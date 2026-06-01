from thickanon.core.types import Entity, AnonymizeConfig, ReviewMode
from thickanon.core.decide import partition


def _e(score):
    return Entity(0, 1, "PERSON", score, "x")


def test_quick_review_splits_gray_band():
    cfg = AnonymizeConfig(mode=ReviewMode.QUICK_REVIEW, low_threshold=0.35, high_threshold=0.65)
    high, gray = partition([_e(0.9), _e(0.5)], cfg)
    assert len(high) == 1 and len(gray) == 1


def test_auto_redact_applies_gray():
    cfg = AnonymizeConfig(mode=ReviewMode.AUTO_REDACT, low_threshold=0.35, high_threshold=0.65)
    apply_now, gray = partition([_e(0.9), _e(0.5)], cfg)
    assert len(apply_now) == 2 and gray == []


def test_auto_skip_drops_gray():
    cfg = AnonymizeConfig(mode=ReviewMode.AUTO_SKIP, low_threshold=0.35, high_threshold=0.65)
    apply_now, gray = partition([_e(0.9), _e(0.5)], cfg)
    assert len(apply_now) == 1 and gray == []
