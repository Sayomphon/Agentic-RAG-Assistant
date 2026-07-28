"""Bounded local reranking with lazy model loading and safe degradation.

The module has no import-time dependency on PyTorch or Sentence Transformers.
Keyword-only and reranker-disabled processes therefore stay lightweight. A
single daemon worker serializes model access, preventing concurrent requests
from duplicating a multi-gigabyte model or exhausting local memory while still
allowing a timed-out CLI process to exit cleanly.
"""

from __future__ import annotations

import logging
import math
import threading
from concurrent.futures import Future, TimeoutError
from pathlib import Path
from typing import Callable, Iterable, Protocol, Sequence

from src.config import (
    CANDIDATE_K,
    RERANKER_BATCH_SIZE,
    RERANKER_CACHE_DIR,
    RERANKER_DEVICE,
    RERANKER_LOCAL_FILES_ONLY,
    RERANKER_MAX_CANDIDATES,
    RERANKER_MAX_LENGTH,
    RERANKER_MIN_SCORE,
    RERANKER_MODEL,
    RERANKER_MODEL_REVISION,
    RERANKER_TIMEOUT_SECONDS,
)
from src.retrievers.base import Retriever, ScoredChunk

logger = logging.getLogger(__name__)


class RerankerError(RuntimeError):
    """Base error translated into fusion-order fallback by the wrapper."""


class RerankerTimeoutError(RerankerError):
    """The bounded local inference deadline was exceeded."""


class RerankerBusyError(RerankerError):
    """A previous timed-out inference is still occupying the sole worker."""


class _CrossEncoderBackend(Protocol):
    """Minimal third-party model surface used by the adapter."""

    def predict(
        self,
        sentences: Sequence[tuple[str, str]],
        *,
        batch_size: int,
        show_progress_bar: bool,
        convert_to_numpy: bool,
    ) -> Iterable[float]:
        ...


class Reranker(Protocol):
    """Stable reranking contract shared with the future Enterprise Track."""

    def rerank(
        self,
        query: str,
        candidates: list[ScoredChunk],
        top_k: int,
    ) -> list[ScoredChunk]:
        """Return up to ``top_k`` candidates in descending relevance order."""
        ...


class LocalCrossEncoderReranker:
    """Sentence-Transformers CrossEncoder adapter for local multilingual use."""

    def __init__(
        self,
        *,
        model_name: str = RERANKER_MODEL,
        model_revision: str = RERANKER_MODEL_REVISION,
        cache_dir: str = RERANKER_CACHE_DIR,
        device: str = RERANKER_DEVICE,
        batch_size: int = RERANKER_BATCH_SIZE,
        timeout_seconds: float = RERANKER_TIMEOUT_SECONDS,
        max_candidates: int = RERANKER_MAX_CANDIDATES,
        max_length: int = RERANKER_MAX_LENGTH,
        local_files_only: bool = RERANKER_LOCAL_FILES_ONLY,
        model_factory: Callable[[], _CrossEncoderBackend] | None = None,
    ) -> None:
        self._model_name = model_name
        self._model_revision = model_revision or None
        self._cache_dir = cache_dir or None
        self._device = device or None
        self._batch_size = max(1, batch_size)
        self._timeout_seconds = max(0.01, timeout_seconds)
        self._max_candidates = max(1, max_candidates)
        self._max_length = max(32, max_length)
        self._local_files_only = local_files_only
        self._model_factory = model_factory

        self._model: _CrossEncoderBackend | None = None
        self._load_error: Exception | None = None
        self._model_lock = threading.Lock()
        self._submission_lock = threading.Lock()
        self._inflight: Future[list[float]] | None = None

    def warmup(self) -> None:
        """Synchronously download/load the pinned model before serving traffic."""
        self._get_model()

    def _build_model(self) -> _CrossEncoderBackend:
        """Load an immutable, non-remote-code model snapshot on first use."""
        if self._model_factory is not None:
            return self._model_factory()

        try:
            from huggingface_hub import snapshot_download
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise RerankerError(
                "Local reranker dependencies are not installed; install the "
                "pinned project requirements."
            ) from exc

        runtime_kwargs = {
            "device": self._device,
            "trust_remote_code": False,
            "max_length": self._max_length,
        }
        local_model_path = Path(self._model_name).expanduser()
        if local_model_path.exists():
            return CrossEncoder(
                str(local_model_path.resolve()),
                local_files_only=True,
                **runtime_kwargs,
            )

        # Resolve a cached revision to its immutable filesystem snapshot first.
        # Passing that path directly avoids all Hub metadata calls and works
        # around library-specific remote-ID handling in offline mode.
        try:
            snapshot_path = snapshot_download(
                repo_id=self._model_name,
                revision=self._model_revision,
                cache_dir=self._cache_dir,
                local_files_only=True,
            )
            return CrossEncoder(
                snapshot_path,
                local_files_only=True,
                **runtime_kwargs,
            )
        except Exception:
            if self._local_files_only:
                raise

        # Cache miss/corruption: an approved online first run downloads the
        # pinned revision. Later processes take the offline path above.
        return CrossEncoder(
            self._model_name,
            cache_folder=self._cache_dir,
            revision=self._model_revision,
            local_files_only=False,
            **runtime_kwargs,
        )

    def _get_model(self) -> _CrossEncoderBackend:
        if self._model is not None:
            return self._model
        if self._load_error is not None:
            raise RerankerError("The local reranker model failed to load.") from (
                self._load_error
            )

        with self._model_lock:
            if self._model is not None:
                return self._model
            if self._load_error is not None:
                raise RerankerError(
                    "The local reranker model failed to load."
                ) from self._load_error
            try:
                self._model = self._build_model()
            except Exception as exc:
                self._load_error = exc
                raise
            return self._model

    def _predict(
        self,
        query: str,
        candidates: list[ScoredChunk],
    ) -> list[float]:
        pairs = [(query, hit.as_snippet()) for hit in candidates]
        raw_scores = self._get_model().predict(
            pairs,
            batch_size=self._batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        try:
            scores = [float(score) for score in raw_scores]
        except (TypeError, ValueError) as exc:
            raise RerankerError("The reranker returned invalid scores.") from exc
        if len(scores) != len(candidates) or not all(map(math.isfinite, scores)):
            raise RerankerError(
                "The reranker returned a mismatched or non-finite score array."
            )
        return scores

    def _submit(
        self,
        query: str,
        candidates: list[ScoredChunk],
    ) -> Future[list[float]]:
        with self._submission_lock:
            if self._inflight is not None and not self._inflight.done():
                raise RerankerBusyError(
                    "The previous local reranking call is still running."
                )
            future: Future[list[float]] = Future()
            self._inflight = future
            threading.Thread(
                target=self._run_prediction,
                args=(future, query, candidates),
                name="rag-reranker",
                daemon=True,
            ).start()
            return future

    def _run_prediction(
        self,
        future: Future[list[float]],
        query: str,
        candidates: list[ScoredChunk],
    ) -> None:
        """Resolve one Future inside the bounded, process-safe daemon worker."""
        if not future.set_running_or_notify_cancel():
            return
        try:
            scores = self._predict(query, candidates)
        except BaseException as exc:
            future.set_exception(exc)
        else:
            future.set_result(scores)

    def rerank(
        self,
        query: str,
        candidates: list[ScoredChunk],
        top_k: int,
    ) -> list[ScoredChunk]:
        if top_k <= 0 or not candidates:
            return []

        bounded = candidates[: self._max_candidates]
        future = self._submit(query, bounded)
        try:
            scores = future.result(timeout=self._timeout_seconds)
        except TimeoutError as exc:
            future.cancel()
            raise RerankerTimeoutError(
                "Local reranking exceeded its configured deadline."
            ) from exc

        ranked = sorted(
            enumerate(zip(bounded, scores, strict=True)),
            key=lambda item: (-item[1][1], item[0]),
        )
        return [
            ScoredChunk(
                chunk=hit.chunk,
                score=score,
                source=hit.source,
                retrieval_score=hit.score,
                reranker_score=score,
            )
            for _, (hit, score) in ranked[:top_k]
        ]


class RerankingRetriever:
    """Retrieve broadly, rerank narrowly, and fail open to retrieval order."""

    def __init__(
        self,
        base: Retriever,
        reranker: Reranker,
        *,
        candidate_k: int = CANDIDATE_K,
        min_reranker_score: float | None = RERANKER_MIN_SCORE,
    ) -> None:
        self._base = base
        self._reranker = reranker
        self.SOURCE = str(getattr(base, "SOURCE", "reranked"))
        self._candidate_k = max(1, candidate_k)
        self._min_reranker_score = min_reranker_score
        self._fallback_count = 0
        self._answerability_rejection_count = 0
        self._metrics_lock = threading.Lock()

    @property
    def query_failure_count(self) -> int:
        """Preserve dense-provider failure telemetry through this wrapper."""
        return int(getattr(self._base, "query_failure_count", 0))

    @property
    def reranker_fallback_count(self) -> int:
        with self._metrics_lock:
            return self._fallback_count

    @property
    def answerability_rejection_count(self) -> int:
        with self._metrics_lock:
            return self._answerability_rejection_count

    def warmup(self) -> None:
        """Load an optional local backend before measuring query latency."""
        warmup = getattr(self._reranker, "warmup", None)
        if callable(warmup):
            warmup()

    def search(self, query: str, top_k: int) -> list[ScoredChunk]:
        if top_k <= 0:
            return []
        candidates = self._base.search(
            query,
            top_k=max(top_k, self._candidate_k),
        )
        if not candidates:
            return []
        try:
            reranked = self._reranker.rerank(query, candidates, top_k)[:top_k]
            if self._min_reranker_score is None:
                return reranked
            accepted = [
                hit
                for hit in reranked
                if hit.reranker_score is not None
                and hit.reranker_score >= self._min_reranker_score
            ]
            with self._metrics_lock:
                self._answerability_rejection_count += (
                    len(reranked) - len(accepted)
                )
            return accepted
        except Exception as exc:
            with self._metrics_lock:
                self._fallback_count += 1
            logger.warning(
                "Local reranking failed (%s); preserving retrieval order.",
                type(exc).__name__,
            )
            return candidates[:top_k]


if __name__ == "__main__":
    LocalCrossEncoderReranker().warmup()
    print("Local reranker snapshot is ready.")
