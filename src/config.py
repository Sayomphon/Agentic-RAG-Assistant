"""Centralized configuration for the Agentic RAG system.

Intended responsibility:
    Hold every tunable value in one place. Each setting has a sensible
    default and can be overridden via an environment variable of the
    same name (loaded from ``.env`` by python-dotenv). Secrets such as
    OPENAI_API_KEY live ONLY in the environment, never in code.
"""

import math
import os
import re
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    """Read one strict boolean setting and fail fast on ambiguous values."""
    raw = os.getenv(name, str(default)).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ValueError(
        f"{name} must be one of true/false, yes/no, on/off, or 1/0; "
        f"received {raw!r}."
    )


def _env_optional_float(
    name: str,
    default: float | None = None,
) -> float | None:
    """Read an optional numeric gate with an explicit disable sentinel."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    raw = raw.strip()
    if raw.lower() in {"none", "off", "disabled"}:
        return None
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number; received {raw!r}.")
    return value


def _env_choice(name: str, default: str, allowed: frozenset[str]) -> str:
    """Read and validate one case-insensitive enumerated setting."""
    value = os.getenv(name, default).strip().lower()
    if value not in allowed:
        choices = ", ".join(sorted(allowed))
        raise ValueError(f"{name} must be one of {choices}; received {value!r}.")
    return value


def _env_revision(name: str, default: str) -> str:
    """Require an immutable 40-character Git commit for remote model loads."""
    value = os.getenv(name, default).strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError(
            f"{name} must be a full 40-character hexadecimal commit SHA."
        )
    return value


@dataclass(frozen=True)
class RetrievalProfile:
    """Named, reviewable retrieval settings applied before env overrides."""

    search_mode: str
    candidate_k: int
    top_k: int
    hybrid_min_cosine: float
    reranker_min_score: float | None
    reranker_batch_size: int
    reranker_max_length: int
    reranker_timeout_seconds: float
    max_context_chars: int
    reranker_failure_policy: str
    secondary_policy: str


_RETRIEVAL_PROFILES = {
    # Importing/running the code without a .env file remains offline-safe.
    "keyword_safe": RetrievalProfile(
        search_mode="keyword",
        candidate_k=12,
        top_k=6,
        hybrid_min_cosine=0.20,
        reranker_min_score=0.01,
        reranker_batch_size=4,
        reranker_max_length=512,
        reranker_timeout_seconds=10.0,
        max_context_chars=6_000,
        reranker_failure_policy="fail_closed",
        secondary_policy="emergency_low_risk_only",
    ),
    # Official Track A settings selected by the versioned Step 3 evidence.
    "track_a_balanced_v1": RetrievalProfile(
        search_mode="hybrid",
        candidate_k=12,
        top_k=6,
        hybrid_min_cosine=0.20,
        reranker_min_score=0.01,
        reranker_batch_size=4,
        reranker_max_length=512,
        reranker_timeout_seconds=10.0,
        max_context_chars=6_000,
        reranker_failure_policy="fail_closed",
        secondary_policy="all_supported",
    ),
    # M1 remediation candidate. It is not an approved release identity until
    # the versioned R3/R4 evidence and Human/Product gates complete.
    "track_a_balanced_v2": RetrievalProfile(
        search_mode="hybrid",
        candidate_k=10,
        top_k=6,
        hybrid_min_cosine=0.20,
        reranker_min_score=0.01,
        reranker_batch_size=4,
        reranker_max_length=128,
        reranker_timeout_seconds=10.0,
        max_context_chars=6_000,
        reranker_failure_policy="fail_closed",
        secondary_policy="emergency_low_risk_only",
    ),
}

RETRIEVAL_PROFILE: str = _env_choice(
    "RETRIEVAL_PROFILE",
    "keyword_safe",
    frozenset(_RETRIEVAL_PROFILES),
)
ACTIVE_RETRIEVAL_PROFILE = _RETRIEVAL_PROFILES[RETRIEVAL_PROFILE]


# LLM
MODEL_NAME: str = os.getenv("MODEL_NAME", "gpt-5-mini")
TEMPERATURE: float = float(os.getenv("TEMPERATURE", "0"))

# Knowledge base / retrieval — the assignment's required artifact is the
# single `knowledge_base.txt` at the repository root, so that is the default.
# KB_PATH may also point at a directory of .txt files (ingested in
# sorted-filename order) when a corpus is split across domains.
KB_PATH: str = os.getenv("KB_PATH", "knowledge_base.txt")
TOP_K: int = int(os.getenv("TOP_K", str(ACTIVE_RETRIEVAL_PROFILE.top_k)))
CANDIDATE_K: int = int(
    os.getenv("CANDIDATE_K", str(ACTIVE_RETRIEVAL_PROFILE.candidate_k))
)
# BM25 is only the ranking layer. A minimum matched-term gate in the retriever
# rejects documents that score from one incidental word in a longer query.
MIN_SCORE: float = float(os.getenv("MIN_SCORE", "2.0"))
MIN_MATCHED_TERMS: int = int(os.getenv("MIN_MATCHED_TERMS", "2"))
MIN_RELATIVE_SCORE: float = float(os.getenv("MIN_RELATIVE_SCORE", "0.55"))
TITLE_BOOST: float = float(os.getenv("TITLE_BOOST", "1.5"))
THAI_TOKENIZER_ENABLED: bool = _env_bool("THAI_TOKENIZER_ENABLED", True)

# Retrieval mode: "keyword" (BM25), "semantic" (embeddings), or "hybrid" (both)
SEARCH_MODE: str = _env_choice(
    "SEARCH_MODE",
    ACTIVE_RETRIEVAL_PROFILE.search_mode,
    frozenset({"keyword", "semantic", "hybrid"}),
)

# Agentic retry loop: total search attempts per query (first attempt included).
# When an attempt yields zero snippets, the query rewriter proposes a new
# search query and the retriever tries again, up to this bound.
MAX_SEARCH_ATTEMPTS: int = int(os.getenv("MAX_SEARCH_ATTEMPTS", "3"))

# Dense retrieval (used by "semantic" and "hybrid" modes only)
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
# Cosine relevance gate. Cosine similarity is never zero, so without this
# gate unanswerable queries would always surface the least-unrelated chunk.
# Tuned on measured data (July 2026, text-embedding-3-small, 54-chunk KB):
# full-sentence answerable queries scored >= 0.426 against their target
# section; unanswerable queries peaked at 0.369 ("employee home addresses").
# 0.38 sits just above that negative ceiling. Ultra-terse positives
# ("quit my job" = 0.345) fall below the gate and degrade to "not found" —
# a deliberate trade: a missed answer is recoverable, a fabricated one is not.
MIN_COSINE: float = float(os.getenv("MIN_COSINE", "0.38"))
# Hybrid retrieval has a local answerability gate after fusion. Its measured
# multilingual optimum can therefore be more permissive than semantic-only
# mode without weakening the latter's deterministic dense-side safety gate.
HYBRID_MIN_COSINE: float = float(
    os.getenv(
        "HYBRID_MIN_COSINE",
        str(ACTIVE_RETRIEVAL_PROFILE.hybrid_min_cosine),
    )
)
EMBEDDING_CACHE_DIR: str = os.getenv("EMBEDDING_CACHE_DIR", ".cache")

# Hybrid fusion ("rrf" is rank-based and scale-free; "weighted" kept for
# evaluation comparison — see src/retrievers/hybrid.py for the rationale)
FUSION_METHOD: str = os.getenv("FUSION_METHOD", "rrf")
RRF_K: int = int(os.getenv("RRF_K", "60"))
DENSE_WEIGHT: float = float(os.getenv("DENSE_WEIGHT", "0.5"))

# Local multilingual reranking. The revision pins model code and weights to a
# reviewed immutable snapshot instead of trusting a moving Hub branch.
RERANKER_ENABLED: bool = _env_bool("RERANKER_ENABLED", True)
RERANKER_MODEL: str = os.getenv(
    "RERANKER_MODEL", "BAAI/bge-reranker-v2-m3"
)
RERANKER_MODEL_REVISION: str = _env_revision(
    "RERANKER_MODEL_REVISION",
    "b4019bcd5cae485c342f61fe5889c2c800c5abec",
)
RERANKER_CACHE_DIR: str = os.getenv(
    "RERANKER_CACHE_DIR", ".cache/reranker"
)
RERANKER_DEVICE: str = os.getenv("RERANKER_DEVICE", "")
RERANKER_BATCH_SIZE: int = int(
    os.getenv(
        "RERANKER_BATCH_SIZE",
        str(ACTIVE_RETRIEVAL_PROFILE.reranker_batch_size),
    )
)
RERANKER_TIMEOUT_SECONDS: float = float(
    os.getenv(
        "RERANKER_TIMEOUT_SECONDS",
        str(ACTIVE_RETRIEVAL_PROFILE.reranker_timeout_seconds),
    )
)
RERANKER_MAX_CANDIDATES: int = int(
    os.getenv("RERANKER_MAX_CANDIDATES", "30")
)
RERANKER_MAX_LENGTH: int = int(
    os.getenv(
        "RERANKER_MAX_LENGTH",
        str(ACTIVE_RETRIEVAL_PROFILE.reranker_max_length),
    )
)
RERANKER_MIN_SCORE: float | None = _env_optional_float(
    "RERANKER_MIN_SCORE",
    ACTIVE_RETRIEVAL_PROFILE.reranker_min_score,
)
RERANKER_LOCAL_FILES_ONLY: bool = _env_bool(
    "RERANKER_LOCAL_FILES_ONLY", False
)
RERANKER_FAILURE_POLICY: str = _env_choice(
    "RERANKER_FAILURE_POLICY",
    ACTIVE_RETRIEVAL_PROFILE.reranker_failure_policy,
    frozenset({"fail_closed", "conservative", "fusion_order"}),
)
RERANKER_SECONDARY_POLICY: str = _env_choice(
    "RERANKER_SECONDARY_POLICY",
    ACTIVE_RETRIEVAL_PROFILE.secondary_policy,
    frozenset({"all_supported", "emergency_low_risk_only"}),
)

# Smaller secondary reranker. The immutable revision is the reviewed
# Hugging Face snapshot, not a moving branch. It is loaded lazily and never
# enables remote model code.
RERANKER_FALLBACK_ENABLED: bool = _env_bool(
    "RERANKER_FALLBACK_ENABLED", True
)
RERANKER_FALLBACK_MODEL: str = os.getenv(
    "RERANKER_FALLBACK_MODEL", "BAAI/bge-reranker-base"
)
RERANKER_FALLBACK_MODEL_REVISION: str = _env_revision(
    "RERANKER_FALLBACK_MODEL_REVISION",
    "2cfc18c9415c912f9d8155881c133215df768a70",
)
RERANKER_FALLBACK_CACHE_DIR: str = os.getenv(
    "RERANKER_FALLBACK_CACHE_DIR", ".cache/reranker-fallback"
)
RERANKER_FALLBACK_MAX_LENGTH: int = int(
    os.getenv("RERANKER_FALLBACK_MAX_LENGTH", "512")
)
# Score scales are model-specific and unbounded, so the secondary threshold
# is deliberately independent from the primary model's tuned gate.
RERANKER_FALLBACK_MIN_SCORE: float | None = _env_optional_float(
    "RERANKER_FALLBACK_MIN_SCORE",
    0.01,
)

# Grounding context
MAX_CONTEXT_CHARS: int = int(
    os.getenv(
        "MAX_CONTEXT_CHARS",
        str(ACTIVE_RETRIEVAL_PROFILE.max_context_chars),
    )
)
CONTEXT_DUPLICATE_THRESHOLD: float = float(
    os.getenv("CONTEXT_DUPLICATE_THRESHOLD", "0.90")
)
CONTEXT_MIN_BODY_CHARS: int = int(
    os.getenv("CONTEXT_MIN_BODY_CHARS", "80")
)
