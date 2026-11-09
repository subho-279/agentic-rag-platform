"""HTTP-level tests of the agent API using an in-memory retriever (no DB, no gateway)."""
import json

import pytest
from fastapi.testclient import TestClient

from ragplatform.agent import app as app_module
from ragplatform.agent.graph import build_graph
from ragplatform.config import get_settings
from ragplatform.embeddings import HashEmbedder
from ragplatform.llm import ExtractiveLLM
from ragplatform.worker.pipeline import IngestEvent

from test_graph import CORPUS, MemoryRetriever

TOKEN = get_settings().internal_token


@pytest.fixture
def client():
    retriever = MemoryRetriever(CORPUS)
    app_module.app.state.graph = build_graph(retriever, HashEmbedder(1536), ExtractiveLLM(), get_settings())
    app_module.app.state.retriever = retriever
    return TestClient(app_module.app)  # not used as a context manager, so the DB-backed lifespan is skipped


def headers(tenant="acme", roles="employee", token=TOKEN):
    return {"X-Internal-Token": token, "X-Tenant-Id": tenant, "X-User-Id": "u1", "X-User-Roles": roles}


def test_rejects_missing_or_wrong_internal_token(client):
    assert client.post("/internal/query", json={"query": "hi"}).status_code == 401
    assert client.post("/internal/query", json={"query": "hi"}, headers=headers(token="nope")).status_code == 401


def test_rejects_malformed_tenant(client):
    r = client.post("/internal/query", json={"query": "hi"}, headers=headers(tenant="x'; drop"))
    assert r.status_code == 400


def test_query_uses_tenant_from_header_only(client):
    r = client.post("/internal/query", json={"query": "How many weeks of parental leave?"}, headers=headers())
    assert r.status_code == 200 and "16 weeks" in r.json()["answer"]
    # A query that *names* another tenant still searches only the header's tenant.
    client.post("/internal/query", json={"query": "globex enterprise plan price"}, headers=headers())
    assert {t for t, _ in client.app.state.retriever.calls} == {"acme"}


def test_system_role_header_is_ignored(client):
    client.post("/internal/query", json={"query": "parental leave"}, headers=headers(roles="hr,__system__"))
    roles_seen = {r for _, roles in client.app.state.retriever.calls for r in roles}
    assert "__system__" not in roles_seen and "hr" in roles_seen


def test_sse_stream_emits_status_tokens_sources_done(client):
    with client.stream("POST", "/internal/query/stream", json={"query": "parental leave weeks"}, headers=headers()) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    events = [line.split(": ", 1)[1] for line in body.splitlines() if line.startswith("event: ")]
    assert events[0] == "status" and events[-1] == "done"
    assert "token" in events and "sources" in events
    answer = "".join(
        json.loads(block.split("data: ", 1)[1])["text"]
        for block in body.split("\n\n")
        if block.startswith("event: token")
    )
    assert "16 weeks" in answer


def test_ingest_event_validation():
    ok = IngestEvent.from_dict({"document_id": "d", "tenant_id": "acme", "file_path": "acme/d/a.md"})
    assert ok.tenant_id == "acme"
    with pytest.raises(ValueError):
        IngestEvent.from_dict({"document_id": "d", "tenant_id": "a b", "file_path": "x"})
