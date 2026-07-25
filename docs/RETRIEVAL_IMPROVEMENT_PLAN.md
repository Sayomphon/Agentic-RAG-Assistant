# Retrieval Improvement Plan

## Goal

Make natural-language retrieval precise enough that the Report Generator
receives relevant evidence rather than relying on the LLM to ignore false
positives. The solution must remain local, explainable, reproducible, and small
enough for a three-day programming assessment.

## Baseline problem

The original BM25 implementation tokenized every English word and used one
absolute score threshold. Natural-language stop words could therefore outweigh
the actual intent:

| Query | Baseline result | Expected result |
|---|---|---|
| `work from home` | Equipment and Laptop Policy | Remote Work Policy |
| `What is the CEO's salary?` | Four unrelated sections | No result |
| `What are the cybersecurity incident reporting rules?` | Three unrelated sections | IT Security and Password Policy |

The LLM query-reformulation step sometimes masked these errors, but it did not
make the retrieval mechanism itself reliable.

## Implementation plan

1. Normalize natural-language queries deterministically.
   - Remove English stop words and generic search-intent words.
   - Apply lightweight suffix normalization.
   - Map a small set of high-value aliases such as `work from home` to
     `remote work`.
2. Improve ranking and filtering.
   - Score section titles and bodies separately.
   - Boost title matches.
   - Require multiple distinct matched terms for multi-term queries.
   - Reject candidates below a percentage of the best result.
3. Bound agent behaviour.
   - Preserve the original query when it already contains English search terms.
   - Use the model-generated query only to translate non-English input.
   - Remove model control over `top_k`.
   - Execute only one tool call and cap the final evidence list at `TOP_K`.
4. Add reproducible evaluation.
   - Version a golden query set with expected section titles.
   - Report exact-match, macro precision, and macro recall.
   - Run the same cases in the standard-library `unittest` suite.

## Acceptance criteria

- All 15 golden retrieval cases return the exact expected section set.
- Negative queries return no sections.
- Tool and agent outputs never exceed `TOP_K`.
- Empty and punctuation-only queries return no sections.
- Tests run without an API key.
- Existing End-to-End travel, remote-work, not-found, and Thai queries remain
  grounded after the retrieval change.

## Result

The offline evaluation now reports:

- 15/15 exact section-set matches
- 100% macro precision
- 100% macro recall
- 7/7 automated tests passing

These metrics describe the version-controlled golden set only. They prevent
known regressions but do not replace a larger production dataset based on real,
anonymized user queries.

## Next production step

If real-query evaluation shows unseen vocabulary or Thai-language recall gaps,
add a hybrid semantic retriever behind the existing `Retriever` protocol and
compare it against this lexical baseline. Select the new mode only when it
improves measured recall without materially reducing precision, latency, data
privacy, or reproducibility.
