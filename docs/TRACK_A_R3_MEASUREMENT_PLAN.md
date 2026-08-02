# Track A R3 — Measurement Execution Plan

## Objective

Close the Step 3 evidence gap with reproducible measurements for retrieval
quality, final-answer quality, latency, memory, and failure safety. R3 produces
technical evidence and a decision recommendation; Product/Business approval
remains an explicit human action.

## Frozen comparison boundary

- Dataset: `lean-quality-v1`, 40 cases.
- Corpus: the R0-frozen knowledge base identity.
- Controlled result count: `TOP_K=6`.
- Historical comparison: R1 `pre_track_a_controlled_top_k_6`.
- Dense candidates: the existing versioned prepared cache.
- Primary and Secondary reranker revisions: immutable R2-approved snapshots.
- Metric implementation: `track-a-r3-metrics-v1`.

Historical R0/R1/Phase 0 and Step 3 v1 artifacts are read-only inputs. R3
runners refuse to overwrite an existing v2 output.

## Execution order

1. Run deterministic repository, dataset, corpus, configuration, and cache
   identity checks.
2. Replay A0–A7 and create sanitized ablation evidence.
3. Run the selected profile through the real LangGraph path and one structured
   judge call per eligible answer.
4. Run cold/warm and failure benchmarks in isolated worker processes.
5. Evaluate all hard gates and write the decision recommendation.
6. Run the complete automated test/regression/integrity suite and inspect the
   final diff.
7. Request human/domain review for the owner-only local review bundle.

## Security and privacy controls

- API credentials stay in process environment only.
- External answer evaluation requires both explicit CLI approval flags.
- Provider errors abort the run and cannot be recorded as quality results.
- Published JSON/Markdown excludes raw queries, prompts, answers, snippets,
  document bodies, credentials, and raw exception messages.
- The local human-review bundle is stored under `.cache` with owner-only
  permissions and is excluded from Git.
- Telemetry and failure artifacts contain stable reason codes only.

## Verification gates

- Unit tests cover deterministic profile identity, hash/cache comparability,
  artifact redaction, explicit approval, citation validity/coverage,
  exact-not-found behavior, provider-failure handling, cold/warm labeling, and
  cross-platform RAM normalization.
- Retrieval hard gates compare A5 with the true pre-Track-A Hybrid baseline.
- Answer hard gates follow the remediation plan thresholds.
- Performance hard gates follow the Apple M4/16 GB initial guardrails.
- Human approval is never inferred from model-judge output.
