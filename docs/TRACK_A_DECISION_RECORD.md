# Track A R3 — Decision Record

## Status

- Recommendation: `REJECT_AND_RETUNE`
- Technical evidence status: complete
- Automated closure gate: failed
- Human/Domain review: `PENDING_HUMAN_APPROVAL` (20 required cases)
- Product/Business decision: `PENDING_PRODUCT_BUSINESS_APPROVAL`
- R4 closure authorization: not granted by this record

The current `track_a_balanced_v1` settings remain the measured technical
candidate profile. They are not approved as a final production/closure
profile because answer and performance hard gates failed.

## Evidence boundary

All comparisons use the R0-frozen 40-case `lean-quality-v1` dataset, identical
corpus identity, and controlled `TOP_K=6`. A0 is the true Pre-Track-A Hybrid
profile reconstructed by R1. A1–A7 replay the same prepared dense/Primary score
cache; A6 adds independently cached scores from the pinned Secondary model.

| Evidence | SHA-256 |
|---|---|
| `track_a_ablation_results_v2.json` | `1cac2890b7324ac987ed6c9fb2bb592fc027b592ff20a323c9ca509c6f9c2715` |
| `track_a_answer_results_v2.json` | `cef2631d38f872e139440992dbd0c068ef64c5a4ec7871d46dfbc93f69f7b241` |
| `track_a_performance_results_v2.json` | `092ae53f18cdb90ff30d111423194b4c2e91b7602c0e934782dcc72f9b382ca5` |
| `src/evaluation/configs/track_a_balanced_v1.json` | `d466f1a43fd7d48319b77be1c310a0da4016a18781ef4baf0cff026cdefa38ef` |

Published artifacts contain case IDs, section-title metadata, metrics, model
identity, and stable failure codes only. Raw questions, responses, snippets,
document bodies, prompts, credentials, and exception details are excluded.
Human review material is local under `.cache`, Git-ignored, and owner-readable
only.

## Decision questions

### 1. How much Retrieval Quality did Track A add?

Against true Pre-Track-A Hybrid A0 at the same `TOP_K=6`, official A5 changed:

- Recall@6: 68.33% → 88.89% (`+20.56 pp`)
- MRR: 0.700 → 0.900 (`+0.200`)
- Not-found discipline: 10% → 80% (`+70 pp`)
- Thai recall: 10% → 70% (`+60 pp`)
- Context header and budget validity: 100%

The Retrieval hard gate passed.

### 2. Which component produced the largest improvement?

- Current hybrid gates (A0→A1) improved Recall by 13.33 pp and Thai recall by
  40 pp, but without answerability still returned evidence for every negative.
- Candidate expansion from 6 to 12 (A1→A2) produced no additional quality on
  this dataset.
- Primary reranking (A2→A3) added 7.22 pp Recall and 0.133 MRR.
- The score gate (A3→A4) reduced negative false positives from 100% to 20%
  without measured Recall loss.
- Context Builder (A4→A5) preserved measured retrieval quality while enforcing
  100% header/budget validity.

The score gate produced the largest Safety improvement; current hybrid
retrieval and Primary reranking produced the largest Recall/ranking gains.

### 3. Is Primary reranking worth its Latency/RAM cost?

Against reranker-disabled retrieval, Candidate 12 added approximately
`3,835 ms` to E2E p95 and `2,086 MiB` peak RSS in this run. It improved Recall
by 7.22 pp and MRR by 0.133 before the score gate; together with the score gate,
Not-found discipline improved by 80 pp.

The quality gain is material, but current Primary performance misses both
initial guardrails:

- Primary local reranker p95: 4,203 ms (target ≤2,000 ms)
- Candidate 12 retrieval p95: 4,727 ms (target ≤3,000 ms)
- Peak RSS: 2,160 MiB (target ≤6,144 MiB; pass)

Primary should not be promoted under the current synchronous always-on policy
without performance retuning or conditional invocation.

### 4. How much Candidate 12 quality does Candidate 30 retain?

The R0-frozen Step 3 quality-max replay measured Candidate 30 at 95.56% Recall
and 0.967 MRR. Candidate 12 retains approximately 93.0% of that Recall and
93.1% of that MRR, while keeping the same 80% retrieval not-found discipline.

Current R3 stress measurement found:

- Candidate 12 E2E p95: 4,727 ms
- Candidate 30 observed E2E p95: 10,046 ms (`2.13×`)
- Candidate 30 timed out on the ninth observed attempt (11.1% timeout rate);
  sampling stopped to avoid contaminating later values with `WORKER_BUSY`.

Candidate 30 is rejected for the current 16 GB target runtime.

### 5. What did the Answerability Gate change?

A3→A4 reduced False Positive rate from 100% to 20% (`-80 pp`) while Recall and
MRR remained unchanged at 88.89% and 0.900. It is useful, but retrieval-level
not-found discipline remains below the 90% target and cannot alone prove final
answer safety.

### 6. Did Final Answer Quality pass?

No. Strong axes were:

- Citation-title validity: 100%
- Negative exact not-found: 100%
- Faithfulness: 99.25%
- Relevance: 5.0/5
- Completeness: 4.90/5
- Thai-script appropriateness: 100%

Blocking failures were:

- Citation coverage: 91.01%, below 100%
- One answerable case returned not-found despite expected evidence being in
  context
- One unsupported high-risk claim
- Specific-data discipline: 93.10%

The coverage implementation is deliberately conservative and counted five
short Markdown structural labels; private inspection also confirmed three
genuinely uncited factual sentences. Therefore the 100% target still fails
even after accounting for structural-label false positives.

### 7. Does failure preserve Safety?

Yes at the runtime boundary:

- Injected Primary timeout used Secondary with no unhandled exception.
- Injected Primary+Secondary failure returned no evidence through fail-closed.
- Concurrent requests exercised `WORKER_BUSY`; one of two requests used
  Secondary and neither escaped as an unhandled exception.
- Every detected failure completed within the overall timeout.

These results establish graceful degradation, not quality equivalence.

### 8. Is Secondary worth keeping?

Secondary is materially faster and smaller:

- Warm local p95: 1,020 ms versus Primary 4,203 ms
- Warm E2E p95: 1,675 ms versus Primary 4,727 ms
- Peak RSS: 1,423 MiB versus Primary 2,160 MiB

However, A6 regressed Multi-section recall below A0 and failed the Retrieval
quality gate. Keep Secondary only as an observable emergency degradation path
for now; do not select it as the default or claim equivalent quality. For
high-risk/multi-section intents, fail-closed or a reviewed conditional policy
is safer until Secondary-specific tuning passes.

### 9. Is the 80% Not-found issue resolved or accepted?

Final-answer negative exact-not-found reached 100%, so the generator's
specific-data discipline resolved all ten reviewed negative cases in this run.
No written risk acceptance is required for that metric. Nevertheless, the
unsupported high-risk claim occurred in an answerable/mixed case, so overall
answer Safety is not approved. There is no Product/Business risk acceptance on
record.

### 10. What is the Official Runtime Profile?

The measured candidate remains:

```text
RETRIEVAL_PROFILE=track_a_balanced_v1
SEARCH_MODE=hybrid
CANDIDATE_K=12
TOP_K=6
HYBRID_MIN_COSINE=0.20
RERANKER_MIN_SCORE=0.01
RERANKER_BATCH_SIZE=4
RERANKER_TIMEOUT_SECONDS=10
MAX_CONTEXT_CHARS=6000
RERANKER_FAILURE_POLICY=fail_closed
RERANKER_FALLBACK_MIN_SCORE=0.01
```

It is the official R3 **candidate/configuration identity**, not an approved
closure or production promotion. Default code remains `keyword_safe` when no
reviewed environment profile is selected.

## Required retuning before approval

1. Add a deterministic post-generation citation-coverage validator with one
   bounded repair attempt, then fail closed if any factual sentence remains
   uncited or cites an unavailable title.
2. Investigate the mixed-language unsupported high-risk case with Human/Domain
   review and strengthen specific-data validation.
3. Fix the retrieved-evidence/not-found contradiction for the multi-section
   case.
4. Reduce Primary latency through candidate-text limits, conditional
   reranking, a smaller multilingual model, quantization, or asynchronous
   serving; rerun all quality gates after any change.
5. Tune a Secondary-specific threshold/profile and explicitly remeasure
   Multi-section quality before considering it as default.
6. Complete the 20-case Human/Domain review and record Product/Business
   approval or rejection.
