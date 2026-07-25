"""Agentic RAG system: an agentic retrieval pipeline built on LangGraph.

Packages:
    - ``src.tools``  — custom RAG retrieval tool over ``knowledge_base.txt``
    - ``src.agents`` — Router, Data Retriever, Query Rewriter, and Report
      Generator agent nodes
    - ``src.graph``  — StateGraph wiring (routing + bounded retry loop)
    - ``src.config`` — centralized, environment-overridable configuration
"""
