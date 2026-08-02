# Track A R3 — Performance and Failure Benchmark

- Generated at: 2026-08-02T15:42:18+07:00
- Host: macOS-26.3.1-arm64-arm-64bit / arm64
- Model download time is reported separately as `0 ms`: every scenario ran from an immutable local cache with remote access disabled.
- Cold model scenarios execute in fresh subprocesses; warm scenarios run all 40 frozen cases.
- Query embedding latency is replayed from the verified prepared cache; local reranker/context latency is measured in this run.

## Scenario matrix

| Scenario | State | Load ms | Reranker p95 | E2E p95 | Peak RSS | Secondary use | Result |
|---|---|---:|---:|---:|---:|---:|---|
| Primary model cold start | cold | 5330.7 | 3122.3 ms | 4250.7 ms | 2004.9 MiB | 0.0% | PASS |
| Primary model warm inference | warm | 4903.8 | 4202.9 ms | 4727.0 ms | 2160.3 MiB | 0.0% | PASS |
| Secondary model cold start | cold | 5548.3 | 1929.0 ms | 3057.5 ms | 1171.9 MiB | 0.0% | PASS |
| Secondary model warm inference | warm | 7400.8 | 1019.6 ms | 1675.4 ms | 1423.0 MiB | 0.0% | PASS |
| Reranker disabled | warm | 0.0 | 0.0 ms | 892.0 ms | 74.5 MiB | 0.0% | PASS |
| Candidate 12 | warm | 4903.8 | 4202.9 ms | 4727.0 ms | 2160.3 MiB | 0.0% | PASS |
| Candidate 30 | warm | 5185.4 | 9383.6 ms | 10046.2 ms | 2159.3 MiB | 0.0% | PASS |
| Primary timeout → Secondary | failure | 13498.9 | 0.0 ms | 0.0 ms | 1080.2 MiB | 100.0% | PASS |
| Both fail → Fail closed | failure | 0.0 | 0.0 ms | 0.0 ms | 74.6 MiB | 100.0% | PASS |
| Concurrent requests / Busy policy | concurrent | 0.0 | 0.0 ms | 0.0 ms | 74.4 MiB | 50.0% | PASS |

## Guardrails

- Warm retrieval p95 (Candidate 12): 4727.0 ms / ≤3000 ms
- Primary local reranker p95: 4202.9 ms / ≤2000 ms
- Maximum peak RSS: 2160.3 MiB / ≤6144 MiB
- Both-fail closed: True
- Concurrent Busy path Secondary usage: 50.0%
- Overall performance gate: **FAIL** — warm_retrieval_p95_above_3000_ms, primary_local_reranker_p95_above_2000_ms
