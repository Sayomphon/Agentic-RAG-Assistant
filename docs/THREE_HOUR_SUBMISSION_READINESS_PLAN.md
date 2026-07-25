# แผนปิดงาน P0–P2 ภายใน 3 ชั่วโมง

## 1. เป้าหมายของแผน

แผนนี้ออกแบบเพื่อยกระดับโปรเจกต์ Agentic RAG จากสถานะ
“มี feature หลายส่วนแล้ว แต่ tests, evaluation, เอกสาร และ submission artifacts
ยังไม่สอดคล้องกัน” ให้เป็นสถานะ **Submission-ready สำหรับ AI Engineer
Programming Test ภายใน 180 นาที**

คำว่า “เสร็จ” ในแผนนี้หมายถึง:

1. P0 ที่กระทบ correctness และเงื่อนไขบังคับของโจทย์ผ่านทั้งหมด
2. P1 ที่ช่วยพิสูจน์ความเป็น AI Engineer มีหลักฐานที่ตรวจซ้ำได้
3. P2 ที่สร้างไว้แล้วได้รับการตรวจและนำเสนออย่างถูกต้อง
4. Feature เชิง Production ที่ไม่จำเป็นต่อคะแนนถูกระบุเป็น roadmap อย่างโปร่งใส
   แทนการเร่งสร้าง implementation ที่ทดสอบไม่ครบ

เวลารวม: **180 นาที**

---

## 2. Definition of Done หลังครบ 3 ชั่วโมง

งานจะถือว่าเสร็จเมื่อผ่านทุกข้อด้านล่าง:

- `python -m unittest discover -v` ผ่านทุก test
- มี Retrieval Evaluation Dataset เพียงแหล่งเดียวที่เป็น Source of Truth
- Query `What is the CEO's salary?` ไม่คืน false-positive chunk
- Critical queries คืน expected sections และไม่เกิน `top_k`
- มี tests ครอบคลุม:
  - retrieval ranking
  - empty query
  - missing knowledge base
  - not-found fallback
  - graph topology
  - forced tool call
  - mocked positive/negative End-to-End
- Report Generator สามารถแสดง source title/citation ในคำตอบ
- README ตรงกับโค้ดและผล evaluation ปัจจุบัน
- README ไม่อ้างว่า KB มี 21 sections เมื่อปัจจุบันมี 54 sections
- README ไม่ระบุ Semantic/Hybrid เป็น future work เพราะ implement แล้ว
- มี screenshots อย่างน้อย 4 กรณี
- `screenshots/` ไม่มีเพียง `.gitkeep`
- มี GitHub Actions สำหรับ offline tests
- `.env` ยังถูก ignore และไม่มี secret อยู่ใน tracked files
- `git diff --check` ผ่าน
- ทุกไฟล์ที่ต้องส่งถูก commit เป็น logical commits
- หากมี GitHub remote แล้ว ต้อง push และทำ fresh-clone verification

---

## 3. Scope ที่ต้องทำ

### 3.1 Must-have ภายใน 3 ชั่วโมง

ลำดับความสำคัญ:

1. Retrieval correctness
2. Evaluation/Test consistency
3. Grounded citations
4. Submission artifacts
5. Minimal CI และ error UX
6. README ที่อิงหลักฐานจริง

### 3.2 Scope Boundary

ภายในรอบ 3 ชั่วโมงให้ทำเฉพาะ Must-have ด้านบน ห้ามเพิ่ม feature ใหม่
นอกเหนือจากแผน เพราะทุกนาทีต้องใช้กับ correctness, tests, evidence,
documentation และ submission quality

หากพบแนวคิดเพิ่มเติมระหว่างทำ ให้บันทึกไว้ใน working notes เท่านั้น
ไม่สร้าง placeholder code และไม่ขยาย dependency จนกว่า Go/No-Go Gate
ก่อนส่งจะผ่านครบทุกข้อ

---

## 4. Timeline 180 นาที

| เวลา | Workstream | ผลลัพธ์บังคับ |
|---|---|---|
| 00:00–00:10 | Baseline และ Scope Freeze | บันทึกผล tests/eval ปัจจุบันและห้ามเพิ่ม feature ใหม่ |
| 00:10–00:35 | P0 Retrieval Correctness | แก้ possessive-token bug และทำ critical retrieval cases ผ่าน |
| 00:35–01:05 | P0 Single Evaluation Source | รวม test dataset และทำ acceptance criteria ให้ชัด |
| 01:05–01:35 | P0 Missing Automated Tests | เพิ่ม missing-KB, fallback, graph และ mocked E2E tests |
| 01:35–01:55 | P1 Citations และ Evidence Contract | Final answer มี source citation และมี test รองรับ |
| 01:55–02:10 | P1 Error UX และ Minimal CI | CLI error อ่านรู้เรื่องและ GitHub Actions รัน offline tests |
| 02:10–02:35 | P0/P1 README และ Evaluation Evidence | README ตรงกับ 54-section KB และ metrics ล่าสุด |
| 02:35–02:50 | Submission Screenshots | ได้ 4 screenshots ที่เห็น query, evidence และ answer |
| 02:50–03:00 | Final Audit/Commit/Push | Tests green, secret hygiene, commit และ fresh-clone checklist |

---

## 5. Work Package 0 — Baseline และ Scope Freeze

เวลา: **10 นาที**

### 5.1 เป้าหมาย

สร้าง baseline ก่อนแก้ เพื่อป้องกันการแก้แบบไม่มีหลักฐาน และล็อกว่า
จะไม่เพิ่ม feature นอกแผน

### 5.2 คำสั่งตรวจ

```bash
git status --short --branch
env SEARCH_MODE=keyword venv/bin/python -m unittest discover -v
env SEARCH_MODE=keyword venv/bin/python -m evals.evaluate_retrieval
venv/bin/python -m pip check
git diff --check
```

### 5.3 Baseline ที่คาดจากสถานะปัจจุบัน

- Automated tests: 8 tests, ผ่าน 7, fail 1
- Legacy evaluation:
  - exact match 73.3%
  - macro precision 85.0%
  - macro recall 93.3%
- `negative_ceo_salary` คืน `Parental Leave`
- README และ Retrieval Improvement Plan มี claims ที่ไม่ตรงผลล่าสุด
- `screenshots/` ยังมีเพียง `.gitkeep`

### 5.4 Exit criteria

- เก็บ baseline ไว้ใน working note หรือ commit description
- ห้ามเริ่ม UI redesign, service ใหม่ หรือ agent ใหม่

---

## 6. Work Package 1 — P0 Retrieval Correctness

เวลา: **25 นาที**

### 6.1 ไฟล์เป้าหมาย

- `src/retrievers/keyword.py`
- `tests/test_retrieval.py`

### 6.2 ปัญหาที่ต้องแก้

`CEO's` ถูก tokenize เป็น:

```text
ceo, s, salary
```

token `s` ไป match กับ possessive words เช่น `company's`
และ `salary` match กับ Parental Leave ทำให้เอกสารผ่าน
minimum matched-term gate ทั้งที่ไม่มีคำว่า CEO

### 6.3 แนวทางแก้ที่แนะนำ

ทำ normalization ของ English possessive ก่อน tokenization:

```text
CEO's       -> CEO
company's   -> company
employee’s  -> employee
```

จากนั้นเพิ่ม defensive filter ไม่ให้ token `s` เป็น search term

ไม่ควรแก้ด้วย:

- การเพิ่ม `CEO salary` เป็น hard-coded negative query
- การเพิ่ม threshold เฉพาะ query
- การลด recall ทั้งระบบเพื่อแก้เพียงกรณีเดียว

### 6.4 Test cases บังคับ

```text
What is the CEO's salary?       -> []
What is the CEOs salary?        -> []
international travel policy     -> travel-related sections
work from home                  -> Remote Work Policy
cybersecurity incident          -> relevant security sections only
```

### 6.5 เกณฑ์ผ่าน

- Negative CEO cases คืน `[]`
- ไม่มี regression กับ travel/remote/security
- ทุกผลลัพธ์ไม่เกิน `top_k`

### 6.6 Time-box rule

หากแก้ไม่ผ่านภายใน 25 นาที:

1. เพิ่ม possessive normalization และ unit test ก่อน
2. ใช้ `SEARCH_MODE=semantic` เป็น demo mode ชั่วคราวเฉพาะเมื่อ negative FP = 0%
3. ห้าม retune threshold แบบสุ่ม

---

## 7. Work Package 2 — P0 Single Evaluation Source of Truth

เวลา: **30 นาที**

### 7.1 ปัญหาปัจจุบัน

มี test set สองชุด:

- `evals/retrieval_cases.json`
- `src/evaluation/testset.py`

ทั้งสองชุดมี scope และ expected results ต่างกัน ทำให้:

- tests อ้าง exact-match แบบหนึ่ง
- mode-comparison report ใช้อีกชุด
- README เลือกตัวเลขที่ดูดีที่สุดโดยไม่ชัดว่าอ้างชุดใด
- KB ขยายเป็น 54 sections แต่ expected titles บางกรณียังอิง KB เดิม

### 7.2 การตัดสินใจ

ให้ใช้ `evals/retrieval_cases.json` เป็น Source of Truth เพียงชุดเดียว
เพราะ:

- แยก data ออกจาก evaluation code
- review diff ได้ง่าย
- เพิ่ม test case โดยไม่แก้ Python
- ใช้ซ้ำได้ทั้ง unit tests และ mode comparison

### 7.3 Schema ที่ควรใช้

แต่ละ case ควรมี:

```json
{
  "id": "negative_ceo_salary",
  "category": "negative",
  "query": "What is the CEO's salary?",
  "expected_titles": [],
  "forbidden_titles": ["Parental Leave"],
  "required_for_default": true
}
```

Field ความหมาย:

- `category`: `lexical`, `semantic`, `multi_chunk`, `negative`
- `expected_titles`: relevant ground truth
- `forbidden_titles`: chunk ที่ห้ามคืน
- `required_for_default`: ต้องผ่านใน default `SEARCH_MODE`

### 7.4 Migration

1. ย้าย cases จาก `src/evaluation/testset.py` เข้า JSON
2. ให้ `src/evaluation/testset.py` เป็น loader/re-export เท่านั้น
   หรือถอดออกหากไม่มี caller
3. ให้ทั้ง:
   - `evals/evaluate_retrieval.py`
   - `src/evaluation/run_eval.py`
   - `tests/test_retrieval.py`

   โหลด dataset เดียวกัน

4. อัปเดต expected titles ให้สะท้อน KB 54 sections เช่น:
   - International Travel Visa Support อาจ relevant ต่อ travel query
   - Security Incident Response Process relevant ต่อ incident/phishing query

### 7.5 Acceptance criteria

สำหรับ `required_for_default=true`:

- Hit Rate@K = 100%
- Negative false-positive rate = 0%
- ไม่มี forbidden title
- ทุก query คืนไม่เกิน `top_k`

สำหรับ full cross-mode benchmark:

- บันทึก Hit Rate@K, Recall@K, MRR, Negative FP Rate และ latency
- ไม่จำเป็นต้องบังคับทุก mode ได้ 100%
- README ต้องอธิบาย trade-off ตามผลจริง

### 7.6 Time-box rule

หาก migration ใช้เกิน 20 นาที:

- เก็บ JSON เป็น canonical dataset
- ปรับ `src/evaluation/testset.py` ให้โหลด JSON
- ห้ามเพิ่ม test cases ใหม่จนกว่า tests จะกลับมา green

---

## 8. Work Package 3 — P0 Missing Automated Tests

เวลา: **30 นาที**

### 8.1 ไฟล์เป้าหมาย

- `tests/test_retrieval.py`
- `tests/test_retriever_agent.py`
- `tests/test_reporter.py` — เพิ่มใหม่
- `tests/test_graph.py` — เพิ่มใหม่

### 8.2 Tests ที่ต้องเพิ่ม

#### A. Missing Knowledge Base

ตรวจว่า `load_chunks()`:

- raise `FileNotFoundError`
- error message ระบุ path และแนวทางแก้
- ไม่ต้องเรียก LLM

#### B. Reporter Deterministic Fallback

เมื่อ `snippets=[]`:

- คืน `NOT_FOUND_SENTENCE`
- ไม่เรียก `get_llm()`

#### C. Graph Topology

ตรวจว่า graph มีลำดับ:

```text
START -> data_retriever -> report_generator -> END
```

หาก LangGraph public API สำหรับ introspection ไม่เสถียร
ให้ test ผ่าน mocked node execution แทนการอิง internal attributes

#### D. Mocked Positive End-to-End

- Mock Retriever LLM tool call
- Mock search results
- Mock Reporter LLM response
- Invoke graph
- Assert snippets จาก Retriever ถูกส่งถึง Reporter
- Assert final report ถูกเขียนลง state

#### E. Mocked Negative End-to-End

- Retrieval คืน `[]`
- Reporter คืน deterministic fallback
- Assert Reporter LLM ไม่ถูกเรียก

### 8.3 เกณฑ์ผ่าน

```bash
env SEARCH_MODE=keyword venv/bin/python -m unittest discover -v
```

ต้อง:

- exit code = 0
- ไม่มี network call
- ไม่ต้องใช้ API key
- ไม่มี flaky timing assertion

### 8.4 Time-box rule

หากเหลือเวลาน้อย ให้เรียง test ตามลำดับ:

1. Reporter fallback
2. Mocked negative E2E
3. Missing KB
4. Mocked positive E2E
5. Graph topology

---

## 9. Work Package 4 — P1 Grounded Citations

เวลา: **20 นาที**

### 9.1 ไฟล์เป้าหมาย

- `src/agents/reporter.py`
- `tests/test_reporter.py`
- `README.md`

### 9.2 เป้าหมาย

ให้ทุก factual section ใน final answer อ้าง source title ที่มาจาก snippets เช่น:

```text
- ขออนุมัติล่วงหน้าอย่างน้อย 14 วันผ่าน TravelHub
  [International Travel Approval Process]
```

### 9.3 Prompt contract

เพิ่มกติกา:

- อ้าง source title หลัง claim หรือ bullet
- ใช้เฉพาะ title ที่ปรากฏใน snippet header
- ห้ามสร้างชื่อเอกสารใหม่
- หากหลาย claims มาจาก source เดียว สามารถอ้างท้าย bullet group
- Not-found sentence ต้องไม่มี citation

### 9.4 Validation

ใน mocked Reporter test:

- final answer มี source title ที่ส่งเข้าไป
- ไม่มี source title ที่ไม่ได้อยู่ใน snippets
- empty snippets ยังใช้ deterministic fallback

### 9.5 Scope cut

ภายใน 20 นาทีให้ทำ citation ระดับ section title เท่านั้น
ไม่ทำ:

- page number
- character offsets
- footnotes
- citation verification model

---

## 10. Work Package 5 — P1 Error UX และ Minimal CI

เวลา: **15 นาที**

### 10.1 CLI Error Handling

ไฟล์:

- `main.py`
- `src/agents/__init__.py`

เพิ่ม:

- จับ authentication, connection, timeout และ rate-limit errors ที่ระดับ CLI
- แสดงข้อความสั้นที่บอก:
  - failure category
  - model/provider
  - สิ่งที่ผู้ใช้ควรตรวจ
- ห้ามแสดง API key
- กำหนด explicit request timeout และ bounded retry

ไม่ควร:

- catch แล้วตอบเหมือนระบบสำเร็จ
- ซ่อน stack trace ใน debug mode ถาวร
- retry ไม่จำกัด

### 10.2 GitHub Actions

เพิ่ม:

```text
.github/workflows/test.yml
```

Workflow ขั้นต่ำ:

- trigger: `push`, `pull_request`
- Python 3.11
- install `requirements.txt`
- `pip check`
- `python -m unittest discover -v`
- `python -m evals.evaluate_retrieval`
- บังคับ `SEARCH_MODE=keyword`
- ไม่ใช้ `OPENAI_API_KEY`

### 10.3 Acceptance criteria

- Workflow ไม่มี secret dependency
- Offline tests รันเหมือน local
- CLI provider error ไม่แสดง raw traceback ใน normal mode

---

## 11. Work Package 6 — README และ Evaluation Evidence

เวลา: **25 นาที**

### 11.1 ไฟล์เป้าหมาย

- `README.md`
- `evaluation_results.md`
- `docs/RETRIEVAL_IMPROVEMENT_PLAN.md`

### 11.2 สิ่งที่ต้องแก้

1. เปลี่ยน KB size จาก 21 เป็น 54 sections
2. อัปเดต Project Structure ให้มี:
   - `src/retrievers/`
   - `src/evaluation/`
   - `app.py`
   - GitHub workflow
3. เปลี่ยนข้อความที่บอก Semantic/Hybrid เป็น future work
   ให้เป็น implemented modes พร้อม trade-offs
4. ลบ claim `100%` ที่ไม่ตรงผลปัจจุบัน
5. Link ไป `evaluation_results.md`
6. ระบุ run date, dataset size และ config ที่ใช้สร้าง metrics
7. เปลี่ยน `git clone <this-repo>` เป็น URL จริงเมื่อสร้าง remote แล้ว
8. เพิ่มคำสั่ง:

```bash
python -m unittest discover -v
python -m evals.evaluate_retrieval
python -m src.evaluation.run_eval
streamlit run app.py
```

9. เพิ่ม `Known Limitations` แบบกระชับ:
   - evaluation dataset ยังมีขนาดเล็ก
   - Semantic/Hybrid mode มี API latency และ cost
   - threshold และ aliases ยังอิง corpus ปัจจุบัน
   - ควรใช้ anonymized real queries เพื่อประเมินก่อนนำไปใช้จริง

### 11.3 วิธีรายงาน metrics

แยกให้ชัด:

- Critical regression suite
- Full retrieval benchmark
- Keyword/Semantic/Hybrid trade-off
- Offline vs API-dependent evaluation

ห้ามใช้คำว่า production-ready หรือ statistically representative

### 11.4 Acceptance criteria

- ทุกตัวเลขใน README trace กลับไปยัง evaluation artifact ได้
- ไม่มี claim ขัดกับ current code
- README อธิบายสิ่งที่ยังไม่ทำอย่างตรงไปตรงมา

---

## 12. Work Package 7 — Screenshots

เวลา: **15 นาที**

### 12.1 ไฟล์ที่ต้องได้

```text
screenshots/
├── 01_travel_multi_chunk.png
├── 02_remote_work_citations.png
├── 03_not_found_guardrail.png
└── 04_thai_query.png
```

### 12.2 Query ที่แนะนำ

1. Travel:

   ```text
   What do I need to know before an international business trip?
   ```

2. Remote work:

   ```text
   Can I work from home and what approval or security rules apply?
   ```

3. Not found:

   ```text
   What is the CEO's salary?
   ```

4. Thai:

   ```text
   ลาบวชได้กี่วัน และต้องแจ้งล่วงหน้าอย่างไร?
   ```

### 12.3 ภาพต้องแสดง

- User query
- Search mode
- Reformulated search query หากมี
- Retrieved titles
- Scores/provenance
- Final answer
- Citations
- Not-found behavior ใน negative case

### 12.4 Acceptance criteria

- อ่านข้อความสำคัญได้โดยไม่ zoom มาก
- ไม่มี API key, email ส่วนตัว หรือ local filesystem path
- README embed ภาพอย่างน้อย 3 ภาพ
- ภาพตรงกับโค้ดและ metrics รุ่นล่าสุด

---

## 13. Work Package 8 — Final Audit, Commit และ Push

เวลา: **10 นาที**

### 13.1 Local audit

```bash
env SEARCH_MODE=keyword venv/bin/python -m unittest discover -v
env SEARCH_MODE=keyword venv/bin/python -m evals.evaluate_retrieval
venv/bin/python -m pip check
git diff --check
git status --short
git check-ignore -v .env
```

### 13.2 Logical commit plan

แนะนำ 3 commits:

```text
fix: harden retrieval normalization and relevance gates
test: unify retrieval evaluation and cover graph guardrails
docs: add citations, screenshots, CI, and submission evidence
```

หาก Streamlit/Semantic/Hybrid ยังไม่เคยถูก commit ให้แยก:

```text
feat: add semantic and hybrid retrieval explorer
```

### 13.3 Fresh-clone verification

หลัง push:

1. Clone ลง temporary directory
2. สร้าง venv ใหม่
3. ติดตั้ง `requirements.txt`
4. รัน offline tests โดยไม่มี `.env`
5. สร้าง `.env` เฉพาะ local
6. รันหนึ่ง End-to-End query
7. เปิด README ผ่าน GitHub และตรวจ Mermaid/screenshots

### 13.4 Exit criteria

- Working tree สะอาด
- GitHub Actions เริ่มรัน
- README clone URL ใช้งานได้
- `.env` ไม่อยู่ใน commit/history ใหม่
- ผู้สัมภาษณ์สามารถ setup จาก README ได้ภายใน 5 นาที

---

## 14. Go/No-Go Gate ก่อนส่ง

### GO

ส่งได้เมื่อ:

- Tests ผ่านทั้งหมด
- CEO salary คืน no result
- Negative FP rate ของ default mode = 0% ใน critical suite
- Final answer มี citations
- Screenshots ครบ
- README ตรงกับ implementation
- GitHub repository clone ได้
- ไม่มี secret

### NO-GO

ยังไม่ควรส่งหาก:

- Test ยัง fail
- README อ้าง 100% แต่ evaluation ไม่ถึง
- `screenshots/` ยังว่าง
- CEO salary ยังคืน Parental Leave
- Hybrid ถูกตั้งเป็น default ทั้งที่ negative FP ยังสูง
- GitHub clone URL ยังเป็น placeholder
- มี uncommitted files ที่เป็นส่วนหนึ่งของ deliverable

---

## 15. หากเวลาเริ่มไม่พอ

ใช้ลำดับการตัด scope ดังนี้:

1. ห้ามเพิ่ม feature ใหม่ที่อยู่นอก Must-have ของแผน
2. ตัดการเพิ่ม test cases ใหม่ แต่ห้ามตัด failing tests เดิม
3. ใช้ citations แบบ section title ไม่สร้าง citation framework
4. ใช้ screenshots 4 ภาพ ไม่ทำ GIF/video
5. ใช้ Streamlit UI ที่มีอยู่ ไม่ redesign
6. ทำ CI เฉพาะ offline unittest/eval
7. ต้องรักษา:
   - retrieval correctness
   - tests green
   - README accuracy
   - screenshots
   - GitHub reproducibility

---

## 16. Expected Outcome หลังจบ 3 ชั่วโมง

ผู้สัมภาษณ์ควรเห็นหลักฐานว่า candidate สามารถ:

- ออกแบบ multi-agent orchestration ที่ชัดเจน
- สร้าง custom RAG retrieval และแก้ failure จากข้อมูลจริง
- ไม่ใช้ LLM เป็นตัวกลบ retrieval quality
- วัด Hit Rate, Recall, MRR, false-positive และ latency
- ใช้ structural guardrails และ deterministic fallback
- สร้าง source-grounded answer พร้อม citations
- ทำ automated regression tests และ CI
- อธิบายข้อจำกัดและ trade-offs อย่างมีเหตุผล
- ส่ง repository ที่ clone และรันซ้ำได้

จุดขายหลักของ submission ไม่ควรเป็น “มี feature มากที่สุด”
แต่ควรเป็น **correctness, grounding, evaluation, transparency และ
reproducibility ที่พิสูจน์ได้**
