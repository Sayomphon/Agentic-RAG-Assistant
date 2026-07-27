"""Centralized configuration for the Agentic RAG system.

Intended responsibility:
    Hold every tunable value in one place. Each setting has a sensible
    default and can be overridden via an environment variable of the
    same name (loaded from ``.env`` by python-dotenv). Secrets such as
    OPENAI_API_KEY live ONLY in the environment, never in code.
"""

import math
import os

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


def _env_optional_float(name: str) -> float | None:
    """Read an optional numeric gate; an empty value leaves it disabled."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number; received {raw!r}.")
    return value


# LLM
MODEL_NAME: str = os.getenv("MODEL_NAME", "gpt-5-mini")
TEMPERATURE: float = float(os.getenv("TEMPERATURE", "0"))

# Knowledge base / retrieval — the assignment's required artifact is the
# single `knowledge_base.txt` at the repository root, so that is the default.
# KB_PATH may also point at a directory of .txt files (ingested in
# sorted-filename order) when a corpus is split across domains.
KB_PATH: str = os.getenv("KB_PATH", "knowledge_base.txt")
TOP_K: int = int(os.getenv("TOP_K", "4"))
CANDIDATE_K: int = int(os.getenv("CANDIDATE_K", "24"))
# BM25 is only the ranking layer. A minimum matched-term gate in the retriever
# rejects documents that score from one incidental word in a longer query.
MIN_SCORE: float = float(os.getenv("MIN_SCORE", "2.0"))
MIN_MATCHED_TERMS: int = int(os.getenv("MIN_MATCHED_TERMS", "2"))
MIN_RELATIVE_SCORE: float = float(os.getenv("MIN_RELATIVE_SCORE", "0.55"))
TITLE_BOOST: float = float(os.getenv("TITLE_BOOST", "1.5"))
THAI_TOKENIZER_ENABLED: bool = _env_bool("THAI_TOKENIZER_ENABLED", True)

# Retrieval mode: "keyword" (BM25), "semantic" (embeddings), or "hybrid" (both)
SEARCH_MODE: str = os.getenv("SEARCH_MODE", "keyword")

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
RERANKER_MODEL_REVISION: str = os.getenv(
    "RERANKER_MODEL_REVISION",
    "b4019bcd5cae485c342f61fe5889c2c800c5abec",
)
RERANKER_CACHE_DIR: str = os.getenv(
    "RERANKER_CACHE_DIR", ".cache/reranker"
)
RERANKER_DEVICE: str = os.getenv("RERANKER_DEVICE", "")
RERANKER_BATCH_SIZE: int = int(os.getenv("RERANKER_BATCH_SIZE", "8"))
RERANKER_TIMEOUT_SECONDS: float = float(
    os.getenv("RERANKER_TIMEOUT_SECONDS", "5")
)
RERANKER_MAX_CANDIDATES: int = int(
    os.getenv("RERANKER_MAX_CANDIDATES", "30")
)
RERANKER_MAX_LENGTH: int = int(os.getenv("RERANKER_MAX_LENGTH", "512"))
RERANKER_MIN_SCORE: float | None = _env_optional_float(
    "RERANKER_MIN_SCORE"
)
RERANKER_LOCAL_FILES_ONLY: bool = _env_bool(
    "RERANKER_LOCAL_FILES_ONLY", False
)

# Grounding context
MAX_CONTEXT_CHARS: int = int(os.getenv("MAX_CONTEXT_CHARS", "12000"))
CONTEXT_DUPLICATE_THRESHOLD: float = float(
    os.getenv("CONTEXT_DUPLICATE_THRESHOLD", "0.90")
)
CONTEXT_MIN_BODY_CHARS: int = int(
    os.getenv("CONTEXT_MIN_BODY_CHARS", "80")
)
