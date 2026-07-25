"""LangGraph wiring for the sequential two-agent pipeline.

Orchestration pattern: sequential handoff through shared state.
The Data Retriever writes ``snippets`` into ``PipelineState``; LangGraph
then follows the retriever -> generator edge, handing that state to the
Report Generator, which writes the final ``report``.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from typing_extensions import TypedDict

from src.agents.reporter import generator_node
from src.agents.retriever import retriever_node


class PipelineState(TypedDict):
    """Shared state carried across the pipeline — the whole data flow."""

    query: str            # user question (input)
    snippets: list[str]   # Data Retriever output -> handoff to the Generator
    report: str           # Report Generator output (final answer)


def build_graph() -> CompiledStateGraph:
    """Compile the sequential pipeline: Data Retriever -> Report Generator."""
    builder = StateGraph(PipelineState)
    builder.add_node("data_retriever", retriever_node)
    builder.add_node("report_generator", generator_node)
    builder.add_edge(START, "data_retriever")
    # <-- sequential handoff: the retriever's snippets travel to the
    #     generator via shared state. This edge IS the orchestration pattern.
    builder.add_edge("data_retriever", "report_generator")
    builder.add_edge("report_generator", END)
    return builder.compile()
