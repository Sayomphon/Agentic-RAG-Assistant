# Sample Q→A Results (end-to-end)

- Run date: 2026-07-25 18:55
- Pipeline: full agentic graph via `build_graph()` — router → data retriever (with query-rewrite retry loop) → report generator
- Search mode: **hybrid**  ·  model: `gpt-5-mini`  ·  `TOP_K=4`  ·  `MAX_SEARCH_ATTEMPTS=3`
- Questions: 17 — the 15 golden-set queries (lexical, semantic, multi-chunk, negative) plus a Thai query and a greeting

Each block records the agent's actual decisions: the route, every search attempt (a new attempt means the previous one returned nothing and the query was rewritten), the evidence handed to the generator, and the final answer verbatim.

## Q1. What is Form HR-204 used for?

- category: `lexical`  ·  route: `kb_query`  ·  18.8s
- search attempts:
  1. "What is Form HR-204 used for?" → 2 result(s)
- retrieved evidence:
  - **Employee Referral Program** (score 0.0164, bm25, `knowledge_base.txt`)
  - **Petty Cash Policy** (score 0.0161, bm25, `knowledge_base.txt`)
- answer:
  > Form HR-204 is used to register an employee referral in SiamPeople before the candidate's first interview, naming the candidate and the vacancy. [Employee Referral Program]

## Q2. SafeJourney Plan B coverage

- category: `lexical`  ·  route: `kb_query`  ·  16.1s
- search attempts:
  1. "SafeJourney Plan B coverage" → 1 result(s)
- retrieved evidence:
  - **International Travel Insurance** (score 0.0328, bm25+dense, `knowledge_base.txt`)
- answer:
  > - All international business trips are automatically covered by the company's group travel insurance, the SafeJourney Plan B underwritten by Bangkok Assurance PCL. [International Travel Insurance]  
  > - Emergency medical treatment coverage up to 3,000,000 THB. [International Travel Insurance]  
  > - Emergency evacuation coverage. [International Travel Insurance]  
  > - Lost-luggage compensation up to 40,000 THB per trip. [International Travel Insurance]  
  > - Employees must carry the digital insurance card, available in the HR mobile app (SiamPeople) under "My Benefits." [International Travel Insurance]  
  > - Claims must be filed through the SafeJourney portal within 30 days of returning, with original receipts and a copy of the trip approval from TravelHub. [International Travel Insurance]  
  > - Personal side-trips extending a business trip are not covered beyond 48 hours after the last business day. [International Travel Insurance]

## Q3. Accounts Payable helpdesk extension

- category: `lexical`  ·  route: `kb_query`  ·  12.6s
- search attempts:
  1. "Accounts Payable helpdesk extension" → 3 result(s)
- retrieved evidence:
  - **Vendor Invoice and Payment Terms** (score 0.0323, bm25+dense, `knowledge_base.txt`)
  - **Expense Reimbursement** (score 0.0164, dense, `knowledge_base.txt`)
  - **Purchase Requisition and Purchase Orders** (score 0.0161, dense, `knowledge_base.txt`)
- answer:
  > The Accounts Payable helpdesk can be reached at internal extension 5-3300 for status questions. [Vendor Invoice and Payment Terms]

## Q4. StockSense Growth plan price

- category: `lexical`  ·  route: `kb_query`  ·  16.8s
- search attempts:
  1. "StockSense Growth plan price" → 1 result(s)
- retrieved evidence:
  - **StockSense Product Overview** (score 0.0328, bm25+dense, `knowledge_base.txt`)
- answer:
  > The Growth plan costs 12,900 THB per month and covers up to 10 branches and 50,000 SKUs. [StockSense Product Overview]

## Q5. When do I get paid each month?

- category: `semantic`  ·  route: `kb_query`  ·  23.3s
- search attempts:
  1. "When do I get paid each month?" → 4 result(s)
- retrieved evidence:
  - **Compensation Disbursement Schedule** (score 0.0320, bm25+dense, `knowledge_base.txt`)
  - **Parental Leave** (score 0.0164, bm25, `knowledge_base.txt`)
  - **International Travel Daily Allowance** (score 0.0161, bm25, `knowledge_base.txt`)
  - **Company Holidays** (score 0.0159, bm25, `knowledge_base.txt`)
- answer:
  > - Salary is disbursed monthly on the 28th calendar day of each month. [Compensation Disbursement Schedule]  
  > - If the 28th falls on a weekend or public holiday, payment is moved to the preceding business day. [Compensation Disbursement Schedule]  
  > - Funds are transferred to the Thai bank account registered in SiamPeople, and an itemized statement appears in SiamPeople under "My Compensation" one day before disbursement. [Compensation Disbursement Schedule]  
  > - Overtime recorded and approved in TimeTrack by the 15th of the month is included in that month's payment; later approvals roll into the following month. [Compensation Disbursement Schedule]  
  > - Off-cycle corrections are processed only for discrepancies exceeding 1,000 THB; smaller differences are adjusted in the following month. [Compensation Disbursement Schedule]  
  > - Questions about deductions, provident fund contributions, or tax withholding should be directed to the People Operations team through SiamPeople. [Compensation Disbursement Schedule]

## Q6. funeral leave for my father

- category: `semantic`  ·  route: `kb_query`  ·  15.4s
- search attempts:
  1. "funeral leave for my father" → 3 result(s)
- retrieved evidence:
  - **Parental Leave** (score 0.0164, bm25, `knowledge_base.txt`)
  - **Bereavement and Compassionate Absence** (score 0.0164, dense, `knowledge_base.txt`)
  - **Annual Leave** (score 0.0161, dense, `knowledge_base.txt`)
- answer:
  > - You are entitled to up to 7 working days of compassionate absence at full pay for the passing of a parent (father). [Bereavement and Compassionate Absence]  
  > - Record the absence in LeaveDesk under the "Compassionate" category; HR may request supporting documents afterwards rather than in advance. [Bereavement and Compassionate Absence]  
  > - If you need to travel to ceremonies outside Bangkok, you may combine this compassionate absence with other accrued time off with manager approval, and additional unpaid days can be granted by the HR Business Partner. [Bereavement and Compassionate Absence]  
  > - To arrange a company wreath, contact the People Care team through SiamPeople. [Bereavement and Compassionate Absence]

## Q7. what is the dress code

- category: `semantic`  ·  route: `kb_query`  ·  12.8s
- search attempts:
  1. "what is the dress code" → 1 result(s)
- retrieved evidence:
  - **Workplace Attire Standards** (score 0.0164, dense, `knowledge_base.txt`)
- answer:
  > - Standard working attire is business casual: collared shirts, blouses, polos, chinos, skirts, or tailored trousers. [Workplace Attire Standards]  
  > - Denim without rips is acceptable on Fridays together with the company polo. [Workplace Attire Standards]  
  > - Formal business attire (a suit or jacket) is expected when meeting clients, whether at a client site or when hosting visitors at the office. [Workplace Attire Standards]  
  > - T-shirts with slogans, shorts, sandals, and sportswear are not appropriate on office days, except during MoveFest and team sports activities. [Workplace Attire Standards]  
  > - Closed-toe footwear is required in the server room and the facilities workshop. [Workplace Attire Standards]  
  > - Teams with frequent client-facing duties may define stricter norms with HR agreement. [Workplace Attire Standards]  
  > - Religious and cultural garments are always welcome. [Workplace Attire Standards]

## Q8. I want to quit my job

- category: `semantic`  ·  route: `kb_query`  ·  20.6s
- search attempts:
  1. "I want to quit my job" → 0 result(s)
  2. "Resignation procedure and required notice period for voluntary termination of employment" → 4 result(s)
- retrieved evidence:
  - **Resignation Process** (score 0.0325, bm25+dense, `knowledge_base.txt`)
  - **Probation Period** (score 0.0323, bm25+dense, `knowledge_base.txt`)
  - **Annual Leave** (score 0.0161, dense, `knowledge_base.txt`)
  - **Ordination Leave** (score 0.0156, dense, `knowledge_base.txt`)
- answer:
  > Here are the steps and key points to resign from your job:
  > 
  > - Submit at least 30 days' written notice through SiamPeople with a signed resignation letter (or 7 days' written notice if you are still in probation). [Resignation Process] [Probation Period]  
  > - HR will confirm your final working date after checking outstanding leave and project handover plans. [Resignation Process]  
  > - Complete a handover document approved by your manager as part of the departure process. [Resignation Process]  
  > - Return all equipment and access cards to IT and Facilities before leaving. [Resignation Process]  
  > - Attend an exit interview with the HR Business Partner in your final week. [Resignation Process]  
  > - Unused annual leave within the statutory entitlement will be paid out with your final salary. [Resignation Process]  
  > - Access to all systems, including SiamPeople and ExpenseFlow, is revoked at 18:00 on your last working day; submit any pending expense claims before then. [Resignation Process]  
  > - Note probation details if applicable: all new employees serve a 119-day probation; during probation either party may terminate with 7 days' written notice, and probationary employees accrue annual leave normally but may only take it after day 60 unless the manager approves otherwise. [Probation Period]

## Q9. counseling for stress and burnout

- category: `semantic`  ·  route: `kb_query`  ·  20.0s
- search attempts:
  1. "counseling for stress and burnout" → 0 result(s)
  2. "Employee Assistance Program (EAP) mental health counseling for stress and burnout — access and referral procedure" → 2 result(s)
- retrieved evidence:
  - **Employee Referral Program** (score 0.0325, bm25+dense, `knowledge_base.txt`)
  - **Employee Assistance Program** (score 0.0325, bm25+dense, `knowledge_base.txt`)
- answer:
  > Yes — counseling for stress and burnout is available through the Employee Assistance Program. [Employee Assistance Program]
  > 
  > - All employees and their immediate family members can access confidential guidance sessions with licensed practitioners for personal or work‑related difficulties (including stress and burnout). [Employee Assistance Program]  
  > - Each employee family is entitled to 6 sessions per calendar year at no cost, available in Thai or English, in person or by video call. [Employee Assistance Program]  
  > - Appointments are made directly with MindBridge by calling internal extension 5-4477 or via the MindBridge web portal linked from SiamPeople; managers and HR are never informed who has used the service. [Employee Assistance Program]  
  > - MindBridge practitioners can refer employees to MediTrust Clinic for further assessment where appropriate. [Employee Assistance Program]  
  > - In urgent situations outside office hours, the MindBridge line operates 24/7, every day of the year. [Employee Assistance Program]

## Q10. customer SLA uptime compensation

- category: `semantic`  ·  route: `kb_query`  ·  17.2s
- search attempts:
  1. "customer SLA uptime compensation" → 4 result(s)
- retrieved evidence:
  - **Service Credit Policy** (score 0.0164, dense, `knowledge_base.txt`)
  - **Support Escalation Process** (score 0.0161, dense, `knowledge_base.txt`)
  - **Customer Support Service Levels** (score 0.0159, dense, `knowledge_base.txt`)
  - **Compensation Disbursement Schedule** (score 0.0156, dense, `knowledge_base.txt`)
- answer:
  > - Uptime commitments: 99.9% per calendar month for Platinum customers and 99.5% for Standard, measured per product and excluding the announced maintenance window on Sundays from 01:00 to 05:00 Bangkok time. [Service Credit Policy]
  > 
  > - If measured availability falls below the commitment, customers may claim service credits: 5% of that month's subscription fee when availability stays above 99.0%, 10% for availability between 97.0% and 99.0%, and 25% below 97.0%. [Service Credit Policy]
  > 
  > - To claim credits, submit a request through the customer portal within 30 days of the end of the affected month, referencing related CS case numbers where available. [Service Credit Policy]
  > 
  > - Credits are applied to a future invoice (never paid in cash) and are capped at 25% of one month's fee. [Service Credit Policy]
  > 
  > - Availability statistics per product are published monthly on the status page. [Service Credit Policy]

## Q11. everything I need for an overseas business trip

- category: `multi_chunk`  ·  route: `kb_query`  ·  17.0s
- search attempts:
  1. "everything I need for an overseas business trip" → 4 result(s)
- retrieved evidence:
  - **International Travel Approval Process** (score 0.0328, bm25+dense, `knowledge_base.txt`)
  - **International Travel Insurance** (score 0.0323, bm25+dense, `knowledge_base.txt`)
  - **Domestic Travel Policy** (score 0.0312, bm25+dense, `knowledge_base.txt`)
  - **Software Request and Licensing** (score 0.0159, bm25, `knowledge_base.txt`)
- answer:
  > Below is a concise checklist of what the company requires/provides for an overseas business trip, based only on company policy documents.
  > 
  > Pre-trip approvals and submission
  > - Obtain written approval from your department head at least 14 days before departure; submit via TravelHub using “Overseas Trip Request” with a trip purpose statement, an itinerary, and a cost estimate. [International Travel Approval Process]
  > - If the trip is longer than 10 business days, obtain additional sign-off from the Managing Director. [International Travel Approval Process]
  > 
  > Booking and reimbursement rules
  > - Once approved, the Travel Desk will book economy-class airfare through the company’s contracted agency, ThaiOrbit Travel. [International Travel Approval Process]
  > - Self-booked flights are not reimbursable unless the Travel Desk confirms in writing that no contracted option was available. [International Travel Approval Process]
  > - Visa fees and airport transfers are arranged by the Travel Desk and charged directly to the department’s cost center. [International Travel Approval Process]
  > 
  > Insurance and claims
  > - All international business trips are covered by the company group travel insurance, SafeJourney Plan B (underwritten by Bangkok Assurance PCL), including emergency medical treatment (up to 3,000,000 THB), emergency evacuation, and lost-luggage compensation (up to 40,000 THB per trip). [International Travel Insurance]
  > - Carry the digital insurance card available in the HR mobile app (SiamPeople) under “My Benefits.” [International Travel Insurance]
  > - File claims through the SafeJourney portal within 30 days of returning, and submit original receipts plus a copy of the trip approval from TravelHub. [International Travel Insurance]
  > - Personal side-trips that extend a business trip are covered only up to 48 hours after the last business day (coverage does not extend beyond that). [International Travel Insurance]
  > 
  > If you need anything else beyond these policies (packing, passports, visas’ personal requirements, daily allowances, hotels for international travel, or local regulations), that information is not contained in the provided knowledge-base snippets.

## Q12. how do I buy something from a new supplier

- category: `multi_chunk`  ·  route: `kb_query`  ·  13.5s
- search attempts:
  1. "how do I buy something from a new supplier" → 1 result(s)
- retrieved evidence:
  - **Vendor Onboarding and Registration** (score 0.0328, bm25+dense, `knowledge_base.txt`)
- answer:
  > To buy from a new supplier, follow these steps:
  > 
  > - Register the vendor in ProcureDesk before issuing a first purchase order. [Vendor Onboarding and Registration]  
  > - Collect the required vendor documents: a company affidavit issued within the last 6 months, VAT registration (Por Por 20), a bank account confirmation letter, and a signed copy of the Siam Innovate supplier code of conduct. [Vendor Onboarding and Registration]  
  > - Wait for the Procurement team to screen the new vendor (screening is completed within 10 business days); sanctions and litigation checks are performed for contracts expected to exceed 1,000,000 THB per year. [Vendor Onboarding and Registration]  
  > - If the vendor has had no transactions for 24 months they will be set to inactive and must be re-verified before any new orders. [Vendor Onboarding and Registration]  
  > - Any change to a vendor’s bank details takes effect only after a call-back to a previously registered contact person and will not be processed based solely on an emailed request. [Vendor Onboarding and Registration]

## Q13. P1 response time for platinum support

- category: `multi_chunk`  ·  route: `kb_query`  ·  14.9s
- search attempts:
  1. "P1 response time for platinum support" → 3 result(s)
- retrieved evidence:
  - **Customer Support Service Levels** (score 0.0328, bm25+dense, `knowledge_base.txt`)
  - **Support Escalation Process** (score 0.0323, bm25+dense, `knowledge_base.txt`)
  - **Service Credit Policy** (score 0.0159, dense, `knowledge_base.txt`)
- answer:
  > P1 (production service fully unavailable) — first response within 15 minutes on Platinum support. [Customer Support Service Levels]
  > 
  > Response targets are measured from case creation in the portal. [Customer Support Service Levels]

## Q14. What is the CEO's salary?

- category: `negative`  ·  route: `kb_query`  ·  23.6s
- search attempts:
  1. "What is the CEO's salary?" → 0 result(s)
  2. "Chief Executive Officer base salary amount" → 0 result(s)
  3. "Chief Executive Officer annual base salary amount" → 1 result(s)
- retrieved evidence:
  - **Resignation Process** (score 0.0164, bm25, `knowledge_base.txt`)
- answer:
  > I could not find this information in the knowledge base.

## Q15. employee home addresses and phone numbers

- category: `negative`  ·  route: `kb_query`  ·  20.1s
- search attempts:
  1. "employee home addresses and phone numbers" → 0 result(s)
  2. "Employee residential address and telephone number directory" → 2 result(s)
- retrieved evidence:
  - **Emergency and Evacuation Procedures** (score 0.0164, dense, `knowledge_base.txt`)
  - **Employee Assistance Program** (score 0.0161, dense, `knowledge_base.txt`)
- answer:
  > I could not find this information in the knowledge base.

## Q16. ลาบวชได้กี่วัน และต้องแจ้งล่วงหน้าอย่างไร?

- category: `thai`  ·  route: `kb_query`  ·  22.9s
- search attempts:
  1. "ordination leave duration and required advance notice" → 4 result(s)
- retrieved evidence:
  - **Ordination Leave** (score 0.0325, bm25+dense, `knowledge_base.txt`)
  - **Annual Leave** (score 0.0323, bm25+dense, `knowledge_base.txt`)
  - **Sick Leave** (score 0.0320, bm25+dense, `knowledge_base.txt`)
  - **Bereavement and Compassionate Absence** (score 0.0156, dense, `knowledge_base.txt`)
- answer:
  > - จำนวนวัน: ลาบวชแบบได้รับค่าจ้างได้สูงสุด 15 วันทำงาน ได้ครั้งเดียวตลอดการจ้างงาน [Ordination Leave]  
  > - การแจ้งล่วงหน้า: ต้องบันทึกคำขอใน LeaveDesk ภายใต้ประเภท "Ordination" อย่างน้อย 30 วันล่วงหน้า พร้อมระบุวันที่พิธีและชื่อวัด [Ordination Leave]  
  > - เงื่อนไขเพิ่มเติม: สวัสดิการนี้ใช้ได้หลังผ่านการยืนยันการผ่านทดลองงาน และต้องส่งจดหมายยืนยันจากวัดผ่าน LeaveDesk ภายใน 7 วันหลังกลับมาทำงาน [Ordination Leave]  
  > - กรณีต้องการลาบวชนานกว่า 15 วัน สามารถขอเป็นการขาดงานส่วนตัวแบบไม่รับค่าจ้างได้ สูงสุด 120 วัน โดยต้องได้รับอนุมัติจากฝ่ายทรัพยากรบุคคล [Ordination Leave]

## Q17. Hello! What can you do?

- category: `greeting`  ·  route: `direct`  ·  10.4s
- answer:
  > Hi! I can help with items from the Siam Innovate employee handbook — ask me about leave, travel, expenses, benefits, IT security, HR processes, or products. What would you like to know?
