# Enterprise Track — Phase 0 Baseline

- Generated at: 2026-07-28T14:07:01+07:00
- Baseline ID: `enterprise-phase0-v1`
- Retriever contract: `1.0.0`
- Dataset: `lean-quality-v1` (40 cases)
- Dataset SHA-256: `3f80666e6dfd77b7a668eb82c3a5dc6f79a8eed12a97988fc499bdccaf55ff3f`
- Corpus SHA-256: `e09382f19b18ef2a52e1e93826e81852ee649d4bb5ddccb74a1865b8b60fe5c4` (54 sections)
- Source-tree SHA-256: `9b9abfa802a2ae5bf1246ada493c71cbf53dce16b0ef09944fd12af65964a3da` (52 files)
- Runtime: Python 3.11.15
- Corpus embedding boundary: cache hit; corpus content was not sent
- Answer-level evaluation: not requested

## Verification gates

| check | result | count | duration |
|---|---|---:|---:|
| unit_tests | PASS | 107 | 2699.8 ms |
| keyword_regression | PASS | 15 | 109.4 ms |
| retriever_contract | PASS | 8 | 479.3 ms |

## Retrieval baseline

| mode | hit@k | recall@k | MRR | not-found discipline | avg latency | p95 latency |
|---|---:|---:|---:|---:|---:|---:|
| keyword | 66.7% | 63.9% | 0.650 | 30.0% | 9.3 ms | 0.3 ms |
| semantic | 70.0% | 68.3% | 0.667 | 50.0% | 1175.6 ms | 2478.1 ms |
| hybrid | 90.0% | 88.9% | 0.900 | 80.0% | 1970.8 ms | 2943.7 ms |

Answerable metrics are separated from negative discipline. A false positive is any result returned for a negative case.

## Runtime health

| mode | implementation | source | query failures | reranker fallbacks | answerability rejections |
|---|---|---|---:|---:|---:|
| keyword | BM25Retriever | bm25 | 0 | 0 | 0 |
| semantic | OpenAIEmbeddingRetriever | dense | 0 | 0 | 0 |
| hybrid | RerankingRetriever | hybrid | 0 | 0 | 142 |

## Per-category breakdown

| category           | n  | metric   | keyword | semantic | hybrid |
|--------------------|----|----------|---------|----------|--------|
| english_answerable | 10 | hit_rate | 100%    | 100%     | 100%   |
| english_answerable | 10 | recall   | 100%    | 100%     | 100%   |
| english_answerable | 10 | MRR      | 1.000   | 1.000    | 1.000  |
| thai_answerable    | 10 | hit_rate | 0%      | 10%      | 70%    |
| thai_answerable    | 10 | recall   | 0%      | 10%      | 70%    |
| thai_answerable    | 10 | MRR      | 0.000   | 0.100    | 0.700  |
| mixed_answerable   | 5  | hit_rate | 100%    | 100%     | 100%   |
| mixed_answerable   | 5  | recall   | 100%    | 100%     | 100%   |
| mixed_answerable   | 5  | MRR      | 1.000   | 0.800    | 1.000  |
| negative           | 10 | FP_rate  | 70%     | 50%      | 20%    |
| multi_section      | 5  | hit_rate | 100%    | 100%     | 100%   |
| multi_section      | 5  | recall   | 83%     | 90%      | 93%    |
| multi_section      | 5  | MRR      | 0.900   | 1.000    | 1.000  |

## Imperfect cases

| mode     | case                      | expected                                              | retrieved (top-k)                                                                                                                                                               |
|----------|---------------------------|-------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| keyword  | th_remote_work_days       | Remote Work Policy                                    | []                                                                                                                                                                              |
| keyword  | th_annual_leave_carryover | Annual Leave                                          | []                                                                                                                                                                              |
| keyword  | th_sick_leave_certificate | Sick Leave                                            | []                                                                                                                                                                              |
| keyword  | th_ordination_leave       | Ordination Leave                                      | []                                                                                                                                                                              |
| keyword  | th_maternity_leave        | Parental Leave                                        | []                                                                                                                                                                              |
| keyword  | th_salary_payment_date    | Compensation Disbursement Schedule                    | []                                                                                                                                                                              |
| keyword  | th_probation_duration     | Probation Period                                      | []                                                                                                                                                                              |
| keyword  | th_training_budget        | Training Budget                                       | []                                                                                                                                                                              |
| keyword  | th_resignation_notice     | Resignation Process                                   | []                                                                                                                                                                              |
| keyword  | th_security_incident      | Security Incident Response Process                    | []                                                                                                                                                                              |
| keyword  | neg_home_addresses        | (nothing)                                             | Resignation Process, Equipment and Laptop Policy, Employee Referral Program, VPN Usage                                                                                          |
| keyword  | neg_source_credentials    | (nothing)                                             | IT Security and Password Policy                                                                                                                                                 |
| keyword  | neg_performance_rating    | (nothing)                                             | Performance Review Cycle                                                                                                                                                        |
| keyword  | neg_customer_cards        | (nothing)                                             | Corporate Credit Card, Service Credit Policy, PaySiam Gateway Product Overview                                                                                                  |
| keyword  | neg_board_minutes         | (nothing)                                             | Meeting Room and Desk Booking                                                                                                                                                   |
| keyword  | neg_acquisition_plan      | (nothing)                                             | Ordination Leave, Company Holidays                                                                                                                                              |
| keyword  | neg_biometric_records     | (nothing)                                             | Office Access and Visitor Policy                                                                                                                                                |
| keyword  | multi_remote_security     | Remote Work Policy, VPN Usage                         | Hybrid Work Guidelines, Remote Work Policy, Office Access and Visitor Policy                                                                                                    |
| keyword  | multi_new_employee        | Onboarding Process, Probation Period, Health Benefits | Probation Period, Health Benefits                                                                                                                                               |
| semantic | th_remote_work_days       | Remote Work Policy                                    | []                                                                                                                                                                              |
| semantic | th_annual_leave_carryover | Annual Leave                                          | []                                                                                                                                                                              |
| semantic | th_sick_leave_certificate | Sick Leave                                            | []                                                                                                                                                                              |
| semantic | th_ordination_leave       | Ordination Leave                                      | []                                                                                                                                                                              |
| semantic | th_maternity_leave        | Parental Leave                                        | []                                                                                                                                                                              |
| semantic | th_probation_duration     | Probation Period                                      | Hybrid Work Guidelines                                                                                                                                                          |
| semantic | th_training_budget        | Training Budget                                       | []                                                                                                                                                                              |
| semantic | th_resignation_notice     | Resignation Process                                   | []                                                                                                                                                                              |
| semantic | th_security_incident      | Security Incident Response Process                    | []                                                                                                                                                                              |
| semantic | neg_wifi_password         | (nothing)                                             | IT Security and Password Policy, VPN Usage                                                                                                                                      |
| semantic | neg_performance_rating    | (nothing)                                             | Employee Referral Program                                                                                                                                                       |
| semantic | neg_customer_cards        | (nothing)                                             | PaySiam Gateway Product Overview, Corporate Credit Card, Petty Cash Policy, Service Credit Policy, Vendor Invoice and Payment Terms                                             |
| semantic | neg_acquisition_plan      | (nothing)                                             | Company Overview, Vendor Invoice and Payment Terms, Provident Fund, Company Holidays, Customer Support Service Levels, Petty Cash Policy                                        |
| semantic | neg_medical_diagnoses     | (nothing)                                             | Employee Assistance Program                                                                                                                                                     |
| semantic | multi_remote_security     | Remote Work Policy, VPN Usage                         | Remote Work Policy, International Travel Approval Process, IT Security and Password Policy, Hybrid Work Guidelines, Client Site Visit Policy, International Travel Visa Support |
| hybrid   | th_maternity_leave        | Parental Leave                                        | Bereavement and Compassionate Absence                                                                                                                                           |
| hybrid   | th_probation_duration     | Probation Period                                      | Ordination Leave                                                                                                                                                                |
| hybrid   | th_resignation_notice     | Resignation Process                                   | Ordination Leave, Bereavement and Compassionate Absence, Sick Leave                                                                                                             |
| hybrid   | neg_customer_cards        | (nothing)                                             | PaySiam Gateway Product Overview, Company Overview, ChatServe Product Overview                                                                                                  |
| hybrid   | neg_acquisition_plan      | (nothing)                                             | Company Overview, Provident Fund, ChatServe Product Overview, Customer Support Service Levels, PaySiam Gateway Product Overview, Vendor Invoice and Payment Terms               |
| hybrid   | multi_new_employee        | Onboarding Process, Probation Period, Health Benefits | Probation Period, Employee Referral Program, Internal Transfer Program, Wellness and Fitness Benefit, Health Benefits, Provident Fund                                           |

## Reproducibility and security

- Unit, exact keyword regression, and Retriever contract gates run before any external API request.
- Evaluation modes use the same factory-backed implementations as the application; fallback output is rejected as an invalid baseline.
- Reports store case IDs, labels, retrieved titles, scores, and latency—not raw queries, prompts, secrets, or document bodies.
- Semantic/hybrid modes send evaluation query strings to OpenAI Embeddings only after an explicit command-line approval flag.
- A missing/corrupt corpus cache fails closed unless corpus embedding is approved with a separate flag.
- Any source, test, contract, dependency, dataset, corpus, or runtime configuration change makes the strict reproduction gate fail. The historical manifest remains immutable while later-phase CI validates its structure without comparing current source bytes.
