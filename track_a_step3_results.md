# Track A — Step 3 Measure & Tune

- Generated at: 2026-07-28T12:35:26+07:00
- Dataset: `src/evaluation/datasets/lean_quality_v1.json` (40 cases)
- Frozen baseline SHA-256: `8fbbc0d33ac9ab8a678c5cd3154eb397a436a99948360f1a9928dbea9618b3c7`
- External data boundary: evaluation query strings only; no knowledge-base body or snippet is sent.
- Prepared score cache: hit (40 query strings created the cache; 0 sent in this run).
- Answer-level evaluation: not run.

## Verification gates

| check | result | count | duration |
|---|---|---:|---:|
| unit_tests | PASS | 82 | 3221.3 ms |
| keyword_regression | PASS | 15 | 103.8 ms |

## Before / after

| configuration | recall@k | MRR | not-found discipline | Δ recall | Δ MRR | Δ not-found |
|---|---:|---:|---:|---:|---:|---:|
| Step 1 baseline | 63.9% | 0.650 | 30.0% | — | — | — |
| Step 2 defaults | 69.2% | 0.700 | 10.0% | +5.3% | +0.050 | -20.0% |
| Step 3 selected | 88.9% | 0.900 | 80.0% | +25.0% | +0.250 | +50.0% |
| Selected without reranker | 81.7% | 0.767 | 0.0% | +17.8% | +0.117 | -30.0% |

## Category evidence

| category | metric | baseline | selected | delta |
|---|---|---:|---:|---:|
| english_answerable | recall | 100.0% | 100.0% | +0.000 |
| english_answerable | MRR | 1.000 | 1.000 | +0.000 |
| thai_answerable | recall | 0.0% | 70.0% | +0.700 |
| thai_answerable | MRR | 0.000 | 0.700 | +0.700 |
| mixed_answerable | recall | 100.0% | 100.0% | +0.000 |
| mixed_answerable | MRR | 1.000 | 1.000 | +0.000 |
| negative | not-found discipline | 30.0% | 80.0% | +0.500 |
| multi_section | recall | 83.3% | 93.3% | +0.100 |
| multi_section | MRR | 0.900 | 1.000 | +0.100 |

Category recall is a blocking non-regression gate. Category MRR movement remains visible here and is accepted only when the overall MRR, recall, Thai recall, and not-found gates pass.

## Selected configuration

- Quality-max profile: `c30-k6-cos0.10-rron-0.01-ctx6000` (score=0.903)
- Balanced runtime profile: `c12-k6-cos0.20-rron-0.01-ctx6000` (score=0.837, 92.6% quality retained)
- `CANDIDATE_K=12`
- `TOP_K=6`
- `HYBRID_MIN_COSINE=0.20`
- `RERANKER_MIN_SCORE=0.01`
- `RERANKER_BATCH_SIZE=4`
- `RERANKER_TIMEOUT_SECONDS=10`
- `MAX_CONTEXT_CHARS=6000`
- Citation validity: 100.0%
- Context truncation rate: 0.0%
- Thai recall: 70.0%
- Context p95: 4461 characters

## Latency

- The online estimate adds captured query-embedding latency to a second local reranker/context benchmark for the selected profile.
- Estimated online average: 1917.7 ms
- Estimated online p95: 2361.7 ms
- Query embedding p95: 889.8 ms
- Local reranker + context p95: 1612.1 ms

## Reranker decision gate

- Quality-score delta versus the same profile without reranking: +0.325
- Reranker score range: 0.0000–0.9982 (p50=0.0001, p95=0.1036)
- Decision: keep the reranker enabled when the selected profile passes all hard gates and improves the composite score; otherwise retain it as optional.

## Top profiles

| profile | score | recall | MRR | not-found | Thai recall | gates |
|---|---:|---:|---:|---:|---:|---|
| `c30-k6-cos0.00-rron-0.01-ctx4000` | 0.903 | 95.6% | 0.967 | 80.0% | 90.0% | PASS |
| `c30-k6-cos0.00-rron-0.01-ctx6000` | 0.903 | 95.6% | 0.967 | 80.0% | 90.0% | PASS |
| `c30-k6-cos0.00-rron-0.01-ctx12000` | 0.903 | 95.6% | 0.967 | 80.0% | 90.0% | PASS |
| `c30-k6-cos0.10-rron-0.01-ctx4000` | 0.903 | 95.6% | 0.967 | 80.0% | 90.0% | PASS |
| `c30-k6-cos0.10-rron-0.01-ctx6000` | 0.903 | 95.6% | 0.967 | 80.0% | 90.0% | PASS |
| `c30-k6-cos0.10-rron-0.01-ctx12000` | 0.903 | 95.6% | 0.967 | 80.0% | 90.0% | PASS |
| `c12-k6-cos0.00-rron-0.01-ctx4000` | 0.837 | 88.9% | 0.900 | 80.0% | 70.0% | PASS |
| `c12-k6-cos0.00-rron-0.01-ctx6000` | 0.837 | 88.9% | 0.900 | 80.0% | 70.0% | PASS |
| `c12-k6-cos0.00-rron-0.01-ctx12000` | 0.837 | 88.9% | 0.900 | 80.0% | 70.0% | PASS |
| `c12-k6-cos0.10-rron-0.01-ctx4000` | 0.837 | 88.9% | 0.900 | 80.0% | 70.0% | PASS |

## Security and reproducibility

- The Step 1 baseline is read-only and was not overwritten.
- Dataset and corpus SHA-256 values must match the frozen baseline.
- Query embeddings are requested once per case; the tuning grid replays captured scores locally.
- Local model loading is cache-only and remote model code is disabled.
- Reports exclude raw queries, prompts, API keys, environment variables, and document bodies.
