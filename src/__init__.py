"""Agentic RAG system: a sequential two-agent pipeline built on LangGraph.

Packages:
    - ``src.tools``  — custom RAG retrieval tool over knowledge_base.txt
    - ``src.agents`` — Data Retriever and Report Generator agent nodes
    - ``src.graph``  — StateGraph wiring (sequential handoff pipeline)
    - ``src.config`` — centralized, environment-overridable configuration
"""
