# Track A Closure & Remediation Plan

> แผนปิดช่องว่างของ **Track A — Lean Quality Track** สำหรับ Step 1 — Mini Baseline, Step 2 — Quality Upgrades และ Step 3 — Measure & Tune โดยยึดหลัก Apples-to-apples Evaluation, End-to-end Answer Quality, Fail-safe Degradation และ Reproducible Evidence ก่อนประกาศว่า Track A เสร็จสมบูรณ์

---

## 1. Document Control

| รายการ | รายละเอียด |
|---|---|
| Document | Track A Closure & Remediation Plan |
| Version | 1.0 |
| Created | 2026-07-28 |
| Project | Agentic_RAG |
| Parent plan | `ENTERPRISE_AGENTIC_RAG_IMPLEMENTATION_PLAN.md` v2.0 |
| Baseline source commit | `5e8537b` — Track A Step 1 Mini Baseline ก่อน Quality Upgrades |
| Current implementation commit | `fd3ac95` — Enterprise Phase 0 baseline หลัง Track A |
| Current corpus | `knowledge_base.txt`, 54 sections |
| Evaluation dataset | `lean-quality-v1`, 40 cases |
| Target owner | AI Solution Engineer / AI Engineer |
| Primary language | Thai พร้อม English technical terms |
| Execution constraint | เอกสารนี้เป็นแผนเท่านั้น การสร้างเอกสารไม่รัน Test, Evaluation, Model หรือ API Call |

---

## 2. Executive Decision

Track A มี Component หลักครบและใช้งานได้แล้ว ได้แก่ Thai-aware tokenization, Candidate Expansion, Local Multilingual Reranker, Context Builder และ Answerability Threshold แต่ยังไม่ควรประกาศว่าเสร็จสมบูรณ์ เพราะหลักฐานปัจจุบันยังมีช่องว่างสำคัญ:

1. Step 1 baseline ที่ใช้ตัดสิน Step 3 วัดเฉพาะ Keyword ขณะที่ผลหลังปรับเป็น Hybrid + Dense + Reranker จึงไม่ใช่ Apples-to-apples comparison
2. ยังไม่มี End-to-end Answer Evaluation หลังเปิดใช้ Tuned Profile
3. Metric ชื่อ `citation_validity` ใน Step 3 ตรวจเพียง Context Header ไม่ได้ตรวจ Citation ใน Final Answer
4. เมื่อ Reranker ล้ม เส้นทาง Fallback ข้าม Reranker Answerability Gate และผลทดลอง Reranker-off มี Not-found discipline เท่ากับ 0%
5. Decision Gate ยังไม่มี Reranker-off latency, cold-start time, peak RAM และ fallback latency
6. Internal safety target กำหนดไว้ 90% แต่ Selected Profile ทำได้ 80%
7. Primary Reranker ยังไม่มี Smaller/Quantized model fallback ที่ Implement และทดสอบจริง
8. Runtime default, `.env.example` และ README อธิบาย `SEARCH_MODE` ไม่ตรงกันทั้งหมด

ดังนั้นสถานะปัจจุบันให้ถือเป็น:

```text
Track A Implementation:        substantially complete
Track A Retrieval Validation:  partially complete
Track A Answer Validation:     incomplete
Track A Closure:               not approved
```

งานในเอกสารนี้ต้องปิดสามด้านพร้อมกัน:

```text
Evidence correctness
+ Runtime safety
+ End-to-end answer quality
= Track A closure
```

---

## 3. Evidence Snapshot ณ จุดเริ่มแผน

### 3.1 Existing Artifacts

| Artifact | บทบาท | สถานะ |
|---|---|---|
| `baseline_results.json/.md` | Track A Step 1 baseline | มีเฉพาะ Keyword บน 40 cases |
| `track_a_step3_results.json/.md` | Tuning 540 profiles และ Selected Profile | มี Retrieval/Context metrics แต่ไม่มี Final-answer evaluation |
| `phase0_baseline_results.json/.md` | Post-Track-A operational baseline ที่ commit `fd3ac95` | มี Keyword/Semantic/Hybrid และ Runtime health |
| `answer_eval_results.md` | Historical answer-level evaluation | รันก่อน Track A, 17 cases, `TOP_K=4` |
| `evaluation_results.md` | Historical comparative retrieval | รันก่อน Track A แต่ใช้ Dataset 15 cases |
| `docs/RETRIEVER_CONTRACT.md` | Retriever contract 1.0.0 | ใช้เป็น Compatibility Gate |

### 3.2 Recorded Test Evidence

ผลที่มีอยู่แล้วและไม่ต้องรันซ้ำเพื่อเขียนแผนนี้:

| Baseline | Unit tests | Keyword regression | Contract tests |
|---|---:|---:|---:|
| Track A Step 1 | 45 PASS | 15 PASS | ยังไม่มีในเวลานั้น |
| Track A Step 3 | 82 PASS | 15 PASS | ยังไม่แยกเป็น gate |
| Enterprise Phase 0 (`fd3ac95`) | 107 PASS | 15 PASS | 8 PASS |

### 3.3 Current Post-Track-A Retrieval Metrics

จาก Enterprise Phase 0 baseline:

| Mode | Recall@K | MRR | Not-found discipline | p95 latency |
|---|---:|---:|---:|---:|
| Keyword | 63.9% | 0.650 | 30% | 0.3 ms |
| Semantic | 68.3% | 0.667 | 50% | 2,478.1 ms |
| Hybrid + Reranker | 88.9% | 0.900 | 80% | 2,943.7 ms |

ตัวเลขเหล่านี้เป็นหลักฐานที่ดีสำหรับ **ระบบปัจจุบัน** แต่ยังไม่ตอบว่าการปรับ Track A เพิ่มคุณภาพจาก Pre-Track-A Hybrid เท่าใด

---

## 4. Scope

### 4.1 In Scope

- สร้าง Pre-Track-A comparative baseline จาก commit ก่อน Step 2
- ทำ Apples-to-apples comparison บน Dataset และ Corpus เดียวกัน
- เพิ่ม Component Ablation เพื่อแยกผลของ Candidate Expansion, Reranker, Answerability Gate และ Context Builder
- เพิ่ม End-to-end Answer Evaluation ผ่าน LangGraph จริง
- แยก Context Header Validity ออกจาก Final-answer Citation Validity
- ทำ Safe Degradation เมื่อ Primary/Secondary Reranker ล้ม
- เพิ่ม Smaller/Quantized fallback model configuration
- วัด Warm latency, Cold-start latency, Peak RAM และ Failure-path latency
- ทำ Configuration และ Documentation ให้มี Source of Truth เดียว
- ออก Track A Closure Report และ Decision Record
- Re-baseline Enterprise Phase 0 หลัง Track A closure

### 4.2 Out of Scope

- Qdrant และ Incremental Ingestion
- Tenant/ACL/Classification filtering
- FastAPI
- OpenTelemetry/Grafana
- Enterprise SSO/PDPA/DR
- Fine-tuning LLM/Embedding/Reranker
- การเปลี่ยน Knowledge Base เป็นภาษาไทยทั้งชุด
- การเพิ่ม Autonomous Tool หรือ Write Action

---

## 5. Engineering Principles

### 5.1 Never Overwrite Historical Evidence

ห้ามเขียนทับ:

- `baseline_results.json/.md`
- `track_a_step3_results.json/.md`
- `phase0_baseline_results.json/.md`

Artifact ใหม่ต้องใช้ Version ใหม่และอ้างถึง Artifact เดิมด้วย SHA-256

### 5.2 Apples-to-apples Before/After

การเปรียบเทียบที่ใช้ตัดสินต้องเหมือนกันอย่างน้อย:

- Dataset version และ hash
- Corpus version และ hash
- Query text
- Expected titles
- Embedding model
- Final `TOP_K`
- Metric definitions
- Failure policy
- Execution environment หรือมี Environment delta ระบุชัด

หาก Configuration ต่างกันเพราะเป็นส่วนหนึ่งของการ Tune ต้องรายงานทั้ง:

1. **Controlled comparison** — เปลี่ยนทีละ Component
2. **Operational comparison** — เปรียบเทียบ Default เดิมกับ Selected Profile ใหม่

### 5.3 Separate Retrieval, Context and Answer Metrics

ห้ามใช้ชื่อ Metric เดียวแทนคนละ Layer:

```text
Retrieval citation/provenance
≠ Context header validity
≠ Final-answer citation validity
≠ Citation coverage
```

### 5.4 Fail Safe on Quality-component Failure

Reranker failure ต้องไม่ทำให้ระบบส่ง Evidence ที่อ่อนลงอย่างเงียบ ๆ จนเพิ่มความเสี่ยง Hallucination

Default policy:

```text
Primary Reranker
→ Secondary Smaller Reranker
→ Conservative deterministic fallback
→ Deterministic not-found
```

Fusion-order fallback แบบไม่ผ่าน Gate อนุญาตเฉพาะ Explicit Lab Mode

### 5.5 Preserve Retriever Contract

ห้ามเปลี่ยน Signature:

```python
class Retriever(Protocol):
    def search(self, query: str, top_k: int) -> list[ScoredChunk]:
        ...
```

หากเพิ่ม Metadata ต้องเป็น Optional field หรืออยู่ใน Wrapper/Telemetry เพื่อไม่ทำลาย Contract 1.0.0

---

## 6. Delivery Strategy

งานแบ่งเป็น 5 Workstreams ตาม Dependency:

```text
R0 — Freeze & Coordinate
  ↓
R1 — Close Step 1 Evidence Gap
  ↓
R2 — Close Step 2 Runtime/Safety Gap
  ↓
R3 — Close Step 3 Measurement Gap
  ↓
R4 — Final Closure & Re-baseline
```

Estimated effort:

| Workstream | ระยะเวลา |
|---|---:|
| R0 — Freeze & Coordinate | 0.25–0.5 วัน |
| R1 — Step 1 Closure | 0.5–1 วัน |
| R2 — Step 2 Remediation | 1.5–2.5 วัน |
| R3 — Step 3 Validation | 1.5–2.5 วัน |
| R4 — Closure & Re-baseline | 0.5 วัน |
| **รวม** | **4–7 วันทำงาน** |

เวลาไม่รวมการรอ Approval สำหรับ API Call, Model Download หรือ Business/Domain Review

---

# Part A — Workstream R0: Freeze & Coordinate

## 7. R0 Objective

ป้องกัน Evidence ปนกันระหว่าง Historical Baseline, Remediation Code และ Enterprise Phase 0

## 7.1 R0-01: Create Dedicated Remediation Branch

Recommended branch:

```text
fix/track-a-closure
```

ฐาน branch คือ commit `fd3ac95`

Rules:

- Working tree ต้องสะอาดก่อนเริ่ม
- ห้ามแก้ Artifact เดิม
- ทุก Evaluation Run ต้องบันทึก Git commit SHA
- ห้ามรัน Official Evaluation จาก Dirty worktree

## 7.2 R0-02: Freeze Input Identities

บันทึก:

- `lean_quality_v1.json` SHA-256
- `knowledge_base.txt` corpus SHA-256
- `requirements.txt` SHA-256
- `requirements-dev.txt` SHA-256
- Retriever contract version
- Prompt versions หรือ Source SHA ของ Agent prompts
- Embedding model
- Primary/Secondary reranker model revisions

## 7.3 R0-03: Define New Artifact Names

ใช้ชื่อใหม่:

```text
track_a_pre_upgrade_baseline_v2.json
track_a_pre_upgrade_baseline_v2.md
track_a_ablation_results_v2.json
track_a_ablation_results_v2.md
track_a_answer_results_v2.json
track_a_answer_results_v2.md
track_a_performance_results_v2.json
track_a_performance_results_v2.md
track_a_closure_report_v2.md
docs/TRACK_A_DECISION_RECORD.md
```

## 7.4 R0 Exit Criteria

- [x] Branch แยกจาก Enterprise Phase 0 ชัดเจน
- [x] Working tree สะอาด
- [x] Historical artifacts เป็น Read-only
- [x] Input hashes ถูกบันทึก
- [x] Artifact naming/versioning ได้รับการยืนยัน

R0 verification record:

```text
Branch: fix/track-a-closure
Base commit: fd3ac95f3f2ecc0ae3df9746d329802f656d1432
Freeze manifest: src/evaluation/datasets/track_a_closure_v2.manifest.json
Verification command:
  venv/bin/python -m src.evaluation.run_track_a_closure \
    --verify-r0-freeze --require-clean-worktree
```

Freeze manifest และ Tests บังคับตรวจ Historical artifacts จาก Git object ของ
Base commit โดยตรง การแก้ย้อนหลัง, Hash mismatch, Path traversal, Duplicate
JSON key, Branch ผิด หรือ Dirty worktree จะทำให้ Verification ล้มเหลวแบบ
Fail closed

---

# Part B — Workstream R1: Close Step 1 Mini Baseline

## 8. R1 Objective

สร้าง Baseline ที่ตอบได้ว่า “Hybrid Retrieval ก่อน Track A ทำได้เท่าใด” บน Dataset 40 cases และ Corpus เดียวกับระบบปัจจุบัน

## 8.1 R1-01: Reconstruct Pre-Upgrade Runtime

ใช้ Detached Worktree หรือ Temporary Clone ที่ commit:

```text
5e8537b
```

เหตุผล:

- เป็นจุดหลังสร้าง Dataset/Baseline framework
- ยังไม่มี Thai Tokenization, Candidate Expansion, Reranker และ Context Builder จาก Step 2
- ใช้ Corpus และ Dataset version เดียวกับ Track A

Execution requirements:

- ใช้ Virtual Environment แยกจาก Current branch
- ติดตั้ง Dependency ตาม `requirements.txt` ที่ commit นั้น
- ใช้ API/Model configuration ที่บันทึกไว้ใน Baseline manifest
- ห้ามแก้โค้ด Legacy worktree เพื่อทำให้ผลดีขึ้น
- ถ้าต้องเพิ่ม Runner wrapper ให้เพิ่มใน Current branch และ Treat legacy process เป็น Black-box command

## 8.2 R1-02: Run Three-mode Comparative Baseline

Modes:

```text
keyword
semantic
hybrid
```

Official Baseline ต้องมี:

- Hit@K
- Recall@K
- MRR
- Not-found discipline
- False-positive rate
- p50/p95 latency
- Per-category metrics
- Per-case retrieved titles
- Provider failure count
- Fallback count

Run validity:

- Embedding provider failure > 0 → Invalid run
- Unexpected fallback > 0 → Invalid run
- Dataset/corpus hash mismatch → Invalid run
- Dirty worktree → Invalid run

## 8.3 R1-03: Add Same-TOP_K Controlled Comparison

เพราะ Pre-Track-A default ใช้ `TOP_K=4` แต่ Selected Profile ใช้ `TOP_K=6` ต้องมีสองมุม:

### Comparison A — Operational Default

```text
Pre-Track-A default configuration
vs
Post-Track-A selected configuration
```

ใช้ตอบคำถามทาง Product/Business ว่าระบบที่ Deploy จริงดีขึ้นหรือไม่

### Comparison B — Controlled TOP_K

```text
Pre-Track-A Hybrid at TOP_K=6
vs
Post-Track-A Hybrid at TOP_K=6
```

ใช้แยกผลของ Quality Upgrade ออกจากผลของการเพิ่มจำนวน Context

หาก Manifest เดิมไม่อนุญาต Config override ให้สร้าง Versioned closure manifest ใหม่ ห้ามแก้ Manifest เดิม

## 8.4 R1-04: Add Provenance Sidecar

Artifact ต้องบันทึก:

```json
{
  "source_commit": "5e8537b...",
  "working_tree_clean": true,
  "dataset_sha256": "...",
  "corpus_sha256": "...",
  "requirements_sha256": "...",
  "python_version": "...",
  "commands": ["..."],
  "fallback_count": 0
}
```

## 8.5 R1 Required Tests

- Baseline loader rejects wrong schema
- Baseline loader rejects wrong dataset hash
- Baseline loader rejects wrong corpus hash
- Baseline loader rejects missing `hybrid` evidence
- Baseline loader rejects provider fallback
- Controlled comparison rejects different `TOP_K`
- Operational comparison permits config differenceแต่ต้องรายงาน Delta
- Artifact excludes raw API key, environment dump และ document body

## 8.6 R1 Deliverables

- `track_a_pre_upgrade_baseline_v2.json`
- `track_a_pre_upgrade_baseline_v2.md`
- Baseline provenance sidecar หรือ embedded provenance
- Unit tests สำหรับ Artifact validation
- README link ไป Artifact ใหม่

## 8.7 R1 Exit Criteria

- [ ] Pre-Track-A Keyword/Semantic/Hybrid baseline มีครบ
- [ ] Dataset/corpus hash ตรงกับ Post-Track-A
- [ ] มี Same-TOP_K comparison
- [ ] Provider/Reranker fallback = 0
- [ ] Artifact ระบุ Commit SHA และ Config ครบ
- [ ] Baseline รันซ้ำได้จากคำสั่งเดียว

---

# Part C — Workstream R2: Close Step 2 Quality & Safety Gaps

## 9. R2 Objective

ทำให้ Quality Upgrade ไม่เพียงทำงานใน Normal Path แต่ยัง Fail Safe เมื่อ Model โหลดไม่ได้, Timeout, Busy, Memory ไม่พอ หรือ Inference คืนค่าผิดปกติ

## 9.1 R2-01: Separate Answerability Policy from Reranker Success

ปัจจุบัน Reranker score threshold ใช้ได้เฉพาะเมื่อ Reranker สำเร็จ หากเกิด Exception ระบบคืน Fusion order โดยไม่ผ่าน Answerability Gate

เพิ่ม Failure policy ที่ Configurable:

```text
RERANKER_FAILURE_POLICY=fail_closed
```

Allowed values:

| Policy | Behavior | การใช้งาน |
|---|---|---|
| `fail_closed` | คืน `[]` เมื่อ Primary/Secondary Reranker ใช้งานไม่ได้ | Production-safe default |
| `conservative` | ใช้ Independent deterministic gate ก่อนคืน Fusion order | เปิดเมื่อมี Evaluation รองรับ |
| `fusion_order` | คืน Fusion order เดิม | Lab/debug เท่านั้น |

Recommended initial default:

```text
fail_closed
```

เพราะผล Reranker-off ปัจจุบันมี Not-found discipline 0% และยังไม่มี Independent deterministic gate ที่พิสูจน์แล้ว

### Required behavior

```text
Primary succeeds
→ use reranker threshold

Primary fails, Secondary succeeds
→ use secondary reranker threshold

Both fail, failure policy = fail_closed
→ return []
→ generator returns deterministic not-found
```

## 9.2 R2-02: Implement Secondary Reranker

เพิ่ม Configuration:

```text
RERANKER_FALLBACK_ENABLED=true
RERANKER_FALLBACK_MODEL=BAAI/bge-reranker-base
RERANKER_FALLBACK_MODEL_REVISION=<approved-immutable-revision>
RERANKER_FALLBACK_CACHE_DIR=.cache/reranker-fallback
RERANKER_FALLBACK_MAX_LENGTH=512
```

ก่อน Implement ต้อง:

- ตรวจ Model card และ License
- Pin immutable revision
- ตรวจ Output-score semantics
- วัด RAM และ Latency บน Apple M4/16 GB
- ยืนยันว่าไม่ใช้ `trust_remote_code=True`

Implementation option:

```python
class CascadingReranker:
    def rerank(...):
        try:
            return primary.rerank(...)
        except Exception:
            return fallback.rerank(...)
```

ต้องไม่ Log Query, Candidate body หรือ Model exception ที่มี Sensitive content

## 9.3 R2-03: Add Failure Reason and Model-used Metadata

เพิ่ม Metrics/Properties โดยไม่ทำลาย `Retriever` protocol:

- `primary_reranker_failure_count`
- `secondary_reranker_usage_count`
- `secondary_reranker_failure_count`
- `fail_closed_count`
- `fusion_fallback_count`
- `active_reranker_model`
- `last_fallback_reason_code`

Reason codes:

```text
MODEL_LOAD_FAILED
MODEL_NOT_CACHED
INFERENCE_TIMEOUT
WORKER_BUSY
INVALID_SCORE_ARRAY
OUT_OF_MEMORY
UNKNOWN_RERANKER_ERROR
```

ห้ามส่ง Raw exception detail กลับ End User

## 9.4 R2-04: Add Thai Retrieval Integration Fixture

Unit tests ปัจจุบันยืนยันว่า Thai token > 0 แต่ยังไม่ยืนยัน Ranking บน Thai corpus

เพิ่ม Test fixture ขนาดเล็ก:

```text
[นโยบายการทำงานจากบ้าน]
พนักงานสามารถทำงานจากบ้านได้...
```

Tests:

- Thai query ค้น Thai chunk ได้
- Mixed Thai-English query ค้นได้
- Thai tokenizer disabled → behavior ถูกกำหนดชัด
- English fixture ไม่ Regression
- Agent Thai-only query ยังคงใช้ English translation เมื่อ Production corpus เป็น English

Test fixture ต้องอยู่ใน Test เท่านั้น ไม่เปลี่ยน Production corpus

## 9.5 R2-05: Correct Citation Metric Semantics

เปลี่ยนชื่อใน Retrieval/Context evaluation:

```text
citation_validity
→ context_header_validity
```

เพิ่ม Schema version ใหม่ ห้ามเปลี่ยนความหมายของ Field เดิมโดยไม่เปลี่ยน Version

Metrics ใหม่:

- `context_header_validity`
- `context_budget_validity`
- `answer_citation_validity`
- `answer_citation_coverage`

Definitions:

```text
context_header_validity =
  ทุก snippet ขึ้นต้นด้วย [retrieved title]

answer_citation_validity =
  ทุก citation ใน Final Answer อยู่ใน Evidence Headers

answer_citation_coverage =
  สัดส่วน factual claims ที่มี citation อย่างน้อยหนึ่งรายการ
```

## 9.6 R2-06: Establish One Configuration Source of Truth

ทางเลือกที่แนะนำ:

```text
Runtime code default = keyword-safe
Official Track A profile = explicit named profile
```

เพิ่ม:

```text
RETRIEVAL_PROFILE=track_a_balanced_v1
```

Profile:

```json
{
  "search_mode": "hybrid",
  "candidate_k": 12,
  "top_k": 6,
  "hybrid_min_cosine": 0.20,
  "reranker_min_score": 0.01,
  "reranker_batch_size": 4,
  "reranker_timeout_seconds": 10,
  "max_context_chars": 6000,
  "reranker_failure_policy": "fail_closed"
}
```

หากไม่เพิ่ม Profile loader อย่างน้อยต้องแก้:

- `.env.example`
- `src/config.py`
- README Setup section
- Evaluation report configuration

ให้ระบุชัดว่า:

- Code fallback default คือ Keyword
- การ Copy `.env.example` เปิด Official Hybrid profile
- UI override มี Priority อย่างไร

## 9.7 R2 Required Tests

### Unit

- Primary success
- Primary load failure → Secondary success
- Primary timeout → Secondary success
- Primary + Secondary failure → Fail closed
- Busy worker → Secondary หรือ Fail closed ตาม Policy
- Invalid/non-finite score → Fallback
- Non-positive `top_k`
- Candidate bound
- Model revision pin passed to loader
- Raw exception/query/body ไม่อยู่ใน log payload

### Integration

- Primary model warmup
- Secondary model warmup
- Selected Profile real inference
- Context Builder ทำงานหลัง Secondary result
- Exact not-found เมื่อ Fail closed

### Contract

- Result count ≤ `top_k`
- Best-first ordering
- Provenance preserved
- Empty query returns `[]`
- Existing Retriever contract 1.0.0 ผ่านทั้งหมด

## 9.8 R2 Deliverables

- Safe Reranker failure policy
- Secondary Reranker adapter/config
- Failure telemetry
- Thai retrieval integration tests
- Corrected metric schema
- Authoritative Track A profile
- Updated README และ `.env.example`

## 9.9 R2 Exit Criteria

- [ ] Normal Primary Reranker path ผ่าน
- [ ] Secondary model path ผ่าน
- [ ] Both models fail แล้วระบบไม่ Error
- [ ] Failure path Not-found discipline ไม่ต่ำกว่า Accepted Threshold
- [ ] Thai corpus fixture retrieval ผ่าน
- [ ] Context/Header metrics แยกจาก Answer Citation metrics
- [ ] Configuration และ Documentation ตรงกัน
- [ ] Retriever contract tests ผ่านทั้งหมด

---

# Part D — Workstream R3: Close Step 3 Measure & Tune

## 10. R3 Objective

สร้างหลักฐานที่ยืนยันได้ทั้ง Retrieval Quality, Final Answer Quality, Latency, RAM และ Graceful Degradation แล้วใช้หลักฐานนั้นเลือก Official Profile

## 10.1 R3-01: Component Ablation Matrix

อย่างน้อยต้องมี Profiles:

| ID | Configuration | จุดประสงค์ |
|---|---|---|
| A0 | Pre-Track-A Hybrid | True historical baseline |
| A1 | Current Hybrid, Reranker off, Answerability off | Current-code structural baseline |
| A2 | Candidate Expansion only | วัดผล Candidate breadth |
| A3 | Candidate Expansion + Reranker, score gate off | วัด Ranking effect |
| A4 | A3 + Reranker score gate | วัด Answerability effect |
| A5 | A4 + Context Builder | Official full pipeline |
| A6 | A5 + Primary failure/Secondary model | Graceful degradation |
| A7 | A5 + Both rerankers fail/Fail closed | Safety failure mode |

ทุก Profile ต้องใช้:

- Dataset 40 cases เดียวกัน
- Corpus hash เดียวกัน
- `TOP_K=6` สำหรับ Controlled comparison
- Query embeddings เดียวกันหรือ Versioned score cache เดียวกัน
- Metric implementation version เดียวกัน

## 10.2 R3-02: Retrieval Metrics

Required:

- Hit@K
- Recall@K
- MRR
- Not-found discipline
- False-positive rate
- Thai recall
- Mixed-language recall
- Multi-section recall
- Average final hit count
- Context truncation rate
- Context header validity

Hard gates:

| Metric | Gate |
|---|---:|
| English recall | ไม่ต่ำกว่า Pre-Track-A |
| Mixed recall | ไม่ต่ำกว่า Pre-Track-A |
| Multi-section recall | ไม่ต่ำกว่า Pre-Track-A |
| Thai recall | สูงกว่า Pre-Track-A อย่างวัดได้ |
| Overall recall | ไม่ต่ำกว่า Pre-Track-A |
| MRR | ไม่ต่ำกว่า Pre-Track-A |
| Context header validity | 100% |
| Context budget validity | 100% |

## 10.3 R3-03: End-to-end Answer Evaluation

สร้าง Runner ใหม่หรือขยาย Existing answer evaluation ให้ใช้ `lean-quality-v1`

Pipeline ที่ต้องรัน:

```text
User query
→ Router
→ Retriever Agent / Translation
→ Retrieval + Reranker + Context Builder
→ Query Rewrite เมื่อจำเป็น
→ Report Generator
→ Final Answer Validators
```

### Deterministic metrics

- Route correctness สำหรับ KB queries
- Answerable case ไม่ควรตอบ Not-found เมื่อ Expected evidence ถูก retrieve
- Negative case ต้องตอบ Exact not-found sentence
- Citation title ทุกตัวต้องอยู่ใน Context Header
- Citation coverage ต่อ Factual sentence
- Output schema/encoding validity
- Thai answer มี Thai script และไม่เปลี่ยนเป็น English โดยไม่มีเหตุผล

### Model-based metrics

- Faithfulness
- Answer relevance
- Completeness
- Language appropriateness
- Specific-data discipline

### Human/Domain review

ตรวจอย่างน้อย:

- Thai answerable 5 cases
- Negative 5 cases
- Multi-section 3 cases
- Mixed-language 3 cases
- ทุก Case ที่ LLM judge ไม่ผ่าน

### Answer-level hard gates

| Metric | Target |
|---|---:|
| Answer citation validity | 100% |
| Negative exact not-found | ≥90% และไม่ต่ำกว่า Accepted Baseline |
| Faithfulness | ≥95% |
| Answer relevance | ≥4.0/5 |
| Thai language appropriateness | ≥90% |
| Unsupported high-risk factual claim | 0 |

ถ้า Negative exact not-found ได้ 80% เท่าเดิม ต้องไม่ประกาศ Safety Gate ผ่าน เว้นแต่มี Written Risk Acceptance จาก Product/Business Owner

## 10.4 R3-04: Performance and Memory Benchmark

วัดบน Apple M4/16 GB และบันทึก Environment

### Scenarios

1. Primary model cold start
2. Primary model warm inference
3. Secondary model cold start
4. Secondary model warm inference
5. Reranker disabled
6. Candidate 12
7. Candidate 30
8. Primary timeout → Secondary
9. Both fail → Fail closed
10. Concurrent requestsอย่างน้อย 2 requests เพื่อยืนยัน Busy policy

### Metrics

- Model download time แยกจาก model load time
- Model load time
- Query embedding p50/p95
- Local reranker p50/p95/p99
- Context build p50/p95
- Retrieval end-to-end p50/p95
- Peak RSS
- Steady-state RSS
- Fallback latency
- Timeout rate
- Secondary usage rate

### Initial performance guardrails

| Metric | Initial target |
|---|---:|
| Warm retrieval p95 | ≤3.0 s |
| Primary local reranker p95 | ≤2.0 s |
| Peak process RSS | ≤6 GB บนเครื่อง 16 GB |
| Unexpected fallback during healthy run | 0 |
| Failure-path unhandled exception | 0 |
| Fail-closed response after detected failure | ภายใน overall timeout |

หาก Target ไม่ผ่านให้เลือก Smaller model, ลด Candidate count หรือเปิด Primary model เฉพาะ Query ที่ต้อง Rerank

## 10.5 R3-05: Decision Gate

Decision Record ต้องตอบ:

1. Track A เพิ่ม Retrieval Quality จาก Pre-Track-A Hybrid เท่าใด
2. Component ใดสร้าง Improvement มากที่สุด
3. Reranker เพิ่ม Quality เทียบกับ Latency/RAM เท่าใด
4. Candidate 12 รักษาคุณภาพจาก Candidate 30 เท่าใด
5. Answerability Gate ลด False Positive เท่าใด และเสีย Recall เท่าใด
6. Final Answer Quality ดีขึ้นหรือไม่
7. Primary failure แล้วระบบรักษา Safety ได้หรือไม่
8. Secondary model คุ้มค่าหรือควร Fail closed
9. 80% Not-found discipline ได้รับการแก้หรือได้รับ Risk Acceptance หรือไม่
10. Official Runtime Profile คือค่าใด

Possible decisions:

```text
APPROVE
APPROVE_WITH_ACCEPTED_RISK
KEEP_RERANKER_OPTIONAL
USE_SMALL_MODEL_AS_DEFAULT
FAIL_CLOSED_UNTIL_CLASSIFIER_EXISTS
REJECT_AND_RETUNE
```

## 10.6 R3 Required Tests

- Ablation profiles deterministic จาก Prepared cache เดียวกัน
- Profile ID ครบทุก Config field
- Baseline and current hashes match
- No raw query/document body in published artifact
- LLM Evaluation requires explicit external-data approval flag
- Failed provider call ไม่ถูกบันทึกเป็น Quality result
- Citation validator rejects invented title
- Citation coverage detects uncited factual sentence
- Negative validator requires exact not-found
- Performance result records warm/cold state
- RAM units normalized across macOS/Linux

## 10.7 R3 Deliverables

- `track_a_ablation_results_v2.json/.md`
- `track_a_answer_results_v2.json/.md`
- `track_a_performance_results_v2.json/.md`
- `docs/TRACK_A_DECISION_RECORD.md`
- Updated Selected Profile
- Updated README metrics

## 10.8 R3 Exit Criteria

- [ ] Before/After ใช้ Pre-Track-A Hybrid baseline
- [ ] Same-TOP_K controlled comparison มีครบ
- [ ] Component Ablation มีครบ
- [ ] Final-answer evaluation รันกับ Selected Profile
- [ ] Final-answer citation validity = 100%
- [ ] Negative discipline ≥90% หรือมี Accepted Risk
- [ ] Reranker ON/OFF latency มีครบ
- [ ] Peak RAM และ Cold-start time ถูกบันทึก
- [ ] Failure paths ผ่าน
- [ ] Decision Record ได้รับการอนุมัติ

---

# Part E — Workstream R4: Closure & Enterprise Re-baseline

## 11. R4 Objective

รวมหลักฐานทั้งหมดและสร้างจุดอ้างอิงใหม่สำหรับ Enterprise Track โดยไม่ทำลาย Historical Phase 0

## 11.1 R4-01: Produce Track A Closure Report

สร้าง `track_a_closure_report_v2.md` ประกอบด้วย:

- Executive summary
- Scope และ Environment
- Pre/Post Architecture delta
- Pre-Track-A vs Post-Track-A metrics
- Component Ablation
- Answer-level results
- Performance/RAM
- Failure behavior
- Risk acceptance
- Selected Profile
- Known limitations
- Final decision

## 11.2 R4-02: Update Parent Plan Status

อัปเดต `ENTERPRISE_AGENTIC_RAG_IMPLEMENTATION_PLAN.md` เฉพาะหลัง Closure ผ่าน:

- Track A status
- Completion date
- Selected Profile
- Link ไป Closure Report
- Accepted risks
- Remaining backlog

ห้ามแก้ตัวเลข Historical ให้เหมือนผลใหม่ ให้เพิ่ม Versioned result แทน

## 11.3 R4-03: Re-baseline Enterprise Phase 0

เพราะ Remediation เปลี่ยน Source tree, Tests, Configuration และอาจเปลี่ยน Model fallback:

- เก็บ `enterprise-phase0-v1` เป็น Historical artifact
- สร้าง `enterprise-phase0-v2`
- ใช้ Dataset/Corpus เดิม
- บันทึก Retriever contract version
- รัน Keyword/Semantic/Hybrid
- รัน Unit/Regression/Contract gates
- บันทึก Runtime health และ Fallback counters

Enterprise Phase 1 ห้ามเริ่มจาก Phase 0 v1 หาก Source tree หลัง Remediation ไม่ตรงกับ v1 manifest

## 11.4 R4 Exit Criteria

- [ ] Track A Closure Report พร้อม
- [ ] Decision = APPROVE หรือ APPROVE_WITH_ACCEPTED_RISK
- [ ] Parent plan อัปเดตสถานะ
- [ ] README อ้างเฉพาะตัวเลขที่ Trace กลับ Artifact ได้
- [ ] Enterprise Phase 0 v2 สร้างสำเร็จ
- [ ] Historical v1 artifacts ไม่ถูกเขียนทับ
- [ ] Working tree สะอาดและ Commit scope ชัดเจน

---

## 12. File Impact Plan

### 12.1 New Files

```text
TRACK_A_CLOSURE_REMEDIATION_PLAN.md
docs/TRACK_A_DECISION_RECORD.md
src/evaluation/run_track_a_closure.py
src/evaluation/run_track_a_answer_eval.py
src/evaluation/run_track_a_performance.py
src/evaluation/datasets/track_a_closure_v2.manifest.json
src/evaluation/configs/track_a_balanced_v1.json
tests/test_track_a_closure.py
tests/test_track_a_answer_eval.py
tests/test_track_a_performance.py
track_a_pre_upgrade_baseline_v2.json
track_a_pre_upgrade_baseline_v2.md
track_a_ablation_results_v2.json
track_a_ablation_results_v2.md
track_a_answer_results_v2.json
track_a_answer_results_v2.md
track_a_performance_results_v2.json
track_a_performance_results_v2.md
track_a_closure_report_v2.md
```

ชื่อ Runner สามารถรวมกันได้หากไม่ทำให้ External-data boundaries และ Result schemas ปนกัน

### 12.2 Modified Files

```text
.env.example
README.md
requirements-dev.txt
src/config.py
src/retrievers/reranker.py
src/retrievers/factory.py
src/evaluation/run_measure_tune.py
tests/test_reranker.py
ENTERPRISE_AGENTIC_RAG_IMPLEMENTATION_PLAN.md  # แก้เฉพาะตอน Closure ผ่าน
```

### 12.3 Files That Must Remain Immutable

```text
baseline_results.json
baseline_results.md
track_a_step3_results.json
track_a_step3_results.md
phase0_baseline_results.json
phase0_baseline_results.md
src/evaluation/datasets/lean_quality_v1.json
src/evaluation/datasets/lean_quality_v1.manifest.json
```

หาก Label ผิดจริง ให้ Version Dataset ใหม่ ห้ามแก้ Dataset v1 ย้อนหลัง

---

## 13. Testing and Execution Matrix

| Layer | Network/API | Local model | Frequency | Blocking |
|---|---|---|---|---|
| Unit tests | No | Mock | ทุก commit | Yes |
| Retriever contract | No | Mock | ทุก commit | Yes |
| Keyword regression | No | No | ทุก commit | Yes |
| Artifact/schema tests | No | No | ทุก commit | Yes |
| Real reranker integration | No หลัง cache พร้อม | Yes | ก่อน merge/release | Yes |
| Retrieval evaluation | Query embeddings only | Yes | Decision run | Yes |
| End-to-end answer evaluation | LLM + Embeddings | Yes | Decision run | Yes |
| Performance/RAM | Embeddings อาจใช้ cache/query API | Yes | Selected profiles | Yes |
| Human review | No เพิ่มเติม | N/A | Final decision | Yes |

Official execution order:

```text
1. Static/config validation
2. Unit tests
3. Retriever contract tests
4. Keyword regression
5. Real local reranker integration
6. Pre-Track-A comparative baseline
7. Component ablation
8. End-to-end answer evaluation
9. Performance/RAM benchmark
10. Human review
11. Decision record
12. Enterprise Phase 0 v2
```

ห้ามเริ่ม Paid/External Evaluation ก่อน Local gates ผ่าน

---

## 14. Initial Quality Gates

| Dimension | Blocking Gate |
|---|---:|
| Unit/contract/regression tests | 100% pass |
| Provider failure in official run | 0 |
| Unexpected reranker fallback in healthy run | 0 |
| Retrieval recall | ไม่ต่ำกว่า Pre-Track-A Hybrid |
| Thai recall | สูงกว่า Pre-Track-A |
| English/mixed/multi-section recall | ไม่ Regression |
| Context header validity | 100% |
| Context budget validity | 100% |
| Final-answer citation validity | 100% |
| Final-answer negative discipline | ≥90% หรือมี Accepted Risk |
| Faithfulness | ≥95% |
| Answer relevance | ≥4.0/5 |
| Unsupported high-risk factual claim | 0 |
| Failure-path unhandled exception | 0 |
| Warm retrieval p95 | ≤3.0 s initial target |
| Peak RSS on 16 GB dev machine | ≤6 GB initial target |

Target สามารถปรับได้จาก Evidence แต่การปรับต้องอยู่ใน Decision Record ห้ามลด Threshold เงียบ ๆ เพื่อให้ผลผ่าน

---

## 15. Risk Register

| ID | Risk | Impact | Mitigation |
|---|---|---:|---|
| TA-R01 | Legacy environment สร้างซ้ำไม่ได้ | High | Detached worktree, pinned requirements, provenance sidecar |
| TA-R02 | เปรียบเทียบต่าง TOP_K แล้วสรุปผิด | High | แยก Operational vs Controlled comparison |
| TA-R03 | Embedding API drift | Medium | บันทึก model/date/cache; ใช้ query score cache เดียวสำหรับ Ablation |
| TA-R04 | Reranker failure ลด Safety | High | Secondary model + fail-closed default |
| TA-R05 | Secondary model ใช้ Score scale ต่าง | High | แยก threshold และ tune ต่อ model |
| TA-R06 | LLM judge bias | Medium | Deterministic gates + Human review |
| TA-R07 | Negative dataset มีเพียง 10 cases | High | ใช้เป็น closure gate และเพิ่ม hard-negative backlog |
| TA-R08 | Citation coverage parser ตีความ Markdown ผิด | Medium | จำกัด output formatและเพิ่ม parser tests |
| TA-R09 | Performance result ปน cold/warm | Medium | แยก scenario และบันทึก cache state |
| TA-R10 | RAM units ต่างระหว่าง OS | Medium | Normalize ด้วย psutil หรือ platform-aware converter |
| TA-R11 | Phase 0 v1 ถูกใช้ต่อหลัง Source เปลี่ยน | High | ออก Phase 0 v2 ก่อน Phase 1 |
| TA-R12 | README มีตัวเลขไม่มี Artifact รองรับ | Medium | Traceability check ใน Documentation review |

---

## 16. Roles and Review

| Role | Responsibility |
|---|---|
| AI Solution Engineer | Architecture, trade-off, final closure decision |
| AI Engineer | Retrieval/Reranker/Answerability implementation |
| Evaluation Owner | Dataset, metrics, runner, evidence integrity |
| Domain Reviewer | Thai/negative/multi-section human review |
| Security Reviewer | Data boundary, logs, fallback behavior |
| Product/Business Owner | Acceptable not-found/latency trade-off และ Risk Acceptance |

สำหรับทีมคนเดียว ให้บันทึก Role ที่ใช้ตัดสินแต่ละ Gate ใน Decision Record เพื่อแยก Engineering evidence ออกจาก Business acceptance

---

## 17. Recommended Sprint Breakdown

### Sprint 1 — Evidence and Safety

Goal:

> สร้าง True Pre-Track-A Hybrid baseline และแก้ Reranker failure ให้ Fail Safe

Backlog:

1. R0 Freeze
2. R1 Pre-upgrade baseline
3. R1 Same-TOP_K comparison
4. R2 Failure policy
5. R2 Secondary reranker
6. R2 Failure-path tests
7. R2 Metric rename/schema version

Sprint Exit Demo:

```text
1. แสดง Pre-Track-A Hybrid artifact พร้อม source commit
2. แสดง Primary reranker success
3. Inject Primary failure → Secondary works
4. Inject both failures → deterministic not-found
5. Contract tests pass
6. Historical artifacts unchanged
```

### Sprint 2 — Answer Quality and Closure

Goal:

> ยืนยัน Final Answer Quality, Performance และตัดสิน Official Track A Profile

Backlog:

1. Component Ablation
2. End-to-end 40-case answer evaluation
3. Citation validity/coverage
4. Performance/RAM benchmark
5. Human review
6. Decision Record
7. Closure Report
8. Enterprise Phase 0 v2

Sprint Exit Demo:

```text
1. Pre/Post Hybrid comparison
2. Thai query final answer
3. Negative query exact not-found
4. Citation validator catches invented citation
5. Reranker ON/OFF quality-latency-RAM table
6. Decision Record
7. Phase 0 v2 baseline
```

---

## 18. Definition of Done

Track A จะถือว่าเสร็จสมบูรณ์เมื่อ:

1. มี Pre-Track-A Hybrid baseline บน Dataset 40 cases
2. Before/After มี Same-TOP_K controlled comparison
3. Component Ablation แยกผลของ Candidate Expansion, Reranker, Gate และ Context Builder
4. Thai retrieval และ Agent translation มี Test/Evaluation ครบ
5. Primary Reranker มี Secondary fallback หรือมี Decision ว่า Fail closed
6. Both-reranker failure ไม่ทำให้ระบบ Error หรือส่ง Weak evidence แบบเงียบ ๆ
7. Final-answer evaluation รันบน Selected Profile
8. Final-answer citation validity เท่ากับ 100%
9. Negative discipline ถึง 90% หรือมี Written Risk Acceptance
10. Faithfulness และ Relevance ผ่าน Threshold
11. Latency, Cold start และ Peak RAM ถูกวัด
12. Config/README/Artifact ระบุ Official Profile ตรงกัน
13. Decision Record ได้รับ Approval
14. Closure Report ถูก Version control
15. Enterprise Phase 0 v2 ถูกสร้างจาก Source หลัง Remediation
16. Historical artifacts ไม่ถูกแก้ย้อนหลัง

Final status format:

```text
Track A Status: APPROVED | APPROVED_WITH_ACCEPTED_RISK | NOT_APPROVED
Selected Profile: <profile-name/version>
Evidence Bundle: <artifact paths + SHA-256>
Accepted Risks: <IDs or none>
Next Track: Enterprise Phase 1 or additional Track A remediation
```

---

## 19. Immediate Next Actions

ลำดับเริ่มงานที่แนะนำ:

1. สร้าง `fix/track-a-closure` จาก `fd3ac95`
2. Freeze Dataset/Corpus/Contract hashes
3. สร้าง Detached Worktree ที่ `5e8537b`
4. สร้าง Pre-Track-A comparative baseline โดยไม่เขียนทับ Artifact เดิม
5. Implement Reranker failure policy แบบ Fail closed
6. เพิ่ม Secondary Reranker และ Failure tests
7. Version Metric schema และแก้ชื่อ Context citation metric
8. สร้าง Ablation Runner
9. สร้าง End-to-end Answer Evaluation 40 cases
10. วัด Latency/RAM
11. ทำ Human review และ Decision Record
12. ออก Closure Report และ Enterprise Phase 0 v2

ห้ามประกาศ Track A ว่าเสร็จก่อน R1, R2, R3 และ R4 Exit Criteria ผ่านหรือมี Accepted Risk ที่ระบุผู้อนุมัติและเหตุผลครบถ้วน
