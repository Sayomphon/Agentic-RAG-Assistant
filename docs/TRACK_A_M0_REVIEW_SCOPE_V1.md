# Track A M0 Review Scope and Recovery Record

> **Status:** `NOT_APPROVED`
>
> **R3 decision:** `REJECT_AND_RETUNE`
>
> This record freezes the M0 review scope. It is not merge, release, tag, or
> production-promotion authorization.

## Repository and source identity

- Repository: `Sayomphon/Agentic-RAG-Assistant`
- Base branch: `main`
- Resolved base SHA: `9d7eb46b730ba169cd5e4083aca2ae6accea65a3`
- Review branch: `fix/track-a-closure`
- M1 implementation commits:
  - `51834dc5adc1bcfd711b1d68087c2def1e9c6980`
  - `11ff86a54c11ab9dbec0e3c7c5eccbb4ec5199ac`
- M0 recovery source SHA: the commit containing this record; the exact SHA
  must also be recorded in the Draft PR before M2 starts.

The review branch was fast-forwarded to the resolved base SHA without a
rebase, force-push, content rewrite, or conflict resolution.

## Premature-merge recovery

Draft PR #1 was merged into `main` as
`9d7eb46b730ba169cd5e4083aca2ae6accea65a3` before the required M5
authorization. The merge has identical tree content to the reviewed branch;
the only drift is the merge commit itself.

This event does not change the Track A decision to approved. The code on
`main` remains an unapproved candidate and must not be tagged, released, or
promoted. A new Draft PR must carry the remaining approval evidence and stay
in review-only state until M5 grants authorization. No history rewrite or
direct revert is authorized by this record.

## Frozen scope

The Draft review scope consists of:

1. Existing R0–R4 Track A closure changes now reachable from `main`.
2. M1 answer/citation remediation in `51834dc`.
3. M1 performance and Secondary-policy remediation in `11ff86a`.
4. This M0 scope/recovery record and the versioned approval plan.

The following work is explicitly out of scope for M0–M1 and is not started by
this record:

- R3 v3 evidence generation (M2)
- Human, Domain, or Product approval (M3)
- R4 v3 closure generation (M4)
- Closure authorization (M5)
- Final release, tagging, or branch cleanup

## Review lanes and owners

| Review lane | M0 owner | Boundary |
|---|---|---|
| AI/Code | `@Sayomphon` | Implementation and architecture review |
| Evaluation | `@Sayomphon` | Evidence-integrity coordination; no M3 approval implied |
| Security | `@Sayomphon` | Data boundary, logging, and fail-closed coordination |
| Domain | `@Sayomphon` | Review-lane coordination; M3 Domain verdict remains pending |
| Product | `@Sayomphon` | Review-lane coordination; M3 Business decision remains pending |
| PR maintenance | `@Sayomphon` | Keep Draft; no auto-merge, tag, or promotion |

These assignments establish accountable M0 coordination only. They are not
Human/Domain or Product/Business approvals. M3 must record role separation,
verdicts, limitations, and risk acceptance independently.

## M1 blocker disposition

| Blocker | Disposition | Evidence |
|---|---|---|
| Citation completeness and invented citations | Remediated with deterministic validation and one bounded repair | `51834dc`; focused tests |
| Expected evidence versus exact not-found contradiction | Remediated with evidence-sufficiency decisions and safe partial behavior | `51834dc`; focused tests |
| Unsupported high-risk claims | Remediated with exact numeric, identifier, and role anchors | `51834dc`; focused tests |
| Primary reranker latency | Candidate 10 / max length 128 passed repeated local profiling | M1 engineering evidence |
| Secondary multi-section regression | Restricted to low-risk single-section emergency use; otherwise fail closed | `11ff86a`; focused tests |

`track_a_balanced_v2` remains an engineering candidate. M2 must validate it
with the complete, versioned R3 v3 suite before any approval claim.

## Current passing gates

- Unit tests: `207/207`
- Regression suite: `15/15`
- Retriever contract: `9/9`
- Compile and JSON validation: passed
- Diff and secret/raw-log scans: passed
- Selected local performance runs:
  - Primary p95: `1,135 ms` and `1,728 ms`
  - Warm retrieval p95: `1,940 ms` and `2,210 ms`
  - Peak RSS: approximately `2.1–2.2 GiB`

These are M1 local verification results, not R3 v3 results.

## External-data boundaries

- Primary and Secondary rerankers use immutable local model revisions.
- M2 query-embedding provider calls require separate explicit approval before
  execution.
- Answer, prompt, snippet, and document-body transmission is not approved by
  this record.
- Published artifacts may contain case IDs, section-title metadata, metrics,
  hashes, model identities, and stable reason codes only.
- Raw queries, answers, snippets, document bodies, prompts, credentials, and
  raw exception details must remain excluded from Git and public artifacts.
- Owner-only Human-review material must remain Git-ignored with owner-only
  permissions.

## Evidence references

| Artifact | SHA-256 |
|---|---|
| `TRACK_A_APPROVAL_MERGE_RELEASE_PLAN.md` | `c809c1e4d10c3da03ca6cc597d922ff12d1e82ec18d92bd0b20cf6dc4b33ac44` |
| `docs/TRACK_A_M1_REMEDIATION_EVIDENCE_V1.md` | `7f724d6257678deb2438120d790d9185b80263b380b86924e4d7b29d66e26937` |
| `src/evaluation/configs/track_a_balanced_v2.json` | `6b20bd96d0bc8810aeab318053e2e63d44c16f22cdc0166e5485d44c30053579` |
| `docs/TRACK_A_DECISION_RECORD.md` | `4c92a6864ee780025ed0dd56625c709bfb9cd148899da11aea459df935030a6d` |
| `docs/TRACK_A_R3_MEASUREMENT_PLAN.md` | `1f9eb5d18482135f36220ab65c8156dde7f0d569d0cb57234dc63dc472df93fa` |

## M0–M1 handoff checklist

- [x] Review scope and base SHA recorded.
- [x] Review lanes have accountable coordinators.
- [x] M1 blockers have implementation and local test evidence.
- [x] External-data boundaries are explicit.
- [x] Auto-merge, release, tag, and production promotion are prohibited.
- [ ] New Draft PR is open and records the exact recovery commit SHA.
- [ ] Branch has no unpushed commits.
- [ ] Full local gates pass from the committed, clean source tree.

The final three checks must be completed before M2 begins.
