# Retriever Contract

**Contract version:** `1.0.0`
**Frozen by:** Enterprise Track — Phase 0
**Safety amendment:** Track A R2 — fail-safe reranker cascade
**Python interface:** `src.retrievers.base.Retriever`

This contract isolates LangGraph, tools, evaluation, and future storage
backends from retrieval implementation details. Keyword, dense, hybrid,
reranked, and future Qdrant retrievers must satisfy the same observable
behavior.

## Interface

```python
class Retriever(Protocol):
    def search(self, query: str, top_k: int) -> list[ScoredChunk]:
        ...
```

`query` is trusted as a string by the Python core. API-layer type and length
validation belongs at the service boundary in Phase 3. `top_k` is the maximum
number of results requested by the trusted caller.

## Result contract

Every successful call returns a new `list[ScoredChunk]`.

- The result length is between zero and `max(0, top_k)`.
- Every item is a `ScoredChunk` with a finite numeric `score`.
- Results are ordered by effective `score`, highest first.
- A result set contains each logical `Chunk.index` at most once.
- `ScoredChunk.source` is non-empty and identifies retrieval provenance.
- `Chunk.title`, `Chunk.text`, `Chunk.index`, and `Chunk.source_file` are
  preserved exactly from the indexed corpus.
- `retrieval_score` and `reranker_score` are optional for backward
  compatibility. A reranked hit preserves the pre-rerank score in
  `retrieval_score` and the effective cross-encoder score in
  `reranker_score`.
- `as_snippet()` remains `[Title]\nBody`; ranking metadata is never mixed into
  evidence sent to the generator.

Deterministic retrievers must produce the same order for the same query,
corpus, configuration, dependency versions, and backend responses. Floating
point values need not be bit-identical across hardware.

## Boundary behavior

| Input or state | Required behavior |
|---|---|
| `top_k <= 0` | Return `[]` without calling a backend |
| Empty, whitespace-only, or punctuation-only query | Return `[]` without a paid provider call |
| No candidate clears relevance gates | Return `[]`; never return a least-bad result |
| More candidates than `top_k` | Return only the best `top_k` |
| Duplicate candidates from multiple retrieval paths | Deduplicate before returning |

The core protocol intentionally does not coerce invalid runtime types.
Untrusted JSON validation will be owned by the FastAPI schema in Phase 3.

## Failure and degradation contract

Initialization and query-time failures have different boundaries:

1. A backend that cannot initialize raises its documented adapter error.
   `get_retriever()` catches supported initialization failures and degrades to
   the keyword retriever.
2. A transient dense query failure increments `query_failure_count` and uses
   the configured fallback or returns `[]`.
3. A Primary reranker timeout/load/inference failure increments
   `primary_reranker_failure_count` and tries the independently pinned
   Secondary reranker.
4. If both rerankers fail, the production-default `fail_closed` policy returns
   `[]`. `fusion_order` may preserve the pre-rerank order only when explicitly
   enabled for a lab/debug run; `conservative` also closes unless a reviewed
   deterministic gate accepts evidence.
5. Secondary use, Secondary failure, fail-closed, fusion fallback, active
   model, and the last stable reason code remain visible through additive
   telemetry properties without changing `search(query, top_k)`.
6. Fallback hits retain the fallback retriever's provenance; evaluation must
   not report Secondary/fallback output as a healthy Primary baseline.
7. Errors and logs must not include API keys, raw credentials, raw queries,
   full prompts, raw exception details, or document bodies.

The final controlled-error/not-found decision remains outside this protocol;
the Retriever only returns evidence or an empty result.

## Compatibility policy

- Additive optional metadata may be introduced without changing the major
  contract version.
- Removing fields, changing snippet format, weakening empty-query behavior,
  changing best-first ordering, or allowing more than `top_k` results requires
  a major contract version and migration plan.
- Future ACL-aware retrieval should add a request object plus a compatibility
  adapter; the current `search(query, top_k)` entry point remains available
  until all existing consumers migrate.

## Verification

Run the complete test suite and the explicit contract gate:

```bash
venv/bin/python -m unittest discover -s tests -v
venv/bin/python -m unittest tests.test_retriever_contract -v
```

Every new Retriever implementation must be added to the shared contract test
matrix before it can become a factory mode.
