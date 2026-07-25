"""Centralized configuration for the Agentic RAG system.

Intended responsibility:
    Hold every tunable value in one place. Each setting has a sensible
    default and can be overridden via an environment variable of the
    same name (loaded from ``.env`` by python-dotenv). Secrets such as
    OPENAI_API_KEY live ONLY in the environment, never in code.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# LLM
MODEL_NAME: str = os.getenv("MODEL_NAME", "gpt-5-mini")
TEMPERATURE: float = float(os.getenv("TEMPERATURE", "0"))

# Knowledge base / retrieval
KB_PATH: str = os.getenv("KB_PATH", "knowledge_base.txt")
TOP_K: int = int(os.getenv("TOP_K", "4"))
# Tuned empirically (see README): incidental single-term matches score
# <= ~1.7 (e.g. "salary" appearing in unrelated sections), genuinely
# relevant matches >= ~2.1. 2.0 splits the bands with margin on both sides.
MIN_SCORE: float = float(os.getenv("MIN_SCORE", "2.0"))

# Retrieval mode: "keyword" (BM25 baseline) or "semantic" (optional upgrade)
SEARCH_MODE: str = os.getenv("SEARCH_MODE", "keyword")
