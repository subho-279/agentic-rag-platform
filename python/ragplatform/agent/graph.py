"""LangGraph agent: guard -> retrieve -> grade -> (rewrite -> retrieve)* -> generate -> output guard.

    START -> input_guard --blocked--> refuse -> END
                 |
                 v
             retrieve -> grade --relevant--------------------> generate -> output_guard -> END
                 ^          |
                 |          +--weak & attempts left--> rewrite
                 +--------------------------------------------+
                            +--weak & attempts exhausted----> generate (will say "not found")

The tenant and roles live in graph state, set once by the API layer from the
gateway-verified identity. No node takes them from the user's query.
"""
from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from ..config import Settings
from ..embeddings import Embedder
from ..llm import LLM, NO_ANSWER
from .guard import InputGuard, OutputGuard
from .retrieval import Hit, Retriever


class AgentState(TypedDict, total=False):
    tenant_id: str
    roles: list[str]
    question: str
    current_query: str
    attempt: int
    hits: list[Hit]
    relevant: list[Hit]
    best_score: float
    answer: str
    blocked: bool
    reason: str
    sources: list[dict[str, Any]]
    trace: list[str]


def build_graph(
    retriever: Retriever,
    embedder: Embedder,
    llm: LLM,
    settings: Settings,
    input_guard: InputGuard | None = None,
    output_guard: OutputGuard | None = None,
):
    input_guard = input_guard or InputGuard()
    output_guard = output_guard or OutputGuard(settings.guard_blacklist)

    def _trace(state: AgentState, msg: str) -> list[str]:
        return [*state.get("trace", []), msg]

    def guard_in(state: AgentState) -> AgentState:
        verdict = input_guard.check(state["question"])
        if not verdict.ok:
            return {"blocked": True, "reason": verdict.reason, "trace": _trace(state, f"input_guard: blocked ({verdict.reason})")}
        return {"blocked": False, "current_query": state["question"], "attempt": 0, "trace": _trace(state, "input_guard: ok")}

    def refuse(state: AgentState) -> AgentState:
        return {"answer": "I can't help with that request.", "sources": [], "trace": _trace(state, "refuse")}

    def retrieve(state: AgentState) -> AgentState:
        query = state["current_query"]
        vec = embedder.embed([query])[0]
        hits = retriever.search(state["tenant_id"], state.get("roles", []), vec, settings.retrieval_top_k)
        best = max((h.score for h in hits), default=0.0)
        return {
            "hits": hits,
            "best_score": best,
            "trace": _trace(state, f"retrieve: attempt={state['attempt']} hits={len(hits)} best={best:.2f} query={query!r}"),
        }

    def grade(state: AgentState) -> AgentState:
        # Keep chunks above the threshold, dropping exact duplicates (the same document uploaded twice).
        # Hits arrive best-first, so the highest-scoring copy is the one kept.
        seen: set[str] = set()
        relevant: list[Hit] = []
        for h in state["hits"]:
            key = " ".join(h.content.split())
            if h.score < settings.similarity_threshold or key in seen:
                continue
            seen.add(key)
            relevant.append(h)
        return {"relevant": relevant, "trace": _trace(state, f"grade: relevant={len(relevant)}/{len(state['hits'])}")}

    def rewrite(state: AgentState) -> AgentState:
        attempt = state["attempt"] + 1
        new_query = llm.rewrite(state["question"], attempt)
        return {"attempt": attempt, "current_query": new_query, "trace": _trace(state, f"rewrite #{attempt}: {new_query!r}")}

    def generate(state: AgentState) -> AgentState:
        relevant = state.get("relevant", [])
        if not relevant:
            return {"answer": NO_ANSWER, "sources": [], "trace": _trace(state, "generate: no relevant context")}
        answer = llm.answer(state["question"], [h.content for h in relevant])
        sources = [
            {"ref": i, "document_id": h.document_id, "filename": h.filename, "score": round(h.score, 3)}
            for i, h in enumerate(relevant, start=1)
        ]
        return {"answer": answer, "sources": sources, "trace": _trace(state, "generate: answered")}

    def guard_out(state: AgentState) -> AgentState:
        verdict, cleaned = output_guard.check(
            state["answer"], [h.tenant_id for h in state.get("relevant", [])], state["tenant_id"]
        )
        if not verdict.ok:
            return {
                "answer": "I can't share that answer.",
                "sources": [],
                "blocked": True,
                "reason": verdict.reason,
                "trace": _trace(state, f"output_guard: blocked ({verdict.reason})"),
            }
        return {"answer": cleaned, "trace": _trace(state, "output_guard: ok")}

    def after_guard(state: AgentState) -> str:
        return "refuse" if state.get("blocked") else "retrieve"

    def after_grade(state: AgentState) -> str:
        if state.get("relevant"):
            return "generate"
        return "rewrite" if state["attempt"] < settings.max_rewrites else "generate"

    g = StateGraph(AgentState)
    g.add_node("input_guard", guard_in)
    g.add_node("refuse", refuse)
    g.add_node("retrieve", retrieve)
    g.add_node("grade", grade)
    g.add_node("rewrite", rewrite)
    g.add_node("generate", generate)
    g.add_node("output_guard", guard_out)

    g.add_edge(START, "input_guard")
    g.add_conditional_edges("input_guard", after_guard, {"refuse": "refuse", "retrieve": "retrieve"})
    g.add_edge("refuse", END)
    g.add_edge("retrieve", "grade")
    g.add_conditional_edges("grade", after_grade, {"generate": "generate", "rewrite": "rewrite"})
    g.add_edge("rewrite", "retrieve")
    g.add_edge("generate", "output_guard")
    g.add_edge("output_guard", END)
    return g.compile()