"""Streamlit UI for the Agentic RAG pipeline — presentation layer only.

This file renders what the core already produces; it contains no retrieval
or generation logic. It touches exactly two ``src`` entry points:

    - ``build_graph()``   -> the same two-agent LangGraph the CLI runs
    - ``get_retriever()`` -> the same factory the tool layer uses, warmed
                             per mode so switching modes stays instant

Both are wrapped in ``st.cache_resource`` (the retriever keyed by mode) so
Streamlit's rerun-everything model never rebuilds an index or recompiles
the graph. Run with:  streamlit run app.py
"""

from __future__ import annotations

import html
import os
import time

import streamlit as st

from src.agents.reporter import NOT_FOUND_SENTENCE
from src.config import MODEL_NAME, SEARCH_MODE, TOP_K
from src.graph import build_graph
from src.retrievers import get_retriever

st.set_page_config(
    page_title="Agentic RAG Explorer",
    page_icon="🔎",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------- chrome ---
_CSS = """
<style>
:root { --accent:#3D63DD; --tc:#31333f; --sbg:#f0f2f6; }
@media (prefers-color-scheme: dark) { :root { --tc:#fafafa; --sbg:#262730; } }
.block-container, [data-testid="stMainBlockContainer"] { max-width:64rem; padding-top:2.6rem; }
#MainMenu, footer, [data-testid="stDecoration"] { visibility:hidden; }
.app-title { font-size:1.5rem; font-weight:700; letter-spacing:-.02em; margin:0; }
.app-sub { font-size:.9rem; color:color-mix(in srgb, var(--text-color, var(--tc)) 65%, transparent); margin:.2rem 0 1.1rem; }
.stage-head { display:flex; align-items:baseline; gap:.65rem; margin:1.7rem 0 .6rem; padding-bottom:.35rem; border-bottom:1px solid color-mix(in srgb, var(--text-color, var(--tc)) 12%, transparent); }
.stage-kicker { font-size:.7rem; font-weight:700; letter-spacing:.09em; white-space:nowrap; color:color-mix(in srgb, var(--accent) 70%, var(--text-color, var(--tc))); }
.stage-title { font-size:1.02rem; font-weight:650; }
.stage-sub { font-size:.78rem; color:color-mix(in srgb, var(--text-color, var(--tc)) 55%, transparent); }
.telemetry { display:flex; flex-wrap:wrap; gap:1.5rem; padding:.55rem .95rem; border:1px solid color-mix(in srgb, var(--text-color, var(--tc)) 13%, transparent); border-radius:.5rem; background:var(--secondary-background-color, var(--sbg)); }
.telemetry .t { display:flex; flex-direction:column; }
.telemetry .k { font-size:.63rem; font-weight:600; letter-spacing:.07em; text-transform:uppercase; color:color-mix(in srgb, var(--text-color, var(--tc)) 55%, transparent); }
.telemetry .v { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:.84rem; font-weight:600; }
details.snip { border:1px solid color-mix(in srgb, var(--text-color, var(--tc)) 13%, transparent); border-radius:.5rem; background:var(--secondary-background-color, var(--sbg)); margin-bottom:.45rem; overflow:hidden; }
details.snip summary { display:flex; align-items:center; gap:.6rem; padding:.5rem .85rem; cursor:pointer; list-style:none; }
details.snip summary::-webkit-details-marker { display:none; }
details.snip summary::after { content:"+"; font-family:ui-monospace,monospace; color:color-mix(in srgb, var(--text-color, var(--tc)) 45%, transparent); }
details.snip[open] summary::after { content:"−"; }
.snip-rank { font-family:ui-monospace,monospace; font-size:.72rem; font-weight:600; color:color-mix(in srgb, var(--text-color, var(--tc)) 50%, transparent); }
.snip-title { font-size:.88rem; font-weight:600; }
.snip-score { margin-left:auto; font-family:ui-monospace,monospace; font-size:.72rem; color:color-mix(in srgb, var(--text-color, var(--tc)) 55%, transparent); }
.badge { font-size:.62rem; font-weight:700; letter-spacing:.05em; padding:.13rem .5rem; border-radius:99px; white-space:nowrap; }
.badge-one { color:color-mix(in srgb, var(--text-color, var(--tc)) 75%, transparent); border:1px solid color-mix(in srgb, var(--text-color, var(--tc)) 30%, transparent); }
.badge-both { color:#fff; background:var(--accent); }
details.snip pre { margin:0; padding:.65rem .9rem .85rem; border-top:1px dashed color-mix(in srgb, var(--text-color, var(--tc)) 18%, transparent); font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:.76rem; line-height:1.6; white-space:pre-wrap; background:transparent; color:color-mix(in srgb, var(--text-color, var(--tc)) 85%, transparent); }
.empty { text-align:center; padding:1.5rem 1rem; border:1px dashed color-mix(in srgb, var(--text-color, var(--tc)) 25%, transparent); border-radius:.5rem; font-size:.88rem; color:color-mix(in srgb, var(--text-color, var(--tc)) 60%, transparent); background:var(--secondary-background-color, var(--sbg)); }
.empty b { display:block; font-size:.95rem; margin-bottom:.15rem; color:color-mix(in srgb, var(--text-color, var(--tc)) 80%, transparent); }
</style>
"""
st.markdown(_CSS, unsafe_allow_html=True)

# ------------------------------------------------------------ static copy ---
_MODES = ("keyword", "semantic", "hybrid")
_MODE_CAPTIONS = (
    "BM25 lexical ranking — exact-term matching with a title boost. "
    "Deterministic, offline, no API cost.",
    "OpenAI embeddings + cosine similarity — matches meaning even when the "
    "wording differs from the handbook.",
    "Runs both retrievers and merges ranks with Reciprocal Rank Fusion. "
    "Badges show which side found each snippet.",
)
# Expected ScoredChunk/retriever ``source`` labels per mode, used only to
# detect the factory's documented keyword fallback and surface it in the UI.
_MODE_SOURCE = {"keyword": "bm25", "semantic": "dense", "hybrid": "hybrid"}

_EXAMPLES = (
    ("International travel", "What is the policy on international travel?"),
    ("Work from home", "Can I work from home every day?"),
    ("Mileage claim", "How much can I claim when I use my own car for a client visit?"),
    ("Thai query", "ลาบวชได้กี่วัน และต้องแจ้งล่วงหน้าอย่างไร?"),
    ("Not in KB", "What is the CEO's salary?"),
)

# ------------------------------------------------------- cached core hooks ---
@st.cache_resource(show_spinner=False)
def load_graph():
    """Compile the two-agent LangGraph once per server process."""
    return build_graph()


@st.cache_resource(show_spinner=False)
def load_retriever(mode: str):
    """Warm the retriever for ``mode`` once — cache key includes the mode,
    so switching modes builds each index at most once and reuses it after."""
    return get_retriever(mode)


# ------------------------------------------------------------- renderers ---
def _stage_head(number: int, title: str, sub: str) -> None:
    st.markdown(
        f'<div class="stage-head"><span class="stage-kicker">STAGE {number}</span>'
        f'<span class="stage-title">{title}</span>'
        f'<span class="stage-sub">{sub}</span></div>',
        unsafe_allow_html=True,
    )


def _badge(source: str) -> str:
    if "+" in source:
        return '<span class="badge badge-both">BM25 + EMBEDDINGS</span>'
    label = {"bm25": "BM25", "dense": "EMBEDDINGS"}.get(source, html.escape(source).upper())
    return f'<span class="badge badge-one">{label}</span>'


def _snippet_cards(hits) -> str:
    cards = []
    for rank, hit in enumerate(hits, start=1):
        cards.append(
            f'<details class="snip"{" open" if rank == 1 else ""}>'
            f'<summary><span class="snip-rank">{rank:02d}</span>'
            f'<span class="snip-title">{html.escape(hit.title)}</span>'
            f"{_badge(hit.source)}"
            f'<span class="snip-score">score {hit.score:.4f}</span></summary>'
            f"<pre>{html.escape(hit.text)}</pre></details>"
        )
    return "".join(cards)


def _telemetry(run: dict) -> str:
    timings = run["timings"]
    total = sum(timings.values())
    items = (
        ("mode", run["mode"]),
        ("model", run["model"]),
        ("top-k", str(run["top_k"])),
        ("snippets", str(len(run["snippets"]))),
        ("stage 1 · retrieve", f"{timings.get('retrieval', 0):.2f}s"),
        ("stage 2 · synthesize", f"{timings.get('synthesis', 0):.2f}s"),
        ("total", f"{total:.2f}s"),
    )
    spans = "".join(
        f'<div class="t"><span class="k">{k}</span><span class="v">{html.escape(v)}</span></div>'
        for k, v in items
    )
    return f'<div class="telemetry">{spans}</div>'


def render_run(run: dict) -> None:
    """Display one completed pipeline run: telemetry, evidence, answer."""
    st.markdown(f"##### “{run['query']}”")
    st.markdown(_telemetry(run), unsafe_allow_html=True)

    _stage_head(1, "Data Retriever Agent", "forced tool call → ranked evidence from the knowledge base")
    if run["search_query"] != run["query"]:
        st.caption(f'Agent reformulated the search as: “{run["search_query"]}”')
    if run["hits"]:
        st.markdown(_snippet_cards(run["hits"]), unsafe_allow_html=True)
    else:
        st.markdown(
            '<div class="empty"><b>No snippets cleared the relevance gates</b>'
            f"{run['mode']} mode found nothing relevant to this query, so the "
            "evidence set handed to Stage 2 was empty — by design, the "
            "generator then falls back deterministically instead of guessing.</div>",
            unsafe_allow_html=True,
        )

    _stage_head(2, "Report Generator Agent", "grounded synthesis — uses the snippets above and nothing else")
    with st.container(border=True):
        if run["report"].strip() == NOT_FOUND_SENTENCE:
            st.markdown(f"*{run['report']}*")
            st.caption(
                "Deterministic fallback: zero snippets were handed off, so this "
                "fixed sentence was returned without an LLM call."
                if not run["hits"]
                else "Prompt guardrail: the generator judged the retrieved "
                "snippets insufficient to answer this query."
            )
        else:
            st.markdown(run["report"])


# ------------------------------------------------------------ run driver ---
def execute(query: str, mode: str, top_k: int) -> dict | None:
    """Stream one query through the graph, narrating each stage live."""
    graph = load_graph()
    with st.spinner(f"Preparing the {mode} index…"):
        retriever = load_retriever(mode)
    if getattr(retriever, "SOURCE", "") != _MODE_SOURCE[mode]:
        st.warning(
            f"The **{mode}** index could not be built (embeddings unavailable), "
            "so retrieval fell back to **keyword / BM25** for this session. "
            "Check `OPENAI_API_KEY` and network access, then restart the app."
        )

    run = {
        "query": query, "mode": mode, "top_k": top_k, "model": MODEL_NAME,
        "snippets": [], "hits": [], "report": "", "search_query": query,
        "timings": {},
    }
    stage1 = st.status("**Stage 1 · Data Retriever** — choosing a search query and retrieving…", state="running")
    stage2 = None
    started = time.perf_counter()
    try:
        for update in graph.stream(
            {"query": query, "snippets": [], "report": "",
             "search_mode": mode, "top_k": top_k},
            stream_mode="updates",
        ):
            if "data_retriever" in update:
                run["timings"]["retrieval"] = time.perf_counter() - started
                run.update(update["data_retriever"] or {})
                stage1.update(
                    label=(f"**Stage 1 · Data Retriever** — {len(run['snippets'])} "
                           f"snippet(s) in {run['timings']['retrieval']:.1f}s"),
                    state="complete",
                )
                started = time.perf_counter()
                stage2 = st.status("**Stage 2 · Report Generator** — synthesizing the grounded answer…", state="running")
            elif "report_generator" in update:
                run["timings"]["synthesis"] = time.perf_counter() - started
                run.update(update["report_generator"] or {})
                if stage2 is not None:
                    stage2.update(
                        label=(f"**Stage 2 · Report Generator** — answered in "
                               f"{run['timings']['synthesis']:.1f}s"),
                        state="complete",
                    )
    except Exception as exc:  # noqa: BLE001 — surface any provider error readably
        for status in (stage1, stage2):
            if status is not None:
                status.update(state="error")
        st.error(f"**Pipeline failed** ({type(exc).__name__}): {str(exc)[:400]}")
        return None
    return run


# ------------------------------------------------------------------ page ---
state = st.session_state
state.setdefault("runs", [])
state.setdefault("active_run", None)

with st.sidebar:
    st.markdown("#### Retrieval settings")
    mode = st.radio(
        "Search mode",
        _MODES,
        index=_MODES.index(SEARCH_MODE) if SEARCH_MODE in _MODES else 0,
        format_func=str.capitalize,
        captions=_MODE_CAPTIONS,
    )
    top_k = st.slider("Top-k snippets", min_value=1, max_value=8, value=TOP_K,
                      help="Maximum snippets the Data Retriever may hand to the generator.")
    st.caption(
        "Settings apply to the next query. Indexes are cached per mode — the "
        "first semantic/hybrid query builds (or loads) the embedding index; "
        "after that, switching modes is instant."
    )

st.markdown('<p class="app-title">Agentic RAG Explorer</p>', unsafe_allow_html=True)
st.markdown(
    '<p class="app-sub">Two-agent LangGraph pipeline over the Siam Innovate employee '
    'handbook — a <b>Data Retriever</b> forced through a search tool, handing evidence '
    'to a <b>Report Generator</b> that answers from that evidence only.</p>',
    unsafe_allow_html=True,
)

if not os.getenv("OPENAI_API_KEY"):
    st.error(
        "**`OPENAI_API_KEY` is not set — both agents need the OpenAI API.**\n\n"
        "1. `cp .env.example .env`\n"
        "2. Put your key in `.env` (`OPENAI_API_KEY=sk-...`)\n"
        "3. Restart: `streamlit run app.py`"
    )
    st.stop()

with st.form("query_form", border=False):
    col_input, col_button = st.columns([5, 1], vertical_alignment="bottom")
    typed = col_input.text_input(
        "Question", placeholder="Ask the employee handbook anything…",
        label_visibility="collapsed",
    )
    submitted = col_button.form_submit_button("Search", type="primary", width="stretch")

query_to_run = typed.strip() if submitted and typed.strip() else None
example_cols = st.columns(len(_EXAMPLES))
for col, (label, example_query) in zip(example_cols, _EXAMPLES):
    if col.button(label, key=f"ex_{label}", help=example_query, width="stretch"):
        query_to_run = example_query

if submitted and not typed.strip() and query_to_run is None:
    st.warning("Type a question or pick an example.")

if query_to_run:
    finished = execute(query_to_run, mode, top_k)
    if finished is not None:
        state.runs.append(finished)
        state.active_run = len(state.runs) - 1

with st.sidebar:
    if state.runs:
        st.divider()
        st.markdown("#### History")
        for i in range(len(state.runs) - 1, -1, -1):
            past = state.runs[i]
            if st.button(
                past["query"][:48] + ("…" if len(past["query"]) > 48 else ""),
                key=f"hist_{i}", width="stretch",
                help=f"{past['query']}  ·  {past['mode']}, top_k={past['top_k']}",
            ):
                state.active_run = i

if state.runs and state.active_run is not None:
    render_run(state.runs[state.active_run])
else:
    st.markdown(
        '<div class="empty"><b>No queries yet</b>Ask a question or click an example '
        "above — each run shows the full pipeline: retrieved evidence with scores "
        "and provenance first, then the grounded answer.</div>",
        unsafe_allow_html=True,
    )
