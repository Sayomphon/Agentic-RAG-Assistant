# Track A M1 Remediation Engineering Evidence

> **Status:** M1 engineering evidence only — not Official R3 v3 evidence and
> not merge/release authorization.

## Scope and identity

- Date: 2026-08-02
- Dataset: `lean-quality-v1`, 40 cases
- Corpus sections: 54
- Controlled `TOP_K`: 6
- Primary model: `BAAI/bge-reranker-v2-m3`
- Primary revision: `b4019bcd5cae485c342f61fe5889c2c800c5abec`
- Device path: CPU; MPS unavailable in the measured environment
- Model source: immutable local cache; no model download
- Candidate profile: `src/evaluation/configs/track_a_balanced_v2.json`

Historical v2 artifacts were not modified. These measurements select an M1
candidate for the complete, clean-worktree R3 v3 rerun required by M2.

## Root-cause measurements

The frozen R3 v2 result measured Primary reranker p95 at `4,202.9 ms` and
warm retrieval p95 at `4,727.0 ms`. A same-configuration control rerun
measured `2,161.2 ms` and `2,855.4 ms`, respectively, demonstrating material
host-load sensitivity. The candidate therefore had to pass repeated runs with
margin rather than rely on the fastest observation.

All 451 Candidate-12 query/document pairs were tokenized from the same
prepared cache:

| Token statistic | Value |
|---|---:|
| p50 | 187 |
| p95 | 216 |
| p99 | 225 |
| Maximum | 234 |

Because every pair is shorter than 256 tokens, changing only `max_length`
from 512 to 256 cannot reduce the current tensor sizes. The anomalous
256-token timeout run was rejected as contaminated rather than selected.

## Controlled performance experiments

| Candidate | Max length | Batch | CPU threads | Primary p95 | E2E p95 | Outcome |
|---:|---:|---:|---:|---:|---:|---|
| 12 | 512 | 4 | 4 | 2,161 ms | 2,855 ms | Control; Primary gate missed |
| 12 | 256 | 4 | 4 | 9,916 ms | 10,319 ms | Rejected; timeout/host contamination |
| 12 | 256 | 12 | 4 | 3,699 ms | 5,415 ms | Rejected |
| 10 | 512 | 4 | 4 | 1,850 ms | 2,576 ms | Passed once, not reproducible |
| 10 | 512 | 4 | 4 | 3,273 ms | 3,842 ms | Rejected |
| 10 | 512 | 4 | 8 | 2,695 ms | 3,193 ms | Rejected |
| 10 | 128 | 4 | 4 | 1,135 ms | 1,940 ms | Passed |
| 10 | 128 | 4 | 4 | 1,728 ms | 2,210 ms | Passed repeat |

Both selected-configuration runs stayed below 2,000 ms Primary p95 and
3,000 ms warm retrieval p95, had no timeout or unexpected fallback, and used
approximately 2.1–2.2 GiB peak RSS against the 6 GiB gate.

## Quality replay with newly computed model scores

Cached 512-token reranker scores were not reused to approve the 128-token
candidate. Scores were recomputed locally for all 40 cases using Candidate 10
and `max_length=128`.

| Metric | A5 / Candidate 12 | M1 Candidate v2 | Result |
|---|---:|---:|---|
| Overall Recall@6 | 0.889 | 0.900 | No regression |
| MRR | 0.900 | 0.900 | No regression |
| English recall | 1.000 | 1.000 | No regression |
| Thai recall | 0.700 | 0.700 | No regression |
| Mixed recall | 1.000 | 1.000 | No regression |
| Multi-section recall | 0.933 | 1.000 | Improved |
| Negative discipline | 0.800 | 0.800 | No regression |
| Context header validity | 1.000 | 1.000 | Pass |
| Context budget validity | 1.000 | 1.000 | Pass |

Candidate 8 was rejected because Overall Recall fell to `0.822` and Thai
recall fell to `0.500`. Batch 12 and eight-thread configurations were rejected
because they missed the latency gates.

## Secondary model policy

The existing A6 evidence shows Secondary multi-section recall regression.
Profile v2 therefore uses:

```text
secondary_policy = emergency_low_risk_only
```

Primary failure may try Secondary once for a low-risk, single-section intent.
High-risk or multi-section intent fails closed even when Secondary inference
completes successfully. Policy rejections are exposed through
`secondary_policy_rejection_count` without logging query or document content.

## Required next gate

M2 must rerun the complete versioned R3 suite from one clean source commit,
including A0–A7, end-to-end answer evaluation, performance/failure scenarios,
evidence integrity validation, and Human-review bundle generation. Until that
run passes, `track_a_balanced_v2` remains a measured candidate only.
