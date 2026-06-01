from dataclasses import dataclass, field
from enum import Enum


@dataclass(frozen=True)
class Entity:
    start: int
    end: int
    entity_type: str
    score: float
    text: str


class ReviewMode(Enum):
    QUICK_REVIEW = "quick_review"   # gray band -> human review (default)
    AUTO_REDACT = "auto_redact"     # gray band -> anonymize automatically
    AUTO_SKIP = "auto_skip"         # gray band -> leave, rely on residual scan


@dataclass
class AnonymizeConfig:
    mode: ReviewMode = ReviewMode.QUICK_REVIEW
    # lean-safe: low threshold so we over-redact rather than miss
    low_threshold: float = 0.35    # below this: ignore entirely
    high_threshold: float = 0.65   # at/above this: auto-anonymize
    deny_list: list[str] = field(default_factory=list)
    language: str = "en"
