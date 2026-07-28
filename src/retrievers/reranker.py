"""Bounded local reranking with lazy model loading and safe degradation.

The module has no import-time dependency on PyTorch or Sentence Transformers.
Keyword-only and reranker-disabled processes therefore stay lightweight. A
single daemon worker serializes model access, preventing concurrent requests
from duplicating a multi-gigabyte model or exhausting local memory while still
allowing a timed-out CLI process to exit cleanly. Runtime degradation is
explicit: primary failure tries one smaller secondary model, then the wrapper
applies a configured fail-safe policy without exposing query or document data.
"""

from __future__ import annotations

import logging
import math
import threading
from concurrent.futures import Future, TimeoutError
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable, Protocol, Sequence

from src.config import (
    CANDIDATE_K,
    RERANKER_BATCH_SIZE,
    RERANKER_CACHE_DIR,
    RERANKER_DEVICE,
    RERANKER_FAILURE_POLICY,
    RERANKER_FALLBACK_CACHE_DIR,
    RERANKER_FALLBACK_ENABLED,
    RERANKER_FALLBACK_MAX_LENGTH,
    RERANKER_FALLBACK_MIN_SCORE,
    RERANKER_FALLBACK_MODEL,
    RERANKER_FALLBACK_MODEL_REVISION,
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
    """Sanitized base error handled by the cascading runtime boundary."""


class RerankerTimeoutError(RerankerError):
    """The bounded local inference deadline was exceeded."""


class RerankerBusyError(RerankerError):
    """A previous timed-out inference is still occupying the sole worker."""


class RerankerModelLoadError(RerankerError):
    """A configured model could not be constructed safely."""


class RerankerModelNotCachedError(RerankerModelLoadError):
    """An offline-only model snapshot was not present in the approved cache."""


class RerankerInvalidScoreError(RerankerError):
    """A backend returned a malformed, mismatched, or non-finite score array."""


class RerankerOutOfMemoryError(RerankerError):
    """The local backend exhausted its available inference memory."""


class RerankerInferenceError(RerankerError):
    """A backend inference failed for a reason safe to classify as unknown."""


class FailureReasonCode(str, Enum):
    """Stable, content-free reason codes safe for metrics and logs."""

    MODEL_LOAD_FAILED = "MODEL_LOAD_FAILED"
    MODEL_NOT_CACHED = "MODEL_NOT_CACHED"
    INFERENCE_TIMEOUT = "INFERENCE_TIMEOUT"
    WORKER_BUSY = "WORKER_BUSY"
    INVALID_SCORE_ARRAY = "INVALID_SCORE_ARRAY"
    OUT_OF_MEMORY = "OUT_OF_MEMORY"
    UNKNOWN_RERANKER_ERROR = "UNKNOWN_RERANKER_ERROR"


class RerankerCascadeError(RerankerError):
    """Both configured rerankers were unavailable for one request."""

    def __init__(self, reason_code: FailureReasonCode) -> None:
        super().__init__("No configured reranker completed successfully.")
        self.reason_code = reason_code


def _is_out_of_memory(exc: BaseException) -> bool:
    """Recognize Python and backend-specific OOM types without importing torch."""
    return isinstance(exc, MemoryError) or "outofmemory" in (
        type(exc).__name__.replace("_", "").lower()
    )


def _failure_reason(exc: BaseException) -> FailureReasonCode:
    """Map an exception to a stable reason without inspecting its message."""
    if isinstance(exc, RerankerCascadeError):
        return exc.reason_code
    if isinstance(exc, RerankerTimeoutError):
        return FailureReasonCode.INFERENCE_TIMEOUT
    if isinstance(exc, RerankerBusyError):
        return FailureReasonCode.WORKER_BUSY
    if isinstance(exc, RerankerModelNotCachedError):
        return FailureReasonCode.MODEL_NOT_CACHED
    if isinstance(exc, RerankerModelLoadError):
        return FailureReasonCode.MODEL_LOAD_FAILED
    if isinstance(exc, RerankerInvalidScoreError):
        return FailureReasonCode.INVALID_SCORE_ARRAY
    if isinstance(exc, RerankerOutOfMemoryError) or _is_out_of_memory(exc):
        return FailureReasonCode.OUT_OF_MEMORY
    return FailureReasonCode.UNKNOWN_RERANKER_ERROR


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

    @property
    def model_name(self) -> str:
        """Configured model identifier; contains no request or document data."""
        return self._model_name

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
            raise RerankerModelLoadError(
                "Local reranker dependencies are not installed; install the "
                "pinned project requirements."
            ) from None

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
        except Exception:
            snapshot_path = None
        if snapshot_path is not None:
            try:
                return CrossEncoder(
                    snapshot_path,
                    local_files_only=True,
                    **runtime_kwargs,
                )
            except Exception as exc:
                if _is_out_of_memory(exc):
                    raise RerankerOutOfMemoryError(
                        "The local reranker model exceeded available memory."
                    ) from None
                raise RerankerModelLoadError(
                    "The cached local reranker snapshot failed to load."
                ) from None
        if self._local_files_only:
            raise RerankerModelNotCachedError(
                "The approved local reranker snapshot is not cached."
            )

        # Cache miss/corruption: an approved online first run downloads the
        # pinned revision. Later processes take the offline path above.
        try:
            return CrossEncoder(
                self._model_name,
                cache_folder=self._cache_dir,
                revision=self._model_revision,
                local_files_only=False,
                **runtime_kwargs,
            )
        except Exception as exc:
            if _is_out_of_memory(exc):
                raise RerankerOutOfMemoryError(
                    "The local reranker model exceeded available memory."
                ) from None
            raise RerankerModelLoadError(
                "The local reranker model failed to load."
            ) from None

    def _get_model(self) -> _CrossEncoderBackend:
        if self._model is not None:
            return self._model
        if self._load_error is not None:
            raise self._load_error

        with self._model_lock:
            if self._model is not None:
                return self._model
            if self._load_error is not None:
                raise self._load_error
            try:
                self._model = self._build_model()
            except Exception as exc:
                if isinstance(exc, RerankerError):
                    sanitized = exc
                elif _is_out_of_memory(exc):
                    sanitized = RerankerOutOfMemoryError(
                        "The local reranker model exceeded available memory."
                    )
                else:
                    sanitized = RerankerModelLoadError(
                        "The local reranker model failed to load."
                    )
                self._load_error = sanitized
                raise sanitized from None
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
            raise RerankerInvalidScoreError(
                "The reranker returned invalid scores."
            ) from None
        if len(scores) != len(candidates) or not all(map(math.isfinite, scores)):
            raise RerankerInvalidScoreError(
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
            ) from None
        except RerankerError:
            raise
        except Exception as exc:
            if _is_out_of_memory(exc):
                raise RerankerOutOfMemoryError(
                    "The local reranker exceeded available inference memory."
                ) from None
            raise RerankerInferenceError(
                "The local reranker inference failed."
            ) from None

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


def _validate_reranked_hits(
    hits: object,
    *,
    top_k: int,
) -> list[ScoredChunk]:
    """Reject malformed backend output before it can become evidence."""
    if not isinstance(hits, list) or len(hits) > max(0, top_k):
        raise RerankerInvalidScoreError(
            "The reranker returned an invalid result collection."
        )
    valid_scores = all(
        isinstance(hit, ScoredChunk)
        and math.isfinite(hit.score)
        and hit.reranker_score is not None
        and math.isfinite(hit.reranker_score)
        for hit in hits
    )
    if not valid_scores:
        raise RerankerInvalidScoreError(
            "The reranker returned invalid scored results."
        )
    scores = [hit.score for hit in hits]
    indexes = [hit.chunk.index for hit in hits]
    if scores != sorted(scores, reverse=True) or len(indexes) != len(set(indexes)):
        raise RerankerInvalidScoreError(
            "The reranker returned unordered or duplicate scored results."
        )
    return hits


def _telemetry_count(target: object, name: str) -> int:
    """Read additive telemetry only when the backend exposes a real integer."""
    value = getattr(target, name, 0)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _telemetry_text(target: object, name: str) -> str:
    """Read content-free telemetry only when the backend exposes a string."""
    value = getattr(target, name, "")
    return value if isinstance(value, str) else ""


class CascadingReranker:
    """Try a primary reranker, then one independently configured secondary."""

    def __init__(
        self,
        primary: Reranker,
        secondary: Reranker | None,
    ) -> None:
        self._primary = primary
        self._secondary = secondary
        self._metrics_lock = threading.Lock()
        self._request_state = threading.local()
        self._primary_failure_count = 0
        self._secondary_usage_count = 0
        self._secondary_failure_count = 0

    @property
    def primary_reranker_failure_count(self) -> int:
        with self._metrics_lock:
            return self._primary_failure_count

    @property
    def secondary_reranker_usage_count(self) -> int:
        with self._metrics_lock:
            return self._secondary_usage_count

    @property
    def secondary_reranker_failure_count(self) -> int:
        with self._metrics_lock:
            return self._secondary_failure_count

    @property
    def active_reranker_model(self) -> str:
        return str(getattr(self._request_state, "active_model", ""))

    @property
    def active_reranker_role(self) -> str:
        return str(getattr(self._request_state, "active_role", ""))

    @property
    def last_fallback_reason_code(self) -> str:
        reason = getattr(self._request_state, "reason_code", None)
        return reason.value if isinstance(reason, FailureReasonCode) else ""

    @staticmethod
    def _model_name(reranker: Reranker, role: str) -> str:
        return str(getattr(reranker, "model_name", role))

    @staticmethod
    def _warmup(reranker: Reranker) -> None:
        warmup = getattr(reranker, "warmup", None)
        if callable(warmup):
            warmup()

    def warmup(self) -> None:
        """Warm both snapshots; serving remains possible if either one works."""
        available = 0
        last_reason = FailureReasonCode.UNKNOWN_RERANKER_ERROR
        for role, reranker in (
            ("primary", self._primary),
            ("secondary", self._secondary),
        ):
            if reranker is None:
                continue
            try:
                self._warmup(reranker)
            except Exception as exc:
                last_reason = _failure_reason(exc)
                if role == "primary":
                    with self._metrics_lock:
                        self._primary_failure_count += 1
                else:
                    with self._metrics_lock:
                        self._secondary_failure_count += 1
            else:
                available += 1
        if not available:
            raise RerankerCascadeError(last_reason)

    def rerank(
        self,
        query: str,
        candidates: list[ScoredChunk],
        top_k: int,
    ) -> list[ScoredChunk]:
        self._request_state.active_model = ""
        self._request_state.active_role = ""
        self._request_state.reason_code = None
        try:
            hits = _validate_reranked_hits(
                self._primary.rerank(query, candidates, top_k),
                top_k=top_k,
            )
        except Exception as exc:
            primary_reason = _failure_reason(exc)
            self._request_state.reason_code = primary_reason
            with self._metrics_lock:
                self._primary_failure_count += 1
        else:
            self._request_state.active_role = "primary"
            self._request_state.active_model = self._model_name(
                self._primary,
                "primary",
            )
            return hits

        if self._secondary is None:
            raise RerankerCascadeError(primary_reason) from None

        with self._metrics_lock:
            self._secondary_usage_count += 1
        try:
            hits = _validate_reranked_hits(
                self._secondary.rerank(query, candidates, top_k),
                top_k=top_k,
            )
        except Exception as exc:
            secondary_reason = _failure_reason(exc)
            self._request_state.reason_code = secondary_reason
            with self._metrics_lock:
                self._secondary_failure_count += 1
            raise RerankerCascadeError(secondary_reason) from None

        self._request_state.active_role = "secondary"
        self._request_state.active_model = self._model_name(
            self._secondary,
            "secondary",
        )
        return hits


class RerankingRetriever:
    """Retrieve broadly, rerank narrowly, then apply an explicit failure policy."""

    def __init__(
        self,
        base: Retriever,
        reranker: Reranker,
        *,
        candidate_k: int = CANDIDATE_K,
        min_reranker_score: float | None = RERANKER_MIN_SCORE,
        secondary_min_reranker_score: (
            float | None
        ) = RERANKER_FALLBACK_MIN_SCORE,
        failure_policy: str = RERANKER_FAILURE_POLICY,
        conservative_gate: (
            Callable[[str, ScoredChunk], bool] | None
        ) = None,
    ) -> None:
        if failure_policy not in {"fail_closed", "conservative", "fusion_order"}:
            raise ValueError(
                "failure_policy must be fail_closed, conservative, or "
                "fusion_order."
            )
        self._base = base
        self._reranker = reranker
        self.SOURCE = str(getattr(base, "SOURCE", "reranked"))
        self._candidate_k = max(1, candidate_k)
        self._min_reranker_score = min_reranker_score
        self._secondary_min_reranker_score = secondary_min_reranker_score
        self._failure_policy = failure_policy
        self._conservative_gate = conservative_gate
        self._terminal_reranker_failure_count = 0
        self._fail_closed_count = 0
        self._fusion_fallback_count = 0
        self._answerability_rejection_count = 0
        self._last_terminal_reason_code = ""
        self._logged_failure_keys: set[tuple[str, str]] = set()
        self._metrics_lock = threading.Lock()

    @property
    def query_failure_count(self) -> int:
        """Preserve dense-provider failure telemetry through this wrapper."""
        return int(getattr(self._base, "query_failure_count", 0))

    @property
    def reranker_fallback_count(self) -> int:
        """Backward-compatible count of requests that left the primary path."""
        primary_failures = _telemetry_count(
            self._reranker,
            "primary_reranker_failure_count",
        )
        with self._metrics_lock:
            return max(primary_failures, self._terminal_reranker_failure_count)

    @property
    def primary_reranker_failure_count(self) -> int:
        cascaded = _telemetry_count(
            self._reranker,
            "primary_reranker_failure_count",
        )
        with self._metrics_lock:
            return max(cascaded, self._terminal_reranker_failure_count)

    @property
    def secondary_reranker_usage_count(self) -> int:
        return _telemetry_count(
            self._reranker,
            "secondary_reranker_usage_count",
        )

    @property
    def secondary_reranker_failure_count(self) -> int:
        return _telemetry_count(
            self._reranker,
            "secondary_reranker_failure_count",
        )

    @property
    def fail_closed_count(self) -> int:
        with self._metrics_lock:
            return self._fail_closed_count

    @property
    def fusion_fallback_count(self) -> int:
        with self._metrics_lock:
            return self._fusion_fallback_count

    @property
    def active_reranker_model(self) -> str:
        return _telemetry_text(self._reranker, "active_reranker_model")

    @property
    def last_fallback_reason_code(self) -> str:
        cascaded = _telemetry_text(
            self._reranker,
            "last_fallback_reason_code",
        )
        with self._metrics_lock:
            return cascaded or self._last_terminal_reason_code

    @property
    def answerability_rejection_count(self) -> int:
        with self._metrics_lock:
            return self._answerability_rejection_count

    def warmup(self) -> None:
        """Load an optional local backend before measuring query latency."""
        warmup = getattr(self._reranker, "warmup", None)
        if callable(warmup):
            warmup()

    def _apply_answerability_gate(
        self,
        reranked: list[ScoredChunk],
    ) -> list[ScoredChunk]:
        threshold = self._min_reranker_score
        if getattr(self._reranker, "active_reranker_role", "") == "secondary":
            threshold = self._secondary_min_reranker_score
        if threshold is None:
            return reranked
        accepted = [
            hit
            for hit in reranked
            if hit.reranker_score is not None
            and hit.reranker_score >= threshold
        ]
        with self._metrics_lock:
            self._answerability_rejection_count += len(reranked) - len(accepted)
        return accepted

    def _handle_terminal_failure(
        self,
        query: str,
        candidates: list[ScoredChunk],
        top_k: int,
        exc: Exception,
    ) -> list[ScoredChunk]:
        reason_code = _failure_reason(exc).value
        with self._metrics_lock:
            self._terminal_reranker_failure_count += 1
            self._last_terminal_reason_code = reason_code
            log_key = (self._failure_policy, reason_code)
            should_log = log_key not in self._logged_failure_keys
            self._logged_failure_keys.add(log_key)

        if should_log:
            # Rate-limit repeated outage logs per policy/reason combination;
            # counters retain exact request volume for operations.
            logger.warning(
                "Reranking unavailable; policy=%s reason=%s.",
                self._failure_policy,
                reason_code,
            )
        if self._failure_policy == "fusion_order":
            with self._metrics_lock:
                self._fusion_fallback_count += 1
            return candidates[:top_k]

        if self._failure_policy == "conservative" and self._conservative_gate:
            accepted = [
                hit
                for hit in candidates
                if self._conservative_gate(query, hit)
            ][:top_k]
            if accepted:
                return accepted

        # fail_closed is the production default. Conservative mode also
        # closes when no reviewed deterministic gate accepts evidence.
        with self._metrics_lock:
            self._fail_closed_count += 1
        return []

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
            return self._apply_answerability_gate(reranked)
        except Exception as exc:
            return self._handle_terminal_failure(
                query,
                candidates,
                top_k,
                exc,
            )


def build_cascading_reranker() -> CascadingReranker:
    """Build the approved primary/secondary pair without loading either model."""
    primary = LocalCrossEncoderReranker()
    secondary: LocalCrossEncoderReranker | None = None
    if RERANKER_FALLBACK_ENABLED:
        secondary = LocalCrossEncoderReranker(
            model_name=RERANKER_FALLBACK_MODEL,
            model_revision=RERANKER_FALLBACK_MODEL_REVISION,
            cache_dir=RERANKER_FALLBACK_CACHE_DIR,
            max_length=RERANKER_FALLBACK_MAX_LENGTH,
        )
    return CascadingReranker(primary, secondary)


if __name__ == "__main__":
    build_cascading_reranker().warmup()
    print("Primary and secondary local reranker snapshots are ready.")
