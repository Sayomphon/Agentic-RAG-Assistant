# Track A R2 — Runtime and Safety Policy

This document is the current runtime-safety addendum for Track A R2. The
R0-frozen `docs/RETRIEVER_CONTRACT.md` remains unchanged as historical input
evidence; the Python `Retriever` protocol and result shape remain at `1.0.0`.

## Runtime sequence

```text
Hybrid candidates
  → Primary: BAAI/bge-reranker-v2-m3
  → Secondary: BAAI/bge-reranker-base
  → Configured terminal policy
      fail_closed  → []
      conservative → reviewed deterministic gate, otherwise []
      fusion_order → original fusion order (lab/debug only)
  → Context Builder
  → Generator
```

The production default is `fail_closed`. When both rerankers fail, the empty
result reaches the generator's existing deterministic not-found branch; no
model is asked to synthesize an answer from degraded evidence.

## Secondary model decision

| Property | Reviewed value |
|---|---|
| Model | `BAAI/bge-reranker-base` |
| Immutable revision | `2cfc18c9415c912f9d8155881c133215df768a70` |
| License | MIT; commercial use permitted |
| Published languages | English and Chinese |
| Architecture | Cross-encoder, approximately 0.3B parameters |
| Score semantics | Unbounded relevance score; higher is more relevant |
| Remote model code | Disabled (`trust_remote_code=False`) |
| Cache | `.cache/reranker-fallback` |

Primary sources:

- [Pinned model card](https://huggingface.co/BAAI/bge-reranker-base/blob/2cfc18c9415c912f9d8155881c133215df768a70/README.md)
- [Model repository](https://huggingface.co/BAAI/bge-reranker-base)
- [Immutable commit](https://huggingface.co/BAAI/bge-reranker-base/commit/2cfc18c9415c912f9d8155881c133215df768a70)

The secondary threshold is configured independently as
`RERANKER_FALLBACK_MIN_SCORE`. R2 proves the runtime path and fail-safe
boundary; model-specific quality/threshold comparison belongs to the R3
ablation and evaluation evidence.

The current production corpus is English, and Thai-only user questions are
translated into concise English handbook vocabulary by the Retriever Agent.
The secondary model's published language scope therefore covers the text it
sees in the current production path. A future Thai production corpus requires
a multilingual secondary-model review before promotion.

## Failure taxonomy and telemetry

Only the following content-free reason codes may enter telemetry or logs:

```text
MODEL_LOAD_FAILED
MODEL_NOT_CACHED
INFERENCE_TIMEOUT
WORKER_BUSY
INVALID_SCORE_ARRAY
OUT_OF_MEMORY
UNKNOWN_RERANKER_ERROR
```

The retriever exposes additive properties without changing its `search()`
signature:

- `primary_reranker_failure_count`
- `secondary_reranker_usage_count`
- `secondary_reranker_failure_count`
- `fail_closed_count`
- `fusion_fallback_count`
- `active_reranker_model`
- `last_fallback_reason_code`

Raw query text, candidate bodies, prompts, credentials, filesystem details,
and raw exception messages are excluded from the log boundary.

## Configuration precedence

```text
trusted request override
  > explicit environment variable
  > RETRIEVAL_PROFILE
  > keyword-safe code fallback
```

Runtime code defaults to `keyword_safe`. Copying `.env.example` selects
`track_a_balanced_v1`, which is the versioned official Track A profile:

```text
SEARCH_MODE=hybrid
CANDIDATE_K=12
TOP_K=6
HYBRID_MIN_COSINE=0.20
RERANKER_MIN_SCORE=0.01
RERANKER_BATCH_SIZE=4
RERANKER_TIMEOUT_SECONDS=10
MAX_CONTEXT_CHARS=6000
RERANKER_FAILURE_POLICY=fail_closed
```

## Metric semantics

New Track A tuning output uses schema
`track-a-step3-measure-tune-v2`:

- `context_header_validity`: every context snippet begins with its retrieved
  title.
- `context_budget_validity`: the final context remains within its configured
  character budget.
- `answer_citation_validity`: every final-answer citation names handed-off
  evidence.
- `answer_citation_coverage`: the share of factual answer claims carrying at
  least one citation.

The retrieval-only runner records the two answer metrics as `null`; it must
never present a context-header check as final-answer citation evidence.

## Verification gates

```bash
venv/bin/python -m unittest tests.test_reranker -v
venv/bin/python -m unittest tests.test_thai_retrieval_integration -v
venv/bin/python -m unittest tests.test_retriever_contract -v
venv/bin/python -m unittest discover -s tests -v
venv/bin/python -m src.evaluation.regression
venv/bin/python -m src.evaluation.run_track_a_closure --verify-r1-artifact
RERANKER_LOCAL_FILES_ONLY=true \
  venv/bin/python -m src.evaluation.run_r2_safety --model primary
RERANKER_LOCAL_FILES_ONLY=true \
  venv/bin/python -m src.evaluation.run_r2_safety --model secondary
```

Real-model readiness additionally requires warmup/inference of both immutable
snapshots on the target hardware. Any Secondary quality or performance result
must record that model's identity, revision, cache state, latency, and peak
RSS separately from the Primary path.

## Local R2 verification snapshot

Generated on 2026-07-28 at source HEAD
`3a6fa7a4cb59c7ae658157e4d5cb27b2b556fbd8` plus the uncommitted R2 change
set, using Python 3.11.15 on arm64 macOS. Both runs were offline
(`local_files_only=true`) with 12 synthetic candidates, `top_k=6`,
`batch_size=4`, and four inference iterations.

| Path | Cold start | First inference | Warm average | Warm p95 | Peak RSS |
|---|---:|---:|---:|---:|---:|
| Primary | 4,917.7 ms | 1,833.5 ms | 331.9 ms | 333.1 ms | 1,945.4 MB |
| Secondary | 4,294.2 ms | 896.5 ms | 96.9 ms | 98.9 ms | 1,188.9 MB |

Both paths returned six finite, best-first results. The cached snapshot sizes
were approximately 2.1 GB (Primary) and 1.1 GB (Secondary). Injected
Primary+Secondary failure tests produced the byte-exact deterministic
not-found answer in 10/10 cases, with no unhandled exception.

These measurements prove R2 runtime readiness and the initial memory bound;
they are not the R3 quality/ablation decision. R3 must measure the Secondary
on the frozen Track A dataset and tune its independent answerability threshold
before it can be treated as quality-equivalent to the Primary.
