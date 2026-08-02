# Track A Closure Report v2

- Generated at: 2026-08-02T16:44:38+07:00
- Track A Status: `NOT_APPROVED`
- Closure policy: fail closed; ไม่อนุมัติจากผลเฉลี่ยเมื่อมี Blocking Gate ใดล้มเหลว
- Selected Profile: `track_a_balanced_v1` (measured candidate; not promoted)
- Next Track: `Additional Track A remediation`

## 1. Executive Summary

R0–R3 สร้างหลักฐานเชิงเทคนิคครบและ Retrieval quality ดีขึ้นชัดเจน แต่ Track A ยังปิดไม่ได้ เพราะ End-to-end Answer Gate, Performance Gate, Human/Domain review, Product/Business approval และ R3 authorization ยังไม่ผ่านครบ การสร้าง Enterprise Phase 0 v2 เป็นเพียง technical checkpoint และไม่อนุญาตให้เริ่ม Phase 1.

## 2. Scope and Environment

- Dataset: `lean-quality-v1`, 40 cases, controlled `TOP_K=6`
- Corpus: `knowledge_base.txt`, 54 sections
- Architecture: Keyword + Dense Hybrid → Candidate Expansion → Primary/Secondary Reranker → Answerability Gate → Context Builder → LangGraph answer pipeline → Validators
- Published report contains aggregate metrics, IDs, hashes, and stable reason codes only; no raw query, answer, prompt, credential, or document body.

## 3. Pre/Post Architecture and Retrieval Quality

| Metric | Pre-Track-A A0 | Post-Track-A A5 | Delta |
|---|---:|---:|---:|
| Recall@6 | 68.33% | 88.89% | 20.56% |
| MRR | 0.700 | 0.900 | +0.200 |
| Not-found discipline | 10.00% | 80.00% | 70.00% |

Ablation ยืนยันว่า Primary Reranker เพิ่ม Recall/MRR และ Score Gate ลด False Positive มากที่สุดในมิติ Safety ส่วน Context Builder รักษา Context header/budget validity ที่ 100%. Secondary path มี Recall 87.22% แต่ยังไม่ผ่าน Multi-section non-regression จึงคงเป็น emergency degradation path.

## 4. End-to-end Answer Quality

| Metric | Result | Required |
|---|---:|---:|
| Answer citation validity | 100.00% | 100% |
| Answer citation coverage | 91.01% | 100% |
| Negative exact not-found | 100.00% | ≥90% |
| Faithfulness | 99.25% | ≥95% |
| Answer relevance | 5.00/5 | ≥4.0/5 |
| Unsupported high-risk claims | 1 | 0 |

Blocking findings: citation coverage ต่ำกว่า 100%, มีหนึ่ง answerable case ตอบ not-found ทั้งที่มี expected evidence และมี unsupported high-risk claim หนึ่งรายการ.

## 5. Performance, RAM, and Failure Behavior

- Primary warm retrieval p95: 4,727 ms (target ≤3,000 ms)
- Primary local reranker p95: 4,203 ms (target ≤2,000 ms)
- Peak RSS: 2,160 MiB (target ≤6,144 MiB; pass)
- Primary timeout → Secondary: no unhandled exception
- Primary + Secondary failure → deterministic fail closed
- Concurrent Busy path: bounded and no unhandled exception
- Performance failures: `warm_retrieval_p95_above_3000_ms, primary_local_reranker_p95_above_2000_ms`

## 6. Closure Gates

| Gate | ผล | Evidence |
|---|---|---|
| R0 historical evidence immutability | PASS | 9 frozen identities match reviewed evidence. |
| R1 apples-to-apples evidence | PASS | Local/legacy checks pass, TOP_K=6 identities match, provider failures=0, fallback=0. |
| R3 retrieval quality | PASS | A5 passes controlled retrieval, language, context-header, and context-budget gates. |
| R2 runtime safety | PASS | Primary timeout uses Secondary; both failures fail closed; failure/concurrency paths have no unhandled exception. |
| R3 final-answer quality | FAIL | Automated end-to-end answer hard gate. |
| R3 performance | FAIL | Warm retrieval and Primary local reranker latency guardrails. |
| Human/Domain review | FAIL | PENDING_HUMAN_APPROVAL |
| Product/Business approval | FAIL | PENDING_PRODUCT_BUSINESS_APPROVAL |
| R3 decision authorization | FAIL | REJECT_AND_RETUNE; authorization=not granted by this record. |
| Enterprise Phase 0 v2 checkpoint | PASS | Versioned manifest/report match; Keyword/Semantic/Hybrid and all local gates are present. |

## 7. Risk Acceptance and Governance

- R3 recommendation: `REJECT_AND_RETUNE`
- Human/Domain review: `PENDING_HUMAN_APPROVAL (20 required cases)`
- Product/Business decision: `PENDING_PRODUCT_BUSINESS_APPROVAL`
- R4 authorization: `not granted by this record`
- Accepted Risks: `none`
- Parent Plan completion status was not updated because Closure authorization is not granted.

## 8. Known Limitations and Required Remediation

1. เพิ่ม deterministic citation-coverage validator พร้อม bounded repair และ fail-closed policy.
2. แก้ unsupported mixed-language high-risk claim และ retrieved-evidence/not-found contradiction.
3. ลด Primary latency หรือใช้ conditional reranking แล้ว rerun quality/performance gates.
4. Tune Secondary-specific threshold สำหรับ Multi-section.
5. ทำ Human/Domain review 20 cases และบันทึก Product/Business decision.

## 9. Evidence Bundle

| Artifact | SHA-256 | Bytes |
|---|---|---:|
| `docs/TRACK_A_DECISION_RECORD.md` | `4c92a6864ee780025ed0dd56625c709bfb9cd148899da11aea459df935030a6d` | 8174 |
| `phase0_v2_baseline_results.json` | `d59472f260cd90778106002a34271666f0e0434a45e9a2fe32e0e8272735bc58` | 66674 |
| `src/evaluation/configs/track_a_balanced_v1.json` | `d466f1a43fd7d48319b77be1c310a0da4016a18781ef4baf0cff026cdefa38ef` | 437 |
| `src/evaluation/datasets/enterprise_phase0_v2.manifest.json` | `cfd6778d4d2fbed28d65e025dd447ba59f31bc03adb8d0e4e44f5c4b2a97316e` | 5462 |
| `track_a_ablation_results_v2.json` | `1cac2890b7324ac987ed6c9fb2bb592fc027b592ff20a323c9ca509c6f9c2715` | 181046 |
| `track_a_answer_results_v2.json` | `cef2631d38f872e139440992dbd0c068ef64c5a4ec7871d46dfbc93f69f7b241` | 50439 |
| `track_a_performance_results_v2.json` | `092ae53f18cdb90ff30d111423194b4c2e91b7602c0e934782dcc72f9b382ca5` | 14764 |
| `track_a_pre_upgrade_baseline_v2.json` | `af9f6424fe5cdf1c02efc4d099280318010ff2dc78a55ee0b0214188ffdd8b37` | 213866 |

## 10. Final Decision

```text
Track A Status: NOT_APPROVED
Selected Profile: track_a_balanced_v1 (candidate only)
Accepted Risks: none
Next Track: Additional Track A remediation
```
