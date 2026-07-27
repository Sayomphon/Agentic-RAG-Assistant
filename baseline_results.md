# Track A — Step 1 Mini Baseline

- Generated at: 2026-07-27T21:05:15+07:00
- Dataset: `lean-quality-v1` (40 cases)
- Dataset SHA-256: `3f80666e6dfd77b7a668eb82c3a5dc6f79a8eed12a97988fc499bdccaf55ff3f`
- Corpus SHA-256: `e09382f19b18ef2a52e1e93826e81852ee649d4bb5ddccb74a1865b8b60fe5c4` (54 sections)
- Runtime: Python 3.11.15
- Answer-level evaluation: not requested

## Verification gates

| check | result | count | duration |
|---|---|---:|---:|
| unit_tests | PASS | 45 | 672.1 ms |
| keyword_regression | PASS | 15 | 65.3 ms |

## Retrieval baseline

| mode | hit@k | recall@k | MRR | not-found discipline | avg latency | p95 latency |
|---|---:|---:|---:|---:|---:|---:|
| keyword | 66.7% | 63.9% | 0.650 | 30.0% | 0.1 ms | 0.1 ms |

Metrics for answerable cases are reported separately from negative discipline. A false positive is any returned chunk for a negative case.

## Per-category breakdown

| category           | n  | metric   | keyword |
|--------------------|----|----------|---------|
| english_answerable | 10 | hit_rate | 100%    |
| english_answerable | 10 | recall   | 100%    |
| english_answerable | 10 | MRR      | 1.000   |
| thai_answerable    | 10 | hit_rate | 0%      |
| thai_answerable    | 10 | recall   | 0%      |
| thai_answerable    | 10 | MRR      | 0.000   |
| mixed_answerable   | 5  | hit_rate | 100%    |
| mixed_answerable   | 5  | recall   | 100%    |
| mixed_answerable   | 5  | MRR      | 1.000   |
| negative           | 10 | FP_rate  | 70%     |
| multi_section      | 5  | hit_rate | 100%    |
| multi_section      | 5  | recall   | 83%     |
| multi_section      | 5  | MRR      | 0.900   |

## Imperfect cases

| mode    | case                      | expected                                              | retrieved (top-k)                                                                      |
|---------|---------------------------|-------------------------------------------------------|----------------------------------------------------------------------------------------|
| keyword | th_remote_work_days       | Remote Work Policy                                    | []                                                                                     |
| keyword | th_annual_leave_carryover | Annual Leave                                          | []                                                                                     |
| keyword | th_sick_leave_certificate | Sick Leave                                            | []                                                                                     |
| keyword | th_ordination_leave       | Ordination Leave                                      | []                                                                                     |
| keyword | th_maternity_leave        | Parental Leave                                        | []                                                                                     |
| keyword | th_salary_payment_date    | Compensation Disbursement Schedule                    | []                                                                                     |
| keyword | th_probation_duration     | Probation Period                                      | []                                                                                     |
| keyword | th_training_budget        | Training Budget                                       | []                                                                                     |
| keyword | th_resignation_notice     | Resignation Process                                   | []                                                                                     |
| keyword | th_security_incident      | Security Incident Response Process                    | []                                                                                     |
| keyword | neg_home_addresses        | (nothing)                                             | Resignation Process, Equipment and Laptop Policy, Employee Referral Program, VPN Usage |
| keyword | neg_source_credentials    | (nothing)                                             | IT Security and Password Policy                                                        |
| keyword | neg_performance_rating    | (nothing)                                             | Performance Review Cycle                                                               |
| keyword | neg_customer_cards        | (nothing)                                             | Corporate Credit Card, Service Credit Policy, PaySiam Gateway Product Overview         |
| keyword | neg_board_minutes         | (nothing)                                             | Meeting Room and Desk Booking                                                          |
| keyword | neg_acquisition_plan      | (nothing)                                             | Ordination Leave, Company Holidays                                                     |
| keyword | neg_biometric_records     | (nothing)                                             | Office Access and Visitor Policy                                                       |
| keyword | multi_remote_security     | Remote Work Policy, VPN Usage                         | Hybrid Work Guidelines, Remote Work Policy, Office Access and Visitor Policy           |
| keyword | multi_new_employee        | Onboarding Process, Probation Period, Health Benefits | Probation Period, Health Benefits                                                      |

## Reproducibility and security

- Direct dependencies and installed versions are recorded in `baseline_results.json`.
- The report captures only an explicit non-secret configuration allowlist.
- API keys, raw environment variables, prompts, and document bodies are not written to baseline artifacts.
- Re-running against a changed dataset, corpus, or retrieval config fails the manifest gate and requires an explicit new version.
