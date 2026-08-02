# Track A R3 — Final Answer Evaluation

- Generated at: 2026-08-02T16:06:48+07:00
- Pipeline: User → Router → Retriever/Translation → Hybrid + Reranker + Context → Rewrite when required → Generator → Validators.
- Dataset: all 40 frozen `lean-quality-v1` cases.
- One structured judge request covers faithfulness, relevance, completeness, language, and specific-data discipline.
- Published evidence excludes raw queries, answers, prompts, snippets, document bodies, credentials, and provider error text.

## Hard gates

| Metric | Result | Target | Gate |
|---|---:|---:|---|
| Route correctness | 100.0% | 100% | PASS |
| Citation validity | 100.0% | 100% | PASS |
| Citation coverage | 91.0% | 100% | FAIL |
| Negative exact not-found | 100.0% | ≥90% | PASS |
| Faithfulness | 99.2% | ≥95% | PASS |
| Relevance | 5.00/5 | ≥4.0 | PASS |
| Thai-script appropriateness | 100.0% | ≥90% | PASS |
| Unsupported high-risk claims | 1 | 0 | FAIL |

Automated gate: **FAIL** — no_not_found_after_expected_evidence_below_1, answer_citation_coverage_below_1, unsupported_high_risk_claim_count_above_0

## Human/Domain review

- Status: **PENDING_HUMAN_APPROVAL**
- Required cases: 20
- Owner-only local bundle: `.cache/track-a-r3-human-review-v1.json`
- Automated/model results do not constitute Product/Business approval.

## Sanitized per-case evidence

| Case | Category | Route | Context titles | Citations | Automated review |
|---|---|---|---:|---:|---|
| `en_remote_work_days` | english_answerable | kb_query | 6 | 2 | judge_specific_data_discipline_failed |
| `en_annual_leave_carryover` | english_answerable | kb_query | 6 | 1 | PASS |
| `en_sick_leave_certificate` | english_answerable | kb_query | 1 | 1 | PASS |
| `en_probation_duration` | english_answerable | kb_query | 5 | 1 | PASS |
| `en_training_budget` | english_answerable | kb_query | 1 | 1 | PASS |
| `en_password_length` | english_answerable | kb_query | 1 | 1 | PASS |
| `en_vpn_client` | english_answerable | kb_query | 2 | 2 | PASS |
| `en_expense_deadline` | english_answerable | kb_query | 6 | 4 | PASS |
| `en_travel_insurance` | english_answerable | kb_query | 2 | 1 | PASS |
| `en_standard_support_hours` | english_answerable | kb_query | 2 | 1 | PASS |
| `th_remote_work_days` | thai_answerable | kb_query | 6 | 2 | PASS |
| `th_annual_leave_carryover` | thai_answerable | kb_query | 3 | 1 | PASS |
| `th_sick_leave_certificate` | thai_answerable | kb_query | 1 | 1 | PASS |
| `th_ordination_leave` | thai_answerable | kb_query | 5 | 1 | PASS |
| `th_maternity_leave` | thai_answerable | kb_query | 4 | 1 | PASS |
| `th_salary_payment_date` | thai_answerable | kb_query | 1 | 1 | PASS |
| `th_probation_duration` | thai_answerable | kb_query | 6 | 1 | PASS |
| `th_training_budget` | thai_answerable | kb_query | 1 | 1 | PASS |
| `th_resignation_notice` | thai_answerable | kb_query | 2 | 1 | PASS |
| `th_security_incident` | thai_answerable | kb_query | 2 | 2 | PASS |
| `mixed_remote_portal` | mixed_answerable | kb_query | 3 | 2 | PASS |
| `mixed_hr204` | mixed_answerable | kb_query | 1 | 1 | PASS |
| `mixed_safejourney` | mixed_answerable | kb_query | 2 | 2 | PASS |
| `mixed_platinum_p1` | mixed_answerable | kb_query | 3 | 1 | PASS |
| `mixed_expense_approval` | mixed_answerable | kb_query | 6 | 1 | judge_faithfulness_below_threshold, judge_specific_data_discipline_failed, unsupported_high_risk_claim |
| `neg_ceo_salary` | negative | kb_query | 0 | 0 | PASS |
| `neg_home_addresses` | negative | kb_query | 0 | 0 | PASS |
| `neg_wifi_password` | negative | kb_query | 1 | 0 | PASS |
| `neg_source_credentials` | negative | kb_query | 1 | 0 | PASS |
| `neg_performance_rating` | negative | kb_query | 0 | 0 | PASS |
| `neg_customer_cards` | negative | kb_query | 3 | 0 | PASS |
| `neg_board_minutes` | negative | kb_query | 0 | 0 | PASS |
| `neg_acquisition_plan` | negative | kb_query | 6 | 0 | PASS |
| `neg_biometric_records` | negative | kb_query | 0 | 0 | PASS |
| `neg_medical_diagnoses` | negative | kb_query | 1 | 0 | PASS |
| `multi_overseas_trip` | multi_section | kb_query | 5 | 4 | uncited_factual_unit |
| `multi_new_vendor_purchase` | multi_section | kb_query | 2 | 2 | PASS |
| `multi_remote_security` | multi_section | kb_query | 3 | 3 | uncited_factual_unit |
| `multi_p1_service_failure` | multi_section | kb_query | 3 | 3 | uncited_factual_unit |
| `multi_new_employee` | multi_section | kb_query | 6 | 0 | not_found_despite_expected_evidence |
