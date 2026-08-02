# Track A Approval, Merge & Release Plan

> แผนเปลี่ยนสถานะ Track A จาก `NOT_APPROVED` ไปสู่การอนุมัติ, Merge เข้า
> `main`, Tag เวอร์ชันที่รับรองแล้ว และลบ Remediation Branch อย่างปลอดภัย
> โดยรักษา Evidence Traceability, Fail-closed Governance และ Historical
> Artifact Immutability ตลอดกระบวนการ

---

## 1. Document Control

| รายการ | รายละเอียด |
|---|---|
| Document | Track A Approval, Merge & Release Plan |
| Version | 1.0 |
| Created | 2026-08-02 |
| Project | Agentic_RAG |
| Parent plan | `ENTERPRISE_AGENTIC_RAG_IMPLEMENTATION_PLAN.md` |
| Closure plan | `TRACK_A_CLOSURE_REMEDIATION_PLAN.md` |
| Current main | `fd3ac95f3f2ecc0ae3df9746d329802f656d1432` |
| Current remediation branch | `fix/track-a-closure` |
| Current remediation HEAD | `3d816045c989e0fc0a78d6eebc9de4c2910360e5` |
| Current R3 decision | `REJECT_AND_RETUNE` |
| Current R4 status | `NOT_APPROVED` |
| Current profile | `track_a_balanced_v1` — measured candidate only |
| Current Phase 0 checkpoint | `enterprise-phase0-v2` |
| Execution constraint | เอกสารนี้เป็นแผนเท่านั้น ไม่สร้าง PR, ไม่รัน Evaluation, ไม่ Merge, ไม่ Tag และไม่ลบ Branch |

---

## 2. Executive Context

การทำ R0–R4 ครบในเชิงกิจกรรมไม่ได้แปลว่า Track A ผ่าน Closure โดยอัตโนมัติ
เพราะ R4 เป็น Decision Gate ที่ต้องสรุปจากหลักฐานทั้งหมด ปัจจุบัน Retrieval,
Runtime Safety และ Enterprise Phase 0 v2 ผ่าน แต่ Answer Quality,
Performance และ Approval Gates ยังไม่ผ่าน ดังนั้น Branch
`fix/track-a-closure` สามารถเปิดเป็น Draft Pull Request เพื่อรับ Review ได้
แต่ยังห้าม Merge, Tag ว่า Approved หรือลบ Branch

กระบวนการจากจุดนี้ต้องปิดสามมิติพร้อมกัน:

```text
Technical correctness
+ Business/Domain acceptance
+ Reproducible release evidence
= Merge and release authorization
```

เป้าหมายสุดท้ายไม่ใช่เพียงทำให้ Test ผ่าน แต่ต้องสร้างเส้นทาง Audit ที่ตอบได้ว่า:

1. แก้ Blocker ใด ด้วย Source Change ใด
2. ผลหลังแก้ดีขึ้นบน Dataset/Corpus เดิมหรือไม่
3. มี Regression หรือ Graceful-degradation trade-off ใหม่หรือไม่
4. ใคร Review และใครยอมรับ Business Risk
5. Commit ใดถูก Merge และ Tag ใดชี้ไปยัง Source ที่อนุมัติจริง
6. หาก Post-merge Verification ล้ม จะย้อนกลับอย่างไรโดยไม่ทำลายประวัติ

---

## 3. Current Baseline and Blocking Findings

### 3.1 Branch Topology

```text
main @ fd3ac95
    └── fix/track-a-closure @ 3d81604
          ├── R0 Freeze
          ├── R1 Comparative Evidence
          ├── R2 Runtime Safety
          ├── R3 Evaluation
          └── R4 NOT_APPROVED checkpoint
```

`origin/main` เป็น Ancestor ของ `origin/fix/track-a-closure` ณ วันที่สร้างแผน
แต่ต้องตรวจซ้ำก่อน Official R3 Run และก่อน Merge เพราะ `main` อาจเปลี่ยนได้

### 3.2 Gates ที่ผ่านแล้ว

- R0 historical evidence immutability
- R1 apples-to-apples comparison ที่ `TOP_K=6`
- R3 Retrieval Quality สำหรับ A5
- Context header validity 100%
- Context budget validity 100%
- Primary timeout → Secondary โดยไม่มี Unhandled Exception
- Primary + Secondary failure → deterministic fail closed
- Enterprise Phase 0 v2 Keyword/Semantic/Hybrid checkpoint
- Unit, Regression และ Retriever Contract tests ณ Source ปัจจุบัน

### 3.3 Blocking Gates

| Dimension | Current | Required | Status |
|---|---:|---:|---|
| Answer citation validity | 100% | 100% | PASS |
| Answer citation coverage | 91.01% | 100% | **FAIL** |
| No not-found after expected evidence | 96.67% | 100% | **FAIL** |
| Unsupported high-risk claims | 1 | 0 | **FAIL** |
| Faithfulness | 99.25% | ≥95% | PASS |
| Answer relevance | 5.0/5 | ≥4.0/5 | PASS |
| Primary local reranker p95 | 4,203 ms | ≤2,000 ms | **FAIL** |
| Warm retrieval p95 | 4,727 ms | ≤3,000 ms | **FAIL** |
| Human/Domain review | Pending 20 cases | Approved | **FAIL** |
| Product/Business decision | Pending | Approved/Accepted Risk | **FAIL** |
| R3 recommendation | `REJECT_AND_RETUNE` | `APPROVE*` | **FAIL** |

Enterprise Phase 0 v2 วัด Hybrid p95 ได้ประมาณ 1,499 ms แต่ยังไม่ใช้แทน R3
Performance Gate โดยอัตโนมัติ เพราะ Scenario, Warm/Cold Methodology และ
Benchmark Contract ต่างกัน ต้องแก้หรืออธิบายความต่าง แล้วรัน R3 Performance
ใหม่ด้วย Versioned Methodology ก่อนเปลี่ยน Decision

---

## 4. Target End State

กระบวนการนี้เสร็จเมื่อสถานะเป็นหนึ่งในสองค่า:

```text
APPROVE
APPROVE_WITH_ACCEPTED_RISK
```

และต้องมีเงื่อนไขครบ:

- R3 Retrieval, Answer, Performance และ Failure-path gates ผ่าน
- Human/Domain review มีผู้ Review และผลชัดเจน
- Product/Business Owner อนุมัติ หรือออก Written Risk Acceptance
- R4 Closure Report รุ่นใหม่อ้าง Evidence Hash ครบ
- Parent Plan และ README อ้างเฉพาะ Versioned Artifact รุ่นที่อนุมัติ
- Approved source มี Enterprise Phase 0 checkpoint รุ่นใหม่
- Pull Request ผ่าน Final Review และ Branch Protection
- `main` หลัง Merge ผ่าน Post-merge Verification
- Annotated/Signed Tag ชี้ไปยัง Commit บน `main` ที่ตรวจแล้ว
- Remediation Branch ถูกลบหลัง Merge/Tag/Audit Verification เท่านั้น

---

## 5. Governance Principles

### 5.1 Evidence Before Approval

ห้ามเปลี่ยน Decision Record เป็น `APPROVE` ก่อนสร้างและตรวจ Artifact จาก
Source Commit เดียวกัน หาก Code เปลี่ยนหลัง Evaluation ต้องถือว่า Evidence
เดิมไม่รับรอง Code ใหม่

### 5.2 Never Overwrite Historical Evidence

ไฟล์ต่อไปนี้ต้องเป็น Read-only:

```text
track_a_pre_upgrade_baseline_v2.json/.md
track_a_ablation_results_v2.json/.md
track_a_answer_results_v2.json/.md
track_a_performance_results_v2.json/.md
track_a_closure_report_v2.md
docs/TRACK_A_DECISION_RECORD.md
phase0_baseline_results.json/.md
phase0_v2_baseline_results.json/.md
src/evaluation/datasets/enterprise_phase0_v1.manifest.json
src/evaluation/datasets/enterprise_phase0_v2.manifest.json
```

เหตุผลสำคัญคือ `track_a_closure_report_v2.md` บันทึก SHA-256 ของ Decision
Record และ R3/R4 Artifacts ปัจจุบัน การแก้ไฟล์เดิมจะทำลาย Evidence Bundle

### 5.3 New Evidence Must Be Versioned

ชื่อเป้าหมายที่แนะนำ:

```text
src/evaluation/configs/track_a_balanced_v2.json
track_a_ablation_results_v3.json/.md
track_a_answer_results_v3.json/.md
track_a_performance_results_v3.json/.md
docs/TRACK_A_DECISION_RECORD_V2.md
docs/TRACK_A_HUMAN_REVIEW_APPROVAL_V1.md
docs/TRACK_A_PRODUCT_APPROVAL_V1.md
docs/TRACK_A_RISK_ACCEPTANCE_V1.md          # สร้างเมื่อมี Accepted Risk เท่านั้น
track_a_closure_report_v3.md
src/evaluation/datasets/enterprise_phase0_v3.manifest.json
phase0_v3_baseline_results.json/.md
```

Runner ต้องรองรับ Versioned Output และ Refuse Overwrite ห้ามเปลี่ยน Constant
ให้เขียนทับ v2 เพื่อความสะดวก

### 5.4 Fail Closed on Missing Evidence

กรณีต่อไปนี้ต้องทำให้ Closure เป็น `NOT_APPROVED`:

- Artifact หาย, Hash ไม่ตรง หรือ JSON Schema ไม่ตรง
- Dataset/Corpus/Profile/`TOP_K` identity ต่างกัน
- Provider failure หรือ Unexpected fallback ใน Official healthy run
- Human/Product approval ไม่มีหลักฐานแบบ Versioned
- Branch/Commit ที่รัน Evaluation ไม่ตรงกับ Source ที่จะ Merge
- Working tree สกปรกระหว่าง Official Evaluation
- Threshold ถูกลดโดยไม่มี Decision/Risk Record

### 5.5 Safety Gates That Cannot Be Waived

ห้ามใช้ `APPROVE_WITH_ACCEPTED_RISK` เพื่อข้าม:

- Final-answer citation validity <100%
- มี Unsupported high-risk factual claim
- Provider failure ถูกบันทึกเป็น Quality result
- Failure-path unhandled exception >0
- Secret, raw credential หรือ prohibited content อยู่ใน Published Artifact
- Dataset/Corpus identity mismatch
- Historical artifact ถูกเขียนทับ

Risk Acceptance อาจพิจารณาได้เฉพาะข้อจำกัดที่มี Compensating Control เช่น
Latency เกิน Target เล็กน้อยแต่ยังอยู่ใน Timeout/SLA ที่ Business ยอมรับ หรือ
Secondary quality limitation เมื่อ Secondary ไม่ใช่ Default และ High-risk
intent ใช้ Fail-closed policy

---

## 6. End-to-end Delivery Flow

```text
M0  Open Draft PR and freeze review scope
 ↓
M1  Remediate Answer/Citation/Performance blockers
 ↓
M2  Rerun complete R3 evidence suite
 ↓
M3  Human/Domain + Product/Business approval
 ↓
M4  Regenerate versioned R4 closure evidence
 ↓
M5  Approve or approve with accepted risk
 ↓
M6  Update Parent Plan and release documentation
 ↓
M7  Final PR review and merge to main
 ↓
M8  Verify main and create approved tag
 ↓
M9  Delete remediation branch and preserve audit trail
```

---

# Part A — M0: Open Draft PR and Freeze Review Scope

## 7. M0 Objective

เปิดพื้นที่ Review โดยประกาศอย่างชัดเจนว่า Branch ยังไม่พร้อม Merge และ
กำหนด Scope/Blockers/Owners ก่อนเริ่มแก้ Code รอบใหม่

## 7.1 Pre-flight Checks

```bash
git status -sb
git branch --show-current
git remote -v
git fetch origin --prune
git merge-base --is-ancestor origin/main HEAD
git log --oneline origin/main..HEAD
gh auth status
gh pr list --head fix/track-a-closure --state all
```

Required:

- Current branch = `fix/track-a-closure`
- Working tree สะอาด
- Remote = `Sayomphon/Agentic-RAG-Assistant`
- ไม่มี Unpushed Commit
- หากมี PR อยู่แล้วให้ใช้ PR เดิม ห้ามเปิดซ้ำ
- หาก `origin/main` มี Commit ใหม่ ต้องทำ Base-drift Assessment ก่อน

## 7.2 Create Draft PR

ตัวอย่างคำสั่งเมื่อยังไม่มี PR:

```bash
gh pr create \
  --draft \
  --base main \
  --head fix/track-a-closure \
  --title "Track A closure remediation and approval evidence" \
  --body-file <reviewed-pr-body.md>
```

PR Body ต้องมี:

- Current status: `NOT_APPROVED`
- R3 decision: `REJECT_AND_RETUNE`
- รายการ R0–R4 changes
- Current passing gates
- Answer/Citation/Performance blockers
- External-data boundaries
- Test evidence
- Artifact links และ hashes
- Checklist ที่ห้าม Mark Ready ก่อน M5 ผ่าน

ข้อความที่ต้องปรากฏชัด:

```text
This Draft PR is open for review only.
It is not authorized for merge or production promotion.
```

## 7.3 Review Lanes

ขอ Review แยกตามมุม:

1. **AI/Code Review** — Agent flow, validators, bounded repair, performance
2. **Evaluation Review** — Dataset identity, metrics, ablation, no cherry-pick
3. **Security Review** — Data boundaries, logs, fail-closed behavior
4. **Domain Review** — Thai/mixed/negative/multi-section answers
5. **Product Review** — Accuracy/latency/not-found trade-offs

Draft Review สามารถเริ่มก่อนแก้ Blocker เพื่อให้ Root Cause และ Approach
ได้รับ Feedback แต่ห้าม Approve Final PR จาก Diff รุ่นนี้

## 7.4 Base-drift Policy

หาก `main` เปลี่ยน:

- Review diff ของ `origin/main..HEAD`
- Merge `origin/main` เข้า Remediation Branch แทนการ Rebase หลังมี Official
  Evidence เพื่อรักษา Commit Traceability
- แก้ Conflict แบบระบุไฟล์และเหตุผล
- รัน Local Gates ใหม่
- Official R3 Evidence ต้องสร้างหลัง Base-drift merge เสร็จแล้ว

ห้าม Force-push หลังเริ่ม Official Approval เว้นแต่มี Written Review
Agreement และต้อง invalidate approvals เดิม

## 7.5 M0 Deliverables

- Draft PR URL
- Reviewer/Owner list
- Blocker checklist
- Base-drift assessment
- Current evidence links

## 7.6 M0 Exit Criteria

- [ ] Draft PR เปิดแล้วหรือยืนยันว่าใช้ PR เดิม
- [ ] PR ระบุ `NOT_APPROVED`
- [ ] Review lanes มี Owner
- [ ] ไม่มีคำสั่ง Auto-merge
- [ ] Branch scope และ Base SHA ถูกบันทึก

---

# Part B — M1: Remediate Answer, Citation and Performance Blockers

## 8. M1 Objective

แก้ Root Cause โดยไม่ลด Safety Threshold และไม่ทำให้ Retrieval/Failure-path
ที่ผ่านแล้ว Regression

## 8.1 Workstream A — Citation Coverage Guardrail

เพิ่ม Post-generation pipeline:

```text
Generated Answer
→ Parse factual units
→ Validate citation title against available Context Headers
→ Measure factual-unit coverage
→ One bounded repair attempt
→ Re-validate
→ Pass or deterministic fail closed
```

Requirements:

- แยก Markdown structural label ออกจาก Factual sentence
- Citation title ต้องอยู่ใน Evidence Header เท่านั้น
- ห้ามแก้ Citation ด้วยการเลือก title ที่ไม่มี Claim support
- Repair Prompt รับเฉพาะ Answer + allowlisted Evidence Headers/Snippets
- Repair ได้ไม่เกินหนึ่งครั้ง
- หลัง Repair ยังไม่ผ่าน → deterministic not-found หรือ safe partial answer
  ตาม Policy ที่ได้รับอนุมัติ
- เก็บ stable reason code ไม่เก็บ Raw answer/query ใน Published Artifact

Suggested reason codes:

```text
UNCITED_FACTUAL_UNIT
UNKNOWN_CITATION_TITLE
UNSUPPORTED_CITATION
CITATION_REPAIR_FAILED
ANSWER_FAIL_CLOSED
```

Required tests:

- Valid fully cited answer passes
- Invented citation fails
- Factual sentence without citation is detected
- Heading/bullet label ไม่ถูกนับเป็น Factual claim
- Repair สำเร็จภายในหนึ่งครั้ง
- Repair ล้มแล้ว Fail closed
- Thai punctuation และ mixed-language sentence segmentation
- No raw content in logs/public artifact

## 8.2 Workstream B — Expected-evidence/Not-found Contradiction

Root cause investigation ต้องแยก:

- Evidence ถูก Retrieve แต่ถูก Context Builder ตัดทิ้งหรือไม่
- Generator ตอบ Not-found เพราะ Prompt/format ambiguity หรือไม่
- Multi-section query มี Evidence บางส่วนแต่ Policy บังคับ All-or-nothing หรือไม่
- Query rewrite หรือ Translation เปลี่ยน intent หรือไม่
- Validator ตีความ Not-found ผิดหรือไม่

ห้ามแก้ด้วย Rule ว่า “มี Context แล้วห้าม Not-found” เพราะ Context อาจเป็น
False Positive วิธีที่ปลอดภัยกว่าคือเพิ่ม Evidence Sufficiency Contract:

```text
expected/required evidence coverage
+ answerability score
+ available context titles
→ ANSWER | SAFE_PARTIAL | NOT_FOUND
```

Required tests:

- Expected evidence ครบ → ห้ามตอบ exact not-found
- Evidence บางส่วน → safe partial answer ระบุข้อจำกัดและ cite เฉพาะที่มี
- Context เป็น false positive → ยังตอบ not-found ได้
- Multi-section completeness ไม่ทำให้ Unsupported synthesis
- Bounded rewrite path ไม่เพิ่ม Loop

## 8.3 Workstream C — Unsupported High-risk Claim

สำหรับ Claim ที่เกี่ยวกับวงเงิน, Approval authority, Security, Personal data,
Healthcare หรือ Compliance:

- ตัวเลข/ชื่อ Role/Deadline ต้องมี Exact Evidence span
- ห้ามอนุมานจาก Policy ใกล้เคียง
- ห้ามรวมสอง Source แล้วสร้างเงื่อนไขใหม่ที่ไม่มี Source ใดยืนยัน
- เพิ่ม High-risk claim classifier แบบ deterministic ก่อนใช้ Model judge
- ถ้า Claim support ไม่ครบให้ตัด Claim หรือ Fail closed

Required tests:

- Supported exact value passes
- Numeric value ที่ Evidence ไม่มีถูก reject
- Role/approval chain ที่แต่งเพิ่มถูก reject
- Mixed Thai-English claim ตรวจได้
- Model judge failure ไม่ถูกใช้แทน deterministic block

## 8.4 Workstream D — Primary Reranker Performance

ทำ Profiling ก่อนเปลี่ยน Model:

```text
Query embedding
→ Candidate retrieval
→ Candidate text preparation/tokenization
→ Model inference
→ Score validation
→ Context build
```

ทดลองทีละตัวแปร:

1. จำกัด Candidate body length โดยไม่ตัด title/critical evidence
2. ลด `RERANKER_MAX_LENGTH` จาก Evidence
3. Batch-size tuning สำหรับ Apple M4/16 GB
4. Conditional reranking เฉพาะ Query ที่ Fusion confidence ไม่ชัด
5. Candidate 8/10/12 controlled experiment
6. Smaller multilingual model พร้อม model-specific threshold
7. Quantized/ONNX/CoreML path เมื่อ License/accuracy ผ่าน
8. Async model service เฉพาะเมื่อ Local synchronous optimization ไม่พอ

ทุก Experiment ต้องรายงาน:

- Quality delta เทียบ A5
- Thai/mixed/multi-section delta
- Not-found/false-positive delta
- Warm/cold p50/p95/p99
- Peak/steady RSS
- Timeout/fallback count
- Model revision, device, batch size, max length

ห้ามเลือก Fastest Profile หาก Safety/Quality Gate Regression

## 8.5 Workstream E — Secondary Model Policy

Secondary ปัจจุบันเร็วกว่าแต่ Multi-section recall Regression จึงต้อง:

- Tune threshold แยกจาก Primary
- ทดสอบ Candidate count และ text length แยก
- แยก High-risk/multi-section behavior
- หากยังไม่ผ่าน ให้คง Secondary เป็น Emergency path และ Fail closed สำหรับ
  Intent ที่ไม่รับ Quality degradation
- ห้ามประกาศ Secondary ว่า Quality-equivalent โดยไม่มี Evidence

## 8.6 Source and Configuration Versioning

หากค่า Profile เปลี่ยนให้สร้าง:

```text
src/evaluation/configs/track_a_balanced_v2.json
```

Profile ต้องมี:

- Full config fields
- Schema version
- Model/revision identities
- Failure policy
- Threshold แยก Primary/Secondary
- Performance policy
- Evidence artifact version ที่ใช้เลือก

## 8.7 Commit Strategy

แยก Commit ตาม Root Cause เพื่อ Review/Revert ได้:

```text
fix: enforce bounded answer citation repair
fix: prevent evidence and not-found contradictions
fix: reject unsupported high-risk claims
perf: reduce primary reranker latency
test: add Track A approval gate coverage
```

ห้ามรวม Generated R3 Evidence ไว้ใน Commit เดียวกับ Implementation หลายชุด
เพราะ Reviewer จะแยก Source Change กับ Measured Result ได้ยาก

## 8.8 Local Verification After Every Workstream

```bash
SEARCH_MODE=keyword venv/bin/python -m unittest discover -s tests -v
SEARCH_MODE=keyword venv/bin/python -m src.evaluation.regression
venv/bin/python -m unittest tests.test_retriever_contract -v
venv/bin/python -m compileall -q src tests
git diff --check
```

เพิ่ม Focused tests ตาม Workstream ก่อน Full suite ทุกครั้ง

## 8.9 M1 Exit Criteria

- [ ] Citation coverage validator + bounded repair มี Tests
- [ ] Expected-evidence/not-found contradiction ถูกแก้
- [ ] Unsupported high-risk deterministic gate ผ่าน
- [ ] Performance candidate ผ่าน Local profiling
- [ ] Secondary policy ถูกกำหนดชัด
- [ ] ไม่มี Threshold ลดแบบไม่มีหลักฐาน
- [ ] Full local gates ผ่าน
- [ ] Working tree สะอาดและ Commit scope แยกชัด

---

# Part C — M2: Rerun Complete R3 Evidence Suite

## 9. M2 Objective

สร้าง Evidence รุ่นใหม่จาก Final candidate source โดยใช้ Dataset/Corpus เดิม
และรันทุก Gate ไม่เลือกเฉพาะ Metric ที่ดีขึ้น

## 9.1 Prepare Versioned R3 Runner

Runner ปัจจุบันเขียน v2 จึงต้องเพิ่ม Versioned specification เช่น:

```text
TrackAR3EvidenceSpec
  schema versions
  profile path
  output JSON/Markdown paths
  metric version
  dataset/corpus identities
```

CLI เป้าหมาย:

```text
--evidence-version v3
--profile track_a_balanced_v2
```

Requirements:

- v2 compatibility tests ผ่าน
- Refuse overwrite ทุก Existing Artifact
- Duplicate JSON key/path traversal/size checks
- Published output ไม่มี Raw query/answer/snippet/body/prompt/secret

## 9.2 Official-run Preconditions

- Working tree สะอาด
- Branch SHA ถูกบันทึก
- `origin/main` Base drift ถูก resolve
- Dataset/Corpus hashes ตรง R0/R1
- Model cache/revisions ตรวจแล้ว
- External-data approvals แยก Query Embeddings กับ Answer/Snippets
- Local gates ผ่านก่อน Paid/External calls

## 9.3 Stage 1 — Component Ablation

Profiles ขั้นต่ำ:

```text
A0  True Pre-Track-A Hybrid baseline
A1  Current Hybrid, reranker/answerability off
A2  Candidate expansion only
A3  Candidate expansion + Primary reranker
A4  A3 + score gate
A5  A4 + Context Builder + final answer guardrails
A6  Primary failure → Secondary
A7  Both fail → fail closed
```

ใช้:

- 40 cases เดิม
- Corpus hash เดิม
- Controlled `TOP_K=6`
- Metric implementation version เดียว
- Prepared cache เดียว
- Final candidate profile รุ่นใหม่

Retrieval gates:

| Metric | Gate |
|---|---:|
| Overall Recall@6 | ไม่ต่ำกว่า A0 |
| MRR | ไม่ต่ำกว่า A0 |
| English recall | ไม่ต่ำกว่า A0 |
| Mixed recall | ไม่ต่ำกว่า A0 |
| Multi-section recall | ไม่ต่ำกว่า A0 |
| Thai recall | สูงกว่า A0 อย่างวัดได้ |
| Context header validity | 100% |
| Context budget validity | 100% |
| Healthy-run unexpected fallback | 0 |

## 9.4 Stage 2 — End-to-end Answer Evaluation

Pipeline ต้องเป็น Production-equivalent:

```text
User query
→ Router
→ Translation/Retriever Agent
→ Hybrid/Reranker/Context
→ Rewrite when required
→ Generator
→ Citation/High-risk Validators
→ Bounded repair
→ Final answer
```

Answer hard gates:

| Metric | Required |
|---|---:|
| Route correctness | 100% |
| Answer citation validity | 100% |
| Answer citation coverage | 100% |
| No not-found after expected evidence | 100% |
| Negative exact not-found | ≥90% และไม่ต่ำกว่า Accepted Baseline |
| Faithfulness | ≥95% |
| Answer relevance | ≥4.0/5 |
| Thai language appropriateness | ≥90% |
| Unsupported high-risk claim | 0 |
| Output schema/encoding validity | 100% |

หาก Citation parser เปลี่ยน Definition ต้อง:

- Version Metric schema
- Rerun v2 fixtures เพื่อแสดงผลกระทบของ Definition
- แยก Parser correction ออกจาก Model quality improvement
- ห้ามปรับ Definition เพื่อให้ตัวเลขผ่านโดยไม่มี Justification

## 9.5 Stage 3 — Performance and Memory

Scenarios ขั้นต่ำ:

1. Primary cold start
2. Primary warm inference
3. Secondary cold start
4. Secondary warm inference
5. Reranker disabled
6. Selected Candidate count
7. Stress Candidate count
8. Primary timeout → Secondary
9. Both fail → fail closed
10. Concurrent Busy policy
11. Conditional-rerank bypass path หาก Implement
12. Citation repair path และ repair-failure path

Performance gates:

| Metric | Required |
|---|---:|
| Warm retrieval p95 | ≤3,000 ms |
| Primary local reranker p95 | ≤2,000 ms |
| Peak RSS on 16 GB machine | ≤6,144 MiB |
| Unexpected healthy fallback | 0 |
| Failure-path unhandled exception | 0 |
| Fail-closed within overall timeout | 100% |
| Bounded repair attempts | ≤1 |

เพื่ออธิบายความต่างระหว่าง R3 v2 p95 4,727 ms กับ Phase 0 v2 p95 1,499 ms
ต้องบันทึก:

- Process/model warm state
- Iteration/sample count
- Query embedding cache state
- Candidate text/token lengths
- Concurrent background load
- Model/device configuration
- p95 calculation method

หาก Methodology เปลี่ยนให้รายงานทั้ง Old-compatible comparison และ New
operational measurement

## 9.6 Stage 4 — Evidence Integrity Validation

ตรวจ:

- Schemas/required fields
- Hash cross-reference
- Case counts/categories
- Metrics recompute จาก per-case results
- No provider/fallback contamination
- No raw data/secret leakage
- Artifact files owner/permission policy
- Working tree/commit identity

## 9.7 M2 Deliverables

- `track_a_ablation_results_v3.json/.md`
- `track_a_answer_results_v3.json/.md`
- `track_a_performance_results_v3.json/.md`
- Updated candidate profile v2
- Versioned R3 methodology/runner tests
- Sanitized Human-review bundle

## 9.8 M2 Exit Criteria

- [ ] Ablation A0–A7 ครบ
- [ ] Retrieval gates ผ่าน
- [ ] Answer hard gates ผ่าน
- [ ] Performance gates ผ่าน หรือมี Risk candidate ที่ Waive ได้
- [ ] Failure paths ผ่าน
- [ ] No raw/secret leakage
- [ ] Artifact hashes และ source commit ครบ
- [ ] R3 Recommendation พร้อมเข้าสู่ Human/Product Review

---

# Part D — M3: Human, Domain and Product/Business Approval

## 10. M3 Objective

แยก Technical Evidence ออกจาก Human judgment และ Business Risk Acceptance
โดยมีผู้รับผิดชอบและเหตุผลที่ Audit ได้

## 10.1 Human/Domain Review Scope

Review อย่างน้อย:

- Thai answerable 5 cases
- Negative 5 cases
- Multi-section 3 cases
- Mixed-language 3 cases
- ทุก Case ที่ Deterministic/Model judge ไม่ผ่าน
- Case เดิมที่มี unsupported high-risk claim
- Case เดิมที่ตอบ not-found ทั้งที่มี expected evidence
- ทุก Case ที่ใช้ Citation repair

ขั้นต่ำยังคง 20 cases ตาม R3 v2 และอาจมากกว่า 20 หากมี Failure ใหม่

## 10.2 Human-review Rubric

Reviewer ให้ Verdict ต่อ Case:

```text
PASS
PASS_WITH_NOTE
FAIL_UNSUPPORTED
FAIL_INCOMPLETE
FAIL_CITATION
FAIL_LANGUAGE
FAIL_NOT_FOUND_POLICY
NEEDS_DOMAIN_OWNER
```

ตรวจ:

- Correctness
- Faithfulness
- Completeness
- Citation support
- Thai/business terminology
- Specific-data discipline
- High-risk statement
- Safe not-found/partial-answer behavior

## 10.3 Human-review Artifact

Public/versioned summary เก็บ:

- Case ID
- Category
- Reviewer role
- Review date
- Verdict
- Stable reason code
- Required follow-up

ห้ามเก็บ Raw query/answer/snippet หาก Data classification ไม่อนุญาต
รายละเอียดเต็มให้อยู่ใน Owner-only ignored bundle

แนะนำ:

```text
docs/TRACK_A_HUMAN_REVIEW_APPROVAL_V1.md
```

Status ต้องเป็นหนึ่งใน:

```text
APPROVED
REJECTED
PENDING_REMEDIATION
```

## 10.4 Product/Business Decision

Product/Business Owner ต้องตอบ:

1. Accuracy/Safety เหมาะกับ Intended use หรือไม่
2. Not-found trade-off ยอมรับได้หรือไม่
3. Latency เหมาะกับ User workflow หรือไม่
4. Secondary/fail-closed experience ยอมรับได้หรือไม่
5. มี Operational limitation ที่ต้องสื่อสารหรือไม่
6. อนุมัติ Profile รุ่นใดและ Scope ใด

แนะนำ Artifact:

```text
docs/TRACK_A_PRODUCT_APPROVAL_V1.md
```

Fields:

- Decision
- Owner name/role
- Date
- Approved profile/version
- Evidence bundle hashes
- Intended environment
- Limitations
- Rollback triggers
- Risk acceptance reference หรือ `none`

## 10.5 Written Risk Acceptance

สร้างเฉพาะเมื่อ Decision เป็น `APPROVE_WITH_ACCEPTED_RISK`

Required fields:

- Risk ID
- Failed/waived target
- Current measurement
- Business impact
- Probability/severity
- Compensating controls
- Monitoring/rollback threshold
- Scope and expiry date
- Owner and approver
- Remediation backlog

Risk Acceptance ต้องมี Expiry ห้ามเป็นการยอมรับถาวรโดยไม่มี Review date

## 10.6 Separation of Duties

ขั้นต่ำ:

- AI Engineer ไม่เป็นผู้อนุมัติ Product Risk ของตนเอง
- Evaluation Owner ยืนยัน Evidence integrity
- Domain Reviewer ยืนยันความหมาย/ภาษา
- Product/Business Owner ยืนยัน trade-off

กรณีทีมคนเดียว ให้บันทึก Role hat และระบุว่า Approval ใดเป็น Engineering
recommendation ไม่ใช่ Independent business approval

## 10.7 M3 Exit Criteria

- [ ] Human Review ครบ required cases
- [ ] ทุก Automated failure มี Human verdict
- [ ] Domain status = APPROVED
- [ ] Product decision ถูกบันทึก
- [ ] Risk Acceptance ครบ fields หรือ `none`
- [ ] Evidence ไม่มี Raw/sensitive content เกินขอบเขต

---

# Part E — M4: Regenerate Versioned R4 Closure Evidence

## 11. M4 Objective

สร้าง Closure Report รุ่นใหม่จาก R3 v3 และ Approval Artifacts โดยไม่แก้
R4 v2 เดิม

## 11.1 Version the R4 Assessor

R4 assessor ปัจจุบันผูกกับ v2 paths/schema ให้ Refactor เป็น Specification:

```text
TrackAClosureSpec
  R1 baseline path
  R3 artifact paths/schemas
  profile identity
  human/product/risk approval paths
  phase0 checkpoint paths
  closure report path/schema
```

เพิ่ม CLI เป้าหมาย:

```text
--evidence-version v3
--report-version v3
```

ต้องมี Compatibility tests ที่ยังอ่าน/ตรวจ v2 ได้เหมือนเดิม

## 11.2 R4 Inputs

- R0 freeze manifest
- R1 comparative baseline v2
- R3 ablation v3
- R3 answer v3
- R3 performance v3
- Candidate profile v2
- Human-review approval
- Product approval
- Risk acceptance ถ้ามี
- Enterprise Phase 0 v3 checkpoint

## 11.3 Enterprise Phase 0 v3

เนื่องจาก M1 เปลี่ยน Source tree จึงห้ามใช้ Phase 0 v2 เป็น Final release
identity ต้องสร้าง v3:

```text
enterprise-phase0-v3
```

ก่อน Initialize:

- Code/tests/config final
- Working tree สะอาด
- Local gates ผ่าน
- Profile ที่เลือกตรง R3 Decision
- Primary/Secondary revisions immutable

จากนั้น:

1. Initialize versioned manifest
2. Review manifest fields/secrets
3. Commit manifest
4. รัน Keyword/Semantic/Hybrid จาก Clean worktree
5. Query embeddings ต้องมี Explicit approval
6. Corpus cache miss ต้อง Fail closed
7. Commit result artifacts
8. Strict verify manifest อีกครั้ง

## 11.4 Closure Decision Logic

`APPROVE` เมื่อทุก Gate ผ่านและไม่มี Accepted Risk

`APPROVE_WITH_ACCEPTED_RISK` เมื่อ:

- Non-waivable gates ผ่านทั้งหมด
- เฉพาะ Waivable gate ที่มี Written Risk Acceptance
- Compensating controls และ expiry ครบ
- Product/Business Owner อนุมัติ

นอกเหนือจากนี้:

```text
NOT_APPROVED
```

## 11.5 R4 Report Content

- Executive summary
- Source/Environment identity
- Pre/Post metrics
- Ablation/component effects
- Final Answer metrics
- Performance/RAM
- Failure behavior
- Human/Domain verdict
- Product decision
- Accepted risks
- Selected profile
- Phase 0 v3 result
- Evidence bundle paths + SHA-256
- Final status

## 11.6 M4 Deliverables

- `track_a_closure_report_v3.md`
- Machine-readable closure assessment หากเพิ่ม
- Enterprise Phase 0 v3 manifest/results
- R4 compatibility/security tests

## 11.7 M4 Exit Criteria

- [ ] v2 evidence ไม่ถูกแก้
- [ ] R3 v3 identities ตรงกัน
- [ ] Human/Product approvals ถูกตรวจ
- [ ] Phase 0 v3 ผ่าน
- [ ] Evidence bundle hashes ครบ
- [ ] Status ถูกคำนวณแบบ fail closed

---

# Part F — M5: Closure Authorization Decision

## 12. M5 Objective

ยืนยันว่าผล R4 ไม่ใช่เพียง Report ที่สร้างสำเร็จ แต่เป็น Authorization ที่
พร้อมใช้ควบคุม Merge

## 12.1 Decision Matrix

| Technical gates | Human/Product | Risk record | Decision |
|---|---|---|---|
| All pass | Approved | None | `APPROVE` |
| Non-waivable pass, waivable miss | Approved | Complete | `APPROVE_WITH_ACCEPTED_RISK` |
| Safety gate fails | Any | Any | `NOT_APPROVED` |
| Approval pending | Pending | Any | `NOT_APPROVED` |
| Evidence/hash mismatch | Any | Any | `NOT_APPROVED` |

## 12.2 Decision Record v2

สร้างใหม่:

```text
docs/TRACK_A_DECISION_RECORD_V2.md
```

ต้องตอบ Decision questions เดิมและเพิ่ม:

- Blocker เดิมแก้ด้วยอะไร
- R3 v2 → v3 delta
- Phase 0 v2 → v3 delta
- Performance discrepancy อธิบายแล้วหรือไม่
- Human/Product approvals อยู่ที่ใด
- Merge authorization granted หรือไม่
- Tag candidate คืออะไร

Required status:

```text
Recommendation: APPROVE | APPROVE_WITH_ACCEPTED_RISK | REJECT_AND_RETUNE
Technical evidence status: complete
Automated closure gate: passed
Human/Domain review: APPROVED
Product/Business decision: APPROVED
R4 closure authorization: granted
```

## 12.3 M5 Exit Criteria

- [ ] R4 status เป็น `APPROVE*`
- [ ] Decision Record v2 สอดคล้อง R4
- [ ] Non-waivable gates ผ่าน
- [ ] Approval artifacts มี hash/reference
- [ ] Merge authorization = granted

หากไม่ผ่าน ให้กลับ M1/M2 ห้ามข้ามไป M6

---

# Part G — M6: Update Parent Plan and Release Documentation

## 13. M6 Objective

เปลี่ยนเอกสารโครงการให้ชี้ไปยัง Approved Evidence โดยไม่แก้ตัวเลข Historical

## 13.1 Update Parent Plan

แก้ `ENTERPRISE_AGENTIC_RAG_IMPLEMENTATION_PLAN.md` เฉพาะเมื่อ M5 ผ่าน:

- Track A status
- Completion date
- Approved profile/version
- Closure report link
- Decision record link
- Accepted Risk IDs หรือ `none`
- Enterprise Phase 0 v3 link
- Remaining backlog
- Next Track authorization

ห้าม:

- เปลี่ยน Historical v1/v2 metrics ให้เหมือน v3
- ลบ Record ว่า R3 v2 เคย `REJECT_AND_RETUNE`
- เขียนว่า Enterprise Phase 1 เริ่มแล้วหาก Trigger Conditions ยังไม่เกิด

## 13.2 Update README

- Current approved profile
- Approved metrics จาก Artifact รุ่นใหม่
- Reproduction commands
- Data-boundary flags
- Known limitations
- Links ไป R3/R4/Phase 0 v3
- Historical v1/v2 sections ยังคงชัดเจน

## 13.3 Release Notes Draft

เตรียม:

- What changed
- Why
- Quality/Safety improvements
- Performance result
- Breaking/config changes
- Upgrade instructions
- Known limitations
- Rollback instructions
- Evidence/approval links

## 13.4 Traceability Check

ทุกตัวเลขใน Parent Plan/README/Release Notes ต้อง Trace ไป JSON/Markdown
Artifact พร้อม Version ห้าม Copy ตัวเลขจาก Console output เพียงอย่างเดียว

## 13.5 M6 Exit Criteria

- [ ] Parent Plan status อัปเดตหลัง Approval
- [ ] README ชี้ Approved profile
- [ ] Historical metrics ไม่ถูกเขียนทับ
- [ ] Release notes พร้อม
- [ ] Documentation links และ hashes ตรวจได้

---

# Part H — M7: Final PR Review and Merge to Main

## 14. M7 Objective

เปลี่ยน Draft PR เป็น Ready for Review และ Merge โดยรักษา Evidence commit
history และไม่ให้ Source หลัง Approval เปลี่ยนโดยไม่ Rerun Gate

## 14.1 Pre-ready Checklist

- R4 status = `APPROVE*`
- Decision Record grants authorization
- Parent Plan/README updated
- Phase 0 v3 strict verify ผ่าน
- PR ไม่มี unresolved blocking comments
- Working tree clean
- Branch pushed
- `origin/main` drift check ผ่าน

หาก `main` เปลี่ยนหลัง Official R3/R4:

1. Merge latest `main` เข้า branch
2. Run full local gates
3. Assess affected source/config
4. ถ้ากระทบ Runtime/Evaluation ให้ Rerun M2–M5
5. Invalidate approval หาก Source identity เปลี่ยน

## 14.2 Mark PR Ready

```bash
gh pr ready <pr-number>
```

PR description ต้องเปลี่ยน Current status เป็น Approved พร้อม link:

- R3 v3 artifacts
- Human/Product approvals
- Decision Record v2
- R4 Closure v3
- Phase 0 v3

## 14.3 Required Reviews

อย่างน้อย:

- Independent technical review 1 คน
- Evaluation/Security review หรือ role sign-off
- Domain/Product approval ตาม Artifacts
- Required GitHub checks ผ่าน

Branch protection ที่ตั้งใน GitHub เป็น Source of Truth หากเข้มกว่านี้ให้ใช้
ค่าที่เข้มกว่า

## 14.4 Merge Strategy

แนะนำ **Merge commit** ไม่ใช้ Squash/Rebase merge เพราะ R0–R4 Artifacts
อ้าง Commit history และต้องการรักษา Source/Evidence traceability

ตัวอย่าง:

```bash
gh pr merge <pr-number> --merge --delete-branch=false
```

ห้าม Auto-delete Branch ในขั้นนี้ ต้องรอ M8 และ M9

## 14.5 Merge Preconditions

- Head SHA ที่ Review ตรงกับ SHA ที่จะ Merge
- ไม่มี Commit ใหม่หลัง Final approval
- Checks ผูกกับ Head SHA ล่าสุด
- Mergeability ไม่มี Conflict
- Approved profile เป็น Code/config ที่อยู่ใน PR จริง

## 14.6 M7 Exit Criteria

- [ ] PR Ready และ Reviews ครบ
- [ ] Required checks ผ่านบน Final head SHA
- [ ] Merge commit สำเร็จ
- [ ] Branch ยังไม่ถูกลบ
- [ ] Merge commit SHA ถูกบันทึก

---

# Part I — M8: Verify Main and Tag Approved Version

## 15. M8 Objective

ยืนยันว่า `main` หลัง Merge ตรงกับ Source ที่อนุมัติ ก่อนสร้าง Tag ที่ใช้เป็น
Release/Audit reference

## 15.1 Update Local Main Safely

```bash
git fetch origin --prune
git switch main
git pull --ff-only origin main
git status -sb
```

ห้ามใช้ `git reset --hard` เป็นขั้นตอนปกติ

## 15.2 Post-merge Verification

```bash
SEARCH_MODE=keyword venv/bin/python -m unittest discover -s tests -v
SEARCH_MODE=keyword venv/bin/python -m src.evaluation.regression
venv/bin/python -m unittest tests.test_retriever_contract -v
venv/bin/python -m compileall -q src tests
git diff --check
```

เพิ่ม:

- Strict Phase 0 v3 manifest verification
- R4 v3 Evidence/hash verification
- Approved profile/config consistency
- Historical artifact immutability
- Secret scan
- Optional three-mode smoke/re-baseline เมื่อมี Explicit query approval

Post-merge verification ต้องไม่เขียนทับ Official Evidence เดิม

## 15.3 Tag Policy

เลือก Tag naming ให้สอดคล้อง Repo:

```text
track-a-v1.0.0
```

หรือใช้ Project SemVer เช่น `v0.2.0` หาก Repository มี Release policy อยู่แล้ว
ห้ามใช้สองระบบปนกันโดยไม่มี Mapping

แนะนำ Signed annotated tag เมื่อ Signing พร้อม:

```bash
git tag -s track-a-v1.0.0 \
  -m "Track A approved; see track_a_closure_report_v3.md"
```

Fallback:

```bash
git tag -a track-a-v1.0.0 \
  -m "Track A approved; see track_a_closure_report_v3.md"
```

ก่อน Push tag:

```bash
git show --stat track-a-v1.0.0
git merge-base --is-ancestor track-a-v1.0.0 origin/main
```

จากนั้น:

```bash
git push origin track-a-v1.0.0
```

## 15.4 Tag Metadata

Release note/Tag message ควรอ้าง:

- Merge commit SHA
- Approved profile
- R4 Closure report path/hash
- Decision Record path/hash
- Phase 0 v3 manifest/result
- Accepted Risk IDs

## 15.5 Post-merge Failure Policy

หาก Verification ล้ม:

- ห้าม Tag
- ห้ามลบ Branch
- เปิด Incident/Follow-up issue
- หากกระทบ Safety/Runtime ให้ Revert Merge ผ่าน PR
- ห้าม Rewrite `main` history หรือ force-push
- กลับ M1/M2 หลัง Root Cause ชัดเจน

## 15.6 M8 Exit Criteria

- [ ] Local/remote main ตรงกัน
- [ ] Post-merge gates ผ่าน
- [ ] Phase 0 v3 strict verify ผ่าน
- [ ] Tag ชี้ Merge commit ที่ตรวจแล้ว
- [ ] Tag ถูก Push สำเร็จ
- [ ] Release notes/evidence links ตรวจได้

---

# Part J — M9: Delete Remediation Branch

## 16. M9 Objective

ลบ Branch หลังมี Main + Tag เป็น Recovery/Audit reference แล้ว โดยไม่ทำให้
Evidence สูญหาย

## 16.1 Pre-delete Checks

```bash
git fetch origin --prune
git branch --merged origin/main
git ls-remote --heads origin fix/track-a-closure
git ls-remote --tags origin track-a-v1.0.0
gh pr view <pr-number> --json state,mergedAt,mergeCommit
```

Required:

- PR state = MERGED
- Remote main มี Merge commit
- Approved tag มีอยู่และชี้ Commit ที่ถูกต้อง
- ไม่มี Unresolved blocking review
- Release/Evidence artifacts อยู่บน main
- ไม่มี Hotfix/Follow-up ที่ยังต้องใช้ Branch นี้

## 16.2 Delete Remote Branch

```bash
git push origin --delete fix/track-a-closure
```

## 16.3 Delete Local Branch

ต้องอยู่บน `main` ก่อน:

```bash
git switch main
git branch -d fix/track-a-closure
```

ใช้ `-d` เท่านั้น ถ้า Git ปฏิเสธแปลว่ายังมี Commit ที่ไม่ Merge ให้หยุดตรวจ
ห้ามใช้ `-D` เพื่อข้าม Safety Gate

## 16.4 Recovery

หากต้องการสร้าง Branch กลับ:

```bash
git switch -c fix/track-a-closure-recovery track-a-v1.0.0
```

Tag และ Merge commit คือ Recovery anchors ไม่ใช่ Branch ที่ลบแล้ว

## 16.5 M9 Exit Criteria

- [ ] PR merged
- [ ] Main verified
- [ ] Approved tag pushed
- [ ] Remote branch deleted
- [ ] Local branch deletedด้วย `-d`
- [ ] Audit/Evidence links ยังเข้าถึงได้

---

## 17. Required Quality Gates Summary

| Gate Group | Blocking condition |
|---|---|
| Source | Clean worktree, reviewed commit, no base drift |
| Unit/Regression/Contract | 100% pass |
| Retrieval | No regression vs A0; Thai improvement |
| Context | Header/Budget validity 100% |
| Citation | Validity/Coverage 100% |
| Answer | Faithfulness ≥95%, Relevance ≥4/5 |
| Answerability | Negative ≥90%, expected-evidence contradiction = 0 |
| High-risk | Unsupported claim = 0 |
| Runtime | Warm p95 ≤3s, Primary p95 ≤2s หรือ approved waivable risk |
| Memory | Peak RSS ≤6 GiB |
| Failure | Unhandled exception = 0, fail closed within timeout |
| Evidence | Hash/schema/identity match; no overwrite |
| Security | No secret/raw prohibited content in public artifacts |
| Human | Domain review approved |
| Business | Product approval/risk acceptance approved |
| R4 | `APPROVE` หรือ `APPROVE_WITH_ACCEPTED_RISK` |
| PR | Final SHA reviewed; required checks pass |
| Release | Main verified before tag |

---

## 18. Roles and Responsibilities

| Role | Responsibility |
|---|---|
| AI Solution Engineer | Architecture, trade-offs, final technical recommendation |
| AI Engineer | Answer/Citation/Reranker implementation |
| Evaluation Owner | Dataset, runner, metric, evidence integrity |
| Security Reviewer | Data boundary, logs, fail-closed, secret scan |
| Domain Reviewer | Thai/mixed/high-risk semantic correctness |
| Product/Business Owner | UX/latency/not-found trade-off และ Risk Acceptance |
| PR Maintainer | Branch protection, final merge SHA, tag/release |

---

## 19. Estimated Timeline

| Stage | Estimated effort |
|---|---:|
| M0 Draft PR and scope | 0.25 วัน |
| M1 Answer/Citation remediation | 1–2 วัน |
| M1 Performance/Secondary tuning | 1–3 วัน |
| M2 R3 rerun and validation | 1–2 วัน |
| M3 Human/Product review | 0.5–2 วัน + waiting time |
| M4–M6 Closure/Docs/Phase 0 v3 | 0.5–1 วัน |
| M7–M9 Review/Merge/Tag/Cleanup | 0.5–1 วัน |
| **รวม Engineering effort** | **4–9 วันทำงาน** |

เวลาไม่รวมการรอ Reviewer, API approval, Model download หรือ Business decision

---

## 20. Risk Register

| ID | Risk | Impact | Mitigation |
|---|---|---:|---|
| AMR-R01 | แก้ Artifact v2 ย้อนหลัง | High | Version v3; immutability tests |
| AMR-R02 | ลด Metric threshold เพื่อให้ผ่าน | High | Decision/Risk record required |
| AMR-R03 | Citation repair สร้าง citation ใหม่ที่ไม่ support | High | Validate title + claim support after repair |
| AMR-R04 | มี Context แล้วบังคับตอบจน Hallucinate | High | Evidence sufficiency contract |
| AMR-R05 | Optimize latency แล้ว Thai/Multi-section regression | High | Full ablation/non-regression gates |
| AMR-R06 | Phase 0 v2 ถูกใช้รับรอง Source ใหม่ | High | Create Phase 0 v3 |
| AMR-R07 | Main เปลี่ยนหลัง Official Evaluation | High | Base-drift check; rerun affected gates |
| AMR-R08 | Squash ทำ Evidence commit trace หาย | Medium | Merge commit strategy |
| AMR-R09 | Tag ก่อน Post-merge verification | High | M8 blocking gate |
| AMR-R10 | ลบ Branch ก่อน Merge/Tag | High | M9 pre-delete checks; use `-d` |
| AMR-R11 | External evaluation ส่งข้อมูลเกิน approval | High | Separate explicit flags and cache boundary |
| AMR-R12 | Human approval เป็น Self-approval โดยไม่ระบุ | Medium | Role/separation record |

---

## 21. Suggested Commit Sequence

```text
fix: enforce bounded answer citation repair
fix: prevent evidence and not-found contradictions
fix: reject unsupported high-risk claims
perf: reduce primary reranker latency
test: extend Track A approval gates
feat: version Track A R3 and R4 evidence specifications
test: record Track A R3 v3 evidence
docs: record Track A human and product approvals
docs: approve Track A closure v3
chore: freeze Enterprise Phase 0 v3
docs: update Track A parent plan and release notes
```

Generated evidence commits ต้องเกิดหลัง Source commit ที่ใช้วัด และระบุ
Source SHA ใน Artifact

---

## 22. Master Execution Checklist

### Draft Review

- [ ] Draft PR เปิดและระบุ `NOT_APPROVED`
- [ ] Reviewer lanes/owners ครบ
- [ ] Base drift ไม่มีหรือถูก resolve

### Remediation

- [ ] Citation coverage guardrail
- [ ] Bounded repair
- [ ] Not-found contradiction fix
- [ ] High-risk deterministic validation
- [ ] Performance optimization
- [ ] Secondary policy
- [ ] Local gates 100%

### R3 v3

- [ ] A0–A7 ablation
- [ ] End-to-end 40 cases
- [ ] Citation validity/coverage 100%
- [ ] Unsupported high-risk = 0
- [ ] Performance gates
- [ ] Failure paths
- [ ] Evidence security/integrity

### Approval

- [ ] Human/Domain review
- [ ] Product/Business approval
- [ ] Risk Acceptance หรือ none

### Closure

- [ ] Decision Record v2
- [ ] R4 Closure v3
- [ ] Phase 0 v3
- [ ] Status = `APPROVE*`
- [ ] Parent Plan/README updated

### Merge and Release

- [ ] PR Final Review
- [ ] Merge commit
- [ ] Main verification
- [ ] Approved tag
- [ ] Release notes
- [ ] Branch cleanup

---

## 23. Final Definition of Done

งาน Approval/Merge/Release จะถือว่าเสร็จเมื่อ:

1. Blockers ใน R3 v2 ถูกแก้และมี Regression tests
2. R3 v3 ผ่าน Retrieval, Answer, Performance และ Failure gates
3. Human/Domain review ได้รับ Approval
4. Product/Business decision ถูกบันทึก
5. Non-waivable Safety gates ผ่านทั้งหมด
6. Risk Acceptance มีเฉพาะ Waivable risk และมี Expiry/Owner
7. R4 Closure v3 เป็น `APPROVE` หรือ `APPROVE_WITH_ACCEPTED_RISK`
8. Parent Plan และ README ชี้ Approved Evidence
9. Enterprise Phase 0 v3 รับรอง Final source
10. Final PR SHA ผ่าน Review และ Checks
11. Merge เข้า `main` ด้วย Traceable merge commit
12. `main` ผ่าน Post-merge Verification
13. Approved annotated/signed tag ถูก Push
14. Remediation Branch ถูกลบหลัง Tag สำเร็จ
15. Historical v1/v2 artifacts ไม่ถูกแก้ย้อนหลัง

Final release record:

```text
Track A Status: APPROVED | APPROVED_WITH_ACCEPTED_RISK
Approved Profile: <name/version>
Merge Commit: <sha>
Release Tag: <tag>
Closure Evidence: <path + sha256>
Accepted Risks: <IDs or none>
Rollback Anchor: <tag/merge commit>
Branch Cleanup: completed
```

---

## 24. Immediate Next Actions

1. ตรวจว่ามี Pull Request ของ `fix/track-a-closure` อยู่แล้วหรือไม่
2. หากไม่มี ให้เปิด Draft PR พร้อมสถานะ `NOT_APPROVED`
3. Assign Technical/Evaluation/Security/Domain/Product reviewers
4. เริ่ม Workstream Citation Coverage + High-risk validator ก่อน
5. แก้ Expected-evidence/not-found contradiction
6. Profile และลด Primary latency โดยไม่ลด Quality
7. เพิ่ม Versioned R3/R4 runner ก่อนรัน Evidence รุ่นใหม่
8. รัน R3 v3 ครบทุก Gate
9. ทำ Human/Product approval
10. สร้าง R4/Phase 0 v3
11. Mark PR Ready หลัง Closure เป็น `APPROVE*` เท่านั้น
12. Merge → Verify main → Tag → Delete branch ตาม M7–M9
