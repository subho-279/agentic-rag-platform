"""FastAPI surface of the agentic core. Reachable only from the gateway (shared internal token)."""
from __future__ import annotations

import hmac
import json
from contextlib import asynccontextmanager
from typing import Iterator

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..config import get_settings
from ..db import sanitize_roles, validate_tenant_id
from ..embeddings import build_embedder
from ..llm import build_llm
from .graph import build_graph
from .guard import MAX_QUERY_CHARS
from .retrieval import PgRetriever


class QueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)


class Principal(BaseModel):
    tenant_id: str
    user_id: str
    roles: list[str]


def get_principal(
    x_internal_token: str = Header(default=""),
    x_tenant_id: str = Header(default=""),
    x_user_id: str = Header(default=""),
    x_user_roles: str = Header(default=""),
) -> Principal:
    # Identity comes from headers set by the gateway after JWT validation, so first prove the caller IS the gateway.
    if not hmac.compare_digest(x_internal_token.encode(), get_settings().internal_token.encode()):
        raise HTTPException(status_code=401, detail="invalid internal token")
    try:
        tenant = validate_tenant_id(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid tenant")
    return Principal(tenant_id=tenant, user_id=x_user_id[:128], roles=sanitize_roles(x_user_roles.split(",")))


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.graph = build_graph(PgRetriever(), build_embedder(settings), build_llm(settings), settings)
    yield


app = FastAPI(title="Agentic RAG core", lifespan=lifespan)


def _initial_state(p: Principal, query: str) -> dict:
    return {"tenant_id": p.tenant_id, "roles": p.roles, "question": query.strip(), "trace": []}


def _result(state: dict) -> dict:
    return {
        "answer": state.get("answer", ""),
        "sources": state.get("sources", []),
        "blocked": bool(state.get("blocked")),
        "attempts": state.get("attempt", 0),
        "trace": state.get("trace", []),
    }


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/internal/query")
def query(req: QueryRequest, p: Principal = Depends(get_principal)) -> dict:
    final = app.state.graph.invoke(_initial_state(p, req.query))
    return _result(final)


@app.post("/internal/query/stream")
def query_stream(req: QueryRequest, p: Principal = Depends(get_principal)) -> StreamingResponse:
    graph = app.state.graph

    def events() -> Iterator[str]:
        state: dict = {}
        try:
            for update in graph.stream(_initial_state(p, req.query), stream_mode="updates"):
                for node, delta in update.items():
                    state.update(delta or {})
                    yield _sse("status", {"node": node})
            result = _result(state)
            words = result["answer"].split(" ")
            for i in range(0, len(words), 4):
                yield _sse("token", {"text": " ".join(words[i : i + 4]) + " "})
            yield _sse("sources", {"sources": result["sources"]})
            yield _sse("done", {"blocked": result["blocked"], "attempts": result["attempts"]})
        except Exception:
            yield _sse("error", {"message": "internal error"})

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
