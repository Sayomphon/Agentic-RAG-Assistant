# แผนปิดงานก่อนส่ง — เฉพาะสิ่งที่ต้องทำ

> ปรับปรุง 2026-07-25 หลังเทียบกับโจทย์ `AI Engineer Programming Test.docx`
> และ verify สถานะจริงของ repo ด้วยการรัน tests/eval
>
> เวลาที่เหลือจริง: **~60 นาที** (+20 นาทีสำหรับ optional)

---

## 1. โจทย์บังคับอะไรบ้าง

โจทย์ระบุ deliverables ไว้ 3 อย่างและ evaluation criteria 4 ข้อ เท่านั้น

| โจทย์กำหนด | สถานะ |
|---|---|
| `knowledge_base.txt` (a few paragraphs) | ✅ 54 sections — เกินพอ ไม่ต้องแตะ |
| Data Retriever agent + custom retrieval tool | ✅ `src/agents/retriever.py`, `src/tools/retrieval.py` |
| Report Generator agent | ✅ `src/agents/reporter.py` |
| Sequential orchestration | ✅ `src/graph.py` (LangGraph) |
| รันด้วย sample query | ✅ ทำได้ผ่าน `main.py` และ `app.py` |
| **Screenshot ของ final output หลาย queries** | ❌ `screenshots/` มีแค่ `.gitkeep` |
| **Submit ทั้งหมดบน GitHub repository** | ❌ ยังมีไฟล์ uncommitted |

Evaluation criteria ของโจทย์: (1) ใช้ framework ถูกต้อง (2) RAG mechanism ได้ผลจริง
(3) คำตอบสุดท้ายชัด ไม่ซ้ำซ้อน ถูกต้องตามข้อมูล (4) code structure อ่านง่าย

โจทย์ **ไม่ได้ขอ** unit tests, CI, evaluation metrics, citations, README หรือ Streamlit UI
ทุกอย่างที่เกินจากตารางด้านบนคือ bonus ที่หนุน criteria ข้อ 2–4 ทางอ้อมเท่านั้น

---

## 2. สถานะปัจจุบัน (verified 2026-07-25)

```text
env SEARCH_MODE=keyword venv/bin/python -m unittest discover -v
→ Ran 8 tests, FAILED (failures=1)

env SEARCH_MODE=keyword venv/bin/python -m evals.evaluate_retrieval
→ cases=15  exact_match=80.0%  macro_precision=91.7%  macro_recall=100.0%
```

ปิดไปแล้ว:

- **Possessive-token bug แก้แล้ว** — `negative_ceo_salary` PASS, ไม่คืน `Parental Leave` แล้ว
- **README ตรงกับโค้ดแล้ว** — ระบุ 54 sections, semantic/hybrid เป็น implemented modes
  พร้อมตาราง trade-off, มี Evaluation Results และ Limitations & Next Steps
- **`evaluation_results.md` traceable แล้ว** — ระบุ run date, dataset source และ config ครบ

ยังเหลือ:

- 3 cases fail เพราะ `expected_titles` ล้าสมัย ไม่ใช่ bug ของ retrieval
- `screenshots/` ว่าง
- README ไม่มีส่วน clone URL และไม่ได้ embed screenshots
- ยังไม่ commit/push

---

## 3. Definition of Done

- `python -m unittest discover -v` exit code 0
- Query `What is the CEO's salary?` ไม่คืน false-positive chunk *(ผ่านแล้ว)*
- มี screenshots อย่างน้อย 4 กรณี รวม query ที่โจทย์ยกตัวอย่าง
- README มีคำสั่ง clone ที่ใช้งานได้จริง และ embed screenshot อย่างน้อย 3 ภาพ
- `.env` ยังถูก ignore และไม่มี secret ใน tracked files
- ทุกไฟล์ที่ต้องส่งถูก commit และ push ขึ้น GitHub

---

## 4. Timeline

| เวลา | งาน | ผลลัพธ์บังคับ |
|---|---|---|
| 00:00–00:15 | WP-A: Ground truth sync | tests green ทั้ง 8 |
| 00:15–00:35 | WP-B: Screenshots | 4 ภาพใน `screenshots/` |
| 00:35–00:50 | WP-C: README submission section | clone URL + embedded screenshots |
| 00:50–01:00 | WP-D: Commit และ push | working tree สะอาด, repo clone ได้ |
| *01:00–01:20* | *WP-E (optional): Citations* | *final answer อ้าง source title* |

---

## 5. WP-A — Ground Truth Sync

เวลา: **15 นาที**

### 5.1 ปัญหา

Retriever คืน section ที่ *relevant จริง* แต่ `expected_titles` ยังอิง KB รุ่นก่อนขยาย
ทำให้นับเป็น false positive ทั้งที่ผลลัพธ์ถูกต้อง

| case | retriever คืนเพิ่ม | relevant จริงไหม |
|---|---|---|
| `travel_multi_chunk` | `International Travel Visa Support` | ใช่ |
| `cybersecurity_incident` | `Security Incident Response Process` | ใช่ |
| `phishing_incident` | `Security Incident Response Process` | ใช่ |

### 5.2 การแก้

แก้ `evals/retrieval_cases.json` ไฟล์เดียว เพิ่ม title ข้างต้นเข้า `expected_titles`
ของทั้งสาม cases

**ห้าม** แก้ threshold, ห้ามลด `top_k`, ห้ามแตะ `src/retrievers/keyword.py`
เพราะ retrieval ทำงานถูกอยู่แล้ว — ที่ผิดคือ ground truth

### 5.3 เกณฑ์ผ่าน

```bash
env SEARCH_MODE=keyword venv/bin/python -m unittest discover -v
env SEARCH_MODE=keyword venv/bin/python -m evals.evaluate_retrieval
```

- tests ผ่านทั้ง 8
- `exact_match` = 100%
- `negative_ceo_salary` ยัง PASS (ไม่ regress)

หลังแก้แล้วต้องอัปเดตตัวเลขใน README ถ้ามีจุดใดอ้าง exact match ชุดนี้

---

## 6. WP-B — Screenshots

เวลา: **20 นาที**

นี่คือ **deliverable ที่โจทย์บังคับตรงตัว** และเป็นข้อเดียวที่ยังไม่มีเลย

### 6.1 ไฟล์ที่ต้องได้

```text
screenshots/
├── 01_international_travel.png
├── 02_remote_work.png
├── 03_not_found_guardrail.png
└── 04_thai_query.png
```

### 6.2 Query ที่ใช้

1. **ตรงตามที่โจทย์ยกตัวอย่าง** — ต้องมีภาพนี้

   ```text
   What is the policy on international travel?
   ```

2. Multi-section synthesis

   ```text
   Can I work from home and what approval or security rules apply?
   ```

3. Negative / guardrail

   ```text
   What is the CEO's salary?
   ```

4. Thai query

   ```text
   ลาบวชได้กี่วัน และต้องแจ้งล่วงหน้าอย่างไร?
   ```

### 6.3 ภาพต้องแสดง

- User query
- Retrieved section titles (หลักฐานว่า RAG ทำงาน — ตรงกับ criteria ข้อ 2)
- Final answer จาก Report Generator (criteria ข้อ 3)
- Not-found behavior ในภาพที่ 3

ใช้ `streamlit run app.py` เพราะเห็น retrieved snippets และ answer ในภาพเดียว
ถ้า Streamlit มีปัญหา ใช้ terminal output จาก `python main.py` แทนได้

### 6.4 เกณฑ์ผ่าน

- อ่านข้อความสำคัญได้โดยไม่ต้อง zoom
- ไม่มี API key, email ส่วนตัว หรือ local filesystem path ติดในภาพ
- ภาพตรงกับโค้ดรุ่นล่าสุด

---

## 7. WP-C — README Submission Section

เวลา: **15 นาที**

README ส่วนเนื้อหาเทคนิคครบแล้ว เหลือเฉพาะส่วนที่ผู้ตรวจต้องใช้จริง

### 7.1 สิ่งที่ต้องเพิ่ม

1. คำสั่ง clone ที่ใช้ URL จริง (ไม่ใช่ placeholder) ในหัวข้อ `Setup & Run`
2. หัวข้อ `Sample Output` ที่ embed screenshot อย่างน้อย 3 ภาพ
   พร้อม query กำกับใต้ภาพ
3. ยืนยันว่าคำสั่งใน `Setup & Run` รันได้จาก clone เปล่า

### 7.2 เกณฑ์ผ่าน

- ทุกตัวเลขใน README trace กลับไปยัง `evaluation_results.md` ได้
- ไม่มี claim ที่ขัดกับโค้ดปัจจุบัน
- ผู้ตรวจ setup ตาม README ได้ภายใน 5 นาที

---

## 8. WP-D — Commit และ Push

เวลา: **10 นาที**

### 8.1 Audit ก่อน commit

```bash
env SEARCH_MODE=keyword venv/bin/python -m unittest discover -v
git diff --check
git status --short
git check-ignore -v .env
```

### 8.2 Commit plan

```text
fix: sync retrieval ground truth with expanded knowledge base
docs: add submission screenshots and setup instructions
```

### 8.3 เกณฑ์ผ่าน

- Working tree สะอาด
- `.env` ไม่อยู่ใน commit หรือ history
- Repository clone ได้ และ README แสดง Mermaid/screenshots ถูกต้องบน GitHub

---

## 9. WP-E — Citations *(optional)*

เวลา: **20 นาที** — ทำเฉพาะเมื่อ WP-A ถึง WP-D เสร็จครบ

โจทย์ไม่ได้ขอ แต่หนุน criteria ข้อ 3 โดยตรง เพราะพิสูจน์ว่าคำตอบ
grounded กับ snippets ไม่ใช่ LLM แต่งเอง

### 9.1 ขอบเขต

แก้ prompt ใน `src/agents/reporter.py` ให้อ้าง section title ท้าย claim:

```text
- ขออนุมัติล่วงหน้าอย่างน้อย 14 วันผ่าน TravelHub
  [International Travel Approval Process]
```

กติกา: ใช้เฉพาะ title ที่ปรากฏใน snippet header, ห้ามสร้างชื่อเอกสารใหม่,
not-found sentence ต้องไม่มี citation

### 9.2 Scope cut

ทำแค่ระดับ section title เท่านั้น ไม่ทำ page number, character offset,
footnotes หรือ citation verification

ถ้าทำ WP-E ต้องถ่าย screenshots ใหม่ให้เห็น citations — วางแผนลำดับให้ดี
หรือข้าม WP-E ไปเลยถ้าเวลาไม่พอ

---

## 10. สิ่งที่ตัดออกจากแผนเดิม

| งานที่ตัด | เหตุผล |
|---|---|
| Baseline / Scope freeze | เป็น process ส่วนตัว ไม่ใช่ deliverable |
| Single evaluation source of truth | `evaluation_results.md` ระบุ dataset source ชัดแล้ว จึง traceable — การ migrate เป็น internal hygiene ที่ไม่มีผลต่อคะแนน |
| Missing automated tests (reporter, graph, E2E) | โจทย์ไม่ได้ขอ tests เลย ที่มีอยู่ 8 tests เพียงพอแสดง engineering discipline |
| CLI error UX hardening | ไม่อยู่ใน criteria ข้อใด |
| GitHub Actions CI | ไม่อยู่ใน criteria ข้อใด และกินเวลาที่ควรใช้กับ screenshots |
| Cross-mode benchmark เพิ่มเติม | รันและบันทึกไว้ครบใน `evaluation_results.md` แล้ว |
| Fresh-clone verification เต็มรูป | `git status` สะอาด + README ถูกต้อง เพียงพอสำหรับ submission นี้ |

หากเวลาเหลือหลัง WP-D ให้ไล่ตามลำดับ: WP-E → tests เพิ่ม → CI
ห้ามเริ่มงานในตารางนี้ก่อน WP-A ถึง WP-D เสร็จ

---

## 11. Go/No-Go Gate

### GO

- tests ผ่านทั้ง 8
- `What is the CEO's salary?` คืน no result
- screenshots ครบ 4 ภาพ รวม query ที่โจทย์ยกตัวอย่าง
- README embed screenshots และมี clone URL ใช้งานได้
- ไม่มี secret ใน repo
- push ขึ้น GitHub แล้ว

### NO-GO

- `screenshots/` ยังว่าง — ผิดข้อบังคับของโจทย์โดยตรง
- ยังไม่ได้ push หรือ clone URL เป็น placeholder
- test ยัง fail
- มี uncommitted files ที่เป็นส่วนหนึ่งของ deliverable

---

## 12. Expected Outcome

ผู้ตรวจควรเห็นหลักฐานว่า candidate สามารถ:

- ออกแบบ two-agent orchestration ด้วย LangGraph ได้ชัดเจน (criteria ข้อ 1)
- สร้าง custom retrieval tool ที่ทำงานได้จริง และแก้ failure จากข้อมูลจริง (ข้อ 2)
- ผลิตคำตอบที่ไม่ซ้ำซ้อน ถูกต้องตาม KB และมี guardrail เมื่อไม่มีข้อมูล (ข้อ 3)
- จัดโครงสร้างโค้ดแยก agents/retrievers/tools/evals ชัดเจน (ข้อ 4)
- วัดผลด้วย Hit Rate, Recall, MRR, FP rate และอธิบาย trade-off ตามผลจริง *(bonus)*

จุดขายของ submission คือ **correctness, grounding, evaluation และ transparency
ที่พิสูจน์ได้** ไม่ใช่จำนวน feature
