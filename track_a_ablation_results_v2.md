# Track A R3 — Component Ablation

- Generated at: 2026-08-02T15:27:29+07:00
- Controlled comparison: 40 frozen cases, identical corpus, `TOP_K=6`, metric version `track-a-r3-metrics-v1`.
- A0 source: R1 true Pre-Track-A Hybrid controlled evidence.
- A1–A7 source: the same versioned prepared dense/score cache; Secondary scores use the same candidate union.
- Published boundary: no raw query, answer, prompt, snippet, document body, credential, or provider error text.

## Results

| ID | Configuration | Recall@6 | MRR | Not-found | Thai recall | Avg hits | Gate |
|---|---|---:|---:|---:|---:|---:|---|
| A0 | Pre-Track-A Hybrid | 68.3% | 0.700 | 10.0% | 10.0% | 2.42 | PASS |
| A1 | Current Hybrid; reranker and answerability off | 81.7% | 0.767 | 0.0% | 50.0% | 5.92 | PASS |
| A2 | Candidate expansion only | 81.7% | 0.767 | 0.0% | 50.0% | 5.92 | PASS |
| A3 | Candidate expansion and Primary reranker | 88.9% | 0.900 | 0.0% | 70.0% | 5.92 | PASS |
| A4 | A3 with Primary score gate | 88.9% | 0.900 | 80.0% | 70.0% | 2.38 | PASS |
| A5 | Official full pipeline | 88.9% | 0.900 | 80.0% | 70.0% | 2.38 | PASS |
| A6 | Primary failure with Secondary model | 87.2% | 0.844 | 70.0% | 70.0% | 2.52 | FAIL |
| A7 | Both rerankers fail; fail closed | 0.0% | 0.000 | 100.0% | 0.0% | 0.00 | FAIL |

## Official A5 versus A0

- Recall@6: 68.3% → 88.9% (+20.6%)
- MRR: 0.700 → 0.900 (+0.200)
- Not-found discipline: 10.0% → 80.0% (+70.0%)
- Context header validity: 100.0%
- Context budget validity: 100.0%

## Component deltas

| Transition | Δ Recall | Δ MRR | Δ Not-found discipline |
|---|---:|---:|---:|
| A1 → A2 | +0.0% | +0.000 | +0.0% |
| A2 → A3 | +7.2% | +0.133 | +0.0% |
| A3 → A4 | +0.0% | +0.000 | +80.0% |
| A4 → A5 | +0.0% | +0.000 | +0.0% |

A6 is a degradation-quality measurement, not an assertion that the Secondary model is quality-equivalent. A7 intentionally loses answerable recall and demonstrates deterministic fail-closed safety.
