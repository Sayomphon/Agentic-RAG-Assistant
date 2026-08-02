# Track A R1 — Pre-Upgrade Comparative Baseline v2

- Generated at: `2026-07-28T15:32:01+07:00`
- Evaluation commit: `f4a85cd1857a735d7e7b219571db27e1d705c8ef`
- Pre-Track-A commit: `5e8537b3d0db8395e2a12dc008f9e3184e2bda6f`
- Post-Track-A commit: `fd3ac95f3f2ecc0ae3df9746d329802f656d1432`
- Dataset SHA-256: `3f80666e6dfd77b7a668eb82c3a5dc6f79a8eed12a97988fc499bdccaf55ff3f`
- Corpus SHA-256: `e09382f19b18ef2a52e1e93826e81852ee649d4bb5ddccb74a1865b8b60fe5c4`
- Provider failures: `0`
- Unexpected fallbacks: `0`

## Pre-Track-A operational default — TOP_K=4

| mode | hit@k | recall@k | MRR | not-found | p50 | p95 |
|---|---:|---:|---:|---:|---:|---:|
| keyword | 66.7% | 63.9% | 0.650 | 30.0% | 0.1 ms | 0.1 ms |
| semantic | 70.0% | 67.5% | 0.667 | 50.0% | 595.7 ms | 6836.2 ms |
| hybrid | 70.0% | 68.3% | 0.700 | 10.0% | 380.3 ms | 996.7 ms |

## Pre-Track-A controlled profile — TOP_K=6

| mode | hit@k | recall@k | MRR | not-found | p50 | p95 |
|---|---:|---:|---:|---:|---:|---:|
| keyword | 66.7% | 63.9% | 0.650 | 30.0% | 0.1 ms | 0.1 ms |
| semantic | 70.0% | 68.3% | 0.667 | 50.0% | 388.9 ms | 580.1 ms |
| hybrid | 70.0% | 68.3% | 0.700 | 10.0% | 556.7 ms | 1340.1 ms |

## Post-Track-A selected profile — TOP_K=6

| mode | hit@k | recall@k | MRR | not-found | p50 | p95 |
|---|---:|---:|---:|---:|---:|---:|
| keyword | 66.7% | 63.9% | 0.650 | 30.0% | 0.1 ms | 0.3 ms |
| semantic | 70.0% | 68.3% | 0.667 | 50.0% | 1010.1 ms | 2478.1 ms |
| hybrid | 90.0% | 88.9% | 0.900 | 80.0% | 1870.9 ms | 2943.7 ms |

## Hybrid before/after deltas

| comparison | pre TOP_K | post TOP_K | Δ recall | Δ MRR | Δ not-found | Δ p95 |
|---|---:|---:|---:|---:|---:|---:|
| operational_default | 4 | 6 | +20.6% | +0.200 | +70.0% | +1947.1 ms |
| controlled_top_k_6 | 6 | 6 | +20.6% | +0.200 | +70.0% | +1603.7 ms |

Operational comparison answers whether deployed defaults improved. Controlled comparison fixes TOP_K=6 to isolate the Track A quality pipeline from the context-count increase.

## Verification and data boundary

- Current and legacy worktrees were clean before external calls.
- The legacy runtime was detached at the recorded commit and used a separate virtual environment.
- Dataset, corpus, dependency, worker, and historical Phase 0 identities are pinned by SHA-256.
- The existing corpus embedding cache was required; rebuilding it through the API was not permitted.
- Published artifacts contain case IDs, labels, retrieved titles, metrics, and allowlisted environment metadata only.
- Raw queries, document bodies, prompts, credentials, and raw environment variables are excluded.
