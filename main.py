"""Entry point for the Agentic RAG pipeline.

Usage:
    python main.py "What is the policy on international travel?"   # single query
    python main.py                                                  # interactive loop

Prints three clearly separated stages — user query, retrieved snippets,
final answer — so every run shows evidence that retrieval actually
happened before generation.
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from langgraph.graph.state import CompiledStateGraph

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


def run_query(graph: CompiledStateGraph, query: str) -> None:
    """Run one query through the pipeline and print the three-stage output."""
    print(BANNER)
    print("[1] USER QUERY")
    print(f"    {query}")
    print(DIVIDER)

    result = graph.invoke({"query": query, "snippets": [], "report": ""})

    print("[2] RETRIEVED SNIPPETS  (Data Retriever Agent -> tool call)")
    if result["snippets"]:
        for i, snippet in enumerate(result["snippets"], start=1):
            title, _, body = snippet.partition("\n")
            preview = " ".join(body.split())[:SNIPPET_PREVIEW_CHARS]
            print(f"    ({i}) {title} {preview}...")
    else:
        print("    (none — no chunk cleared the relevance threshold)")
    print(DIVIDER)

    print("[3] FINAL ANSWER  (Report Generator Agent)")
    for line in result["report"].splitlines():
        print(f"    {line}")
    print(BANNER)


def main() -> None:
    """Parse the CLI, build the graph once, and dispatch queries."""
    require_api_key()
    graph = build_graph()

    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:]).strip()
        if not query:
            sys.exit('Usage: python main.py "<your question>"')
        run_query(graph, query)
        return

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
