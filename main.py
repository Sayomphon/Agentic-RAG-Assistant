"""Entry point for the Agentic RAG pipeline.

Usage:
    python main.py "What is the policy on international travel?"   # single query
    python main.py                                                  # interactive loop

Prints clearly separated stages — user query, chosen route, retrieved
snippets (with every search attempt), final answer — so every run shows
the agent's decisions and evidence before generation.

Provider failures are reported as one actionable line and a non-zero exit
code, never a traceback; set ``AGENTIC_RAG_DEBUG=1`` to re-raise instead.
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from langgraph.graph.state import CompiledStateGraph
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAIError,
    RateLimitError,
)

from src.graph import build_graph

BANNER = "=" * 60
DIVIDER = "-" * 60
SNIPPET_PREVIEW_CHARS = 90  # keep stage [2] readable and screenshot-friendly


def require_api_key() -> None:
    """Load .env and exit with a clear message if the API key is missing."""
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        sys.exit(
            "ERROR: OPENAI_API_KEY is not set.\n"
            "Copy .env.example to .env and add your OpenAI API key."
        )


def provider_error_message(exc: OpenAIError) -> str:
    """One actionable line per failure mode.

    The text is written here rather than interpolated from the exception:
    a provider error's string form carries request metadata (and can echo
    the prompt), none of which belongs on a user's terminal. Only the
    status code and request id are passed through — the two fields the
    provider's own support flow asks for.
    """
    if isinstance(exc, AuthenticationError):
        return (
            "The provider rejected the credential. Check OPENAI_API_KEY in "
            ".env — it must be active and allowed to use MODEL_NAME."
        )
    if isinstance(exc, RateLimitError):
        return "Rate limit or quota reached. Wait and retry, or check billing limits."
    # APITimeoutError subclasses APIConnectionError, so it is checked first.
    if isinstance(exc, APITimeoutError):
        return "The provider did not respond in time. Retry the query."
    if isinstance(exc, APIConnectionError):
        return "Could not reach the provider. Check network access and retry."
    if isinstance(exc, APIStatusError):
        request = f", request {exc.request_id}" if exc.request_id else ""
        side = "on the provider's side" if exc.status_code >= 500 else "in the request"
        return (
            f"The provider returned HTTP {exc.status_code} ({side}{request}). "
            "Retry shortly; retrieval alone can be checked offline with "
            "`python -m src.tools.retrieval`."
        )
    return "The provider call failed. Retry, or re-run with AGENTIC_RAG_DEBUG=1."


def run_query(graph: CompiledStateGraph, query: str) -> bool:
    """Run one query through the pipeline and print the staged output.

    Returns:
        ``True`` when the pipeline produced an answer, ``False`` when the
        model provider failed — the caller turns that into an exit code.
    """
    print(BANNER)
    print("[1] USER QUERY")
    print(f"    {query}")
    print(DIVIDER)

    try:
        result = graph.invoke({"query": query, "snippets": [], "report": ""})
    except OpenAIError as exc:
        if os.getenv("AGENTIC_RAG_DEBUG"):
            raise
        print(f"ERROR: {provider_error_message(exc)}", file=sys.stderr)
        print(BANNER)
        return False
    route = result.get("route", "kb_query")

    print(f"[2] ROUTE  (Router Agent) -> {route}")
    if route == "direct":
        print("    (small talk / meta question — knowledge base skipped)")
        print(DIVIDER)
        print("[3] FINAL ANSWER  (Direct Responder)")
        for line in result["report"].splitlines():
            print(f"    {line}")
        print(BANNER)
        return True
    print(DIVIDER)

    print("[3] RETRIEVED SNIPPETS  (Data Retriever Agent -> tool call)")
    attempts = result.get("search_attempts", [])
    if attempts:
        # Every attempt before the last returned zero snippets by
        # construction — a hit ends the retry loop immediately.
        for i, attempt in enumerate(attempts, start=1):
            found = len(result["snippets"]) if i == len(attempts) else 0
            print(f'    attempt {i}: "{attempt}" -> {found} result(s)')
    if result["snippets"]:
        for i, snippet in enumerate(result["snippets"], start=1):
            title, _, body = snippet.partition("\n")
            preview = " ".join(body.split())[:SNIPPET_PREVIEW_CHARS]
            print(f"    ({i}) {title} {preview}...")
    else:
        print("    (none — no chunk cleared the relevance threshold)")
    print(DIVIDER)

    print("[4] FINAL ANSWER  (Report Generator Agent)")
    for line in result["report"].splitlines():
        print(f"    {line}")
    print(BANNER)
    return True


def main() -> None:
    """Parse the CLI, build the graph once, and dispatch queries.

    A provider failure exits non-zero in single-query mode (so scripts and
    CI can tell a failed run from a not-found answer) but keeps the
    interactive loop alive — there the next query is the retry.
    """
    require_api_key()
    graph = build_graph()

    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:]).strip()
        if not query:
            sys.exit('Usage: python main.py "<your question>"')
        sys.exit(0 if run_query(graph, query) else 1)

    print("Agentic RAG — interactive mode. Empty line, 'exit', or Ctrl-C to quit.")
    while True:
        try:
            query = input("\nquery> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if query.lower() in {"", "exit", "quit"}:
            break
        run_query(graph, query)


if __name__ == "__main__":
    main()
