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


DEFAULT_LLM_CATEGORIES = [
    "PERSON", "ORGANIZATION", "LOCATION", "JOB_TITLE",
    "DATE_OF_BIRTH", "ACCOUNT_ID",
]

# Pinned default model (small, CPU-friendly). The sha256 is verified on download;
# see detectors/llm_model.py. Implementer: confirm URL resolves and paste the real
# sha256 of the downloaded file into DEFAULT_LLM_SHA256 (a later task explains how).
DEFAULT_LLM_MODEL_URL = (
    "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/"
    "qwen2.5-1.5b-instruct-q4_k_m.gguf"
)
DEFAULT_LLM_SHA256 = ""  # empty = skip verification (logs a warning); pin once known


@dataclass
class LLMConfig:
    enabled: bool = False
    model_path: str | None = None
    model_url: str = DEFAULT_LLM_MODEL_URL
    sha256: str = DEFAULT_LLM_SHA256
    n_gpu_layers: int = 0
    confidence: float = 0.5
    categories: list[str] = field(default_factory=lambda: list(DEFAULT_LLM_CATEGORIES))
    custom_instruction: str = ""
    max_chunk_chars: int = 4000


DEFAULT_GLINER_LABELS = [
    "person", "organization", "location", "email", "phone number",
    "address", "date of birth", "job title", "account number", "id number",
]

# A fast_gliner-supported ONNX GLiNER model on Hugging Face. Implementer: confirm
# this repo loads with fast_gliner (a later task); if not, pin another ONNX GLiNER repo.
DEFAULT_GLINER_MODEL_ID = "onnx-community/gliner_multi_pii-v1"


@dataclass
class GLiNERConfig:
    enabled: bool = False
    model_id: str = DEFAULT_GLINER_MODEL_ID
    model_path: str | None = None
    labels: list[str] = field(default_factory=lambda: list(DEFAULT_GLINER_LABELS))
    threshold: float = 0.5
    gpu: bool = False
    max_chunk_chars: int = 4000


@dataclass
class AnonymizeConfig:
    mode: ReviewMode = ReviewMode.QUICK_REVIEW
    # lean-safe: low threshold so we over-redact rather than miss
    low_threshold: float = 0.35    # below this: ignore entirely
    high_threshold: float = 0.65   # at/above this: auto-anonymize
    deny_list: list[str] = field(default_factory=list)
    language: str = "en"
    llm: "LLMConfig | None" = None
    gliner: "GLiNERConfig | None" = None
