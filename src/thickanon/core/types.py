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


DEFAULT_GLINER_LABELS = [
    "person", "organization", "location", "email", "phone number",
    "address", "date of birth", "job title", "account number", "id number",
    # Technical identifiers. They raised recall on IT text (tickets, logs,
    # connection strings) from 85,4 % to 93,9 % in the 23.11.2026 benchmark.
    "hostname", "username", "ip address", "url",
]

# urchade/gliner_multi_pii-v1 exported to ONNX, run by onnxruntime without torch.
# Pinned to one revision so the model cannot change under a running setup.
DEFAULT_GLINER_MODEL_ID = "onnx-community/gliner_multi_pii-v1"
DEFAULT_GLINER_REVISION = "2e0397a7e8a250d76c37122232b3cbde42c8d629"
DEFAULT_GLINER_ONNX_FILE = "onnx/model.onnx"


@dataclass
class GLiNERConfig:
    enabled: bool = False
    model_id: str = DEFAULT_GLINER_MODEL_ID
    model_path: str | None = None
    onnx_file: str = DEFAULT_GLINER_ONNX_FILE
    labels: list[str] = field(default_factory=lambda: list(DEFAULT_GLINER_LABELS))
    threshold: float = 0.5
    gpu: bool = False
    # GLiNER reads at most config.max_len words (384 for the default model) and
    # silently drops the rest, so the input is windowed by words, not characters.
    # 96 words with 32 overlap gave the best recall on long documents in the
    # 23.11.2026 model benchmark (docs/reviews/2026-11-23-model-research.md).
    max_chunk_words: int = 96
    chunk_overlap_words: int = 32


@dataclass
class AnonymizeConfig:
    mode: ReviewMode = ReviewMode.QUICK_REVIEW
    # lean-safe: low threshold so we over-redact rather than miss
    low_threshold: float = 0.35    # below this: ignore entirely
    high_threshold: float = 0.65   # at/above this: auto-anonymize
    deny_list: list[str] = field(default_factory=list)
    language: str = "en"
    gliner: "GLiNERConfig | None" = None
