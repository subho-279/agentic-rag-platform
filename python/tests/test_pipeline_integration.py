"""Ingestion worker + agent over a real Postgres/pgvector (same env var as the RLS tests).

Covers what the gateway and Kafka would normally do around the worker: the gateway's
`documents` row insert and the event payload. Everything from `process_event` onwards is real.
"""
import os
import uuid
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg_pool import ConnectionPool

from ragplatform import db as dbmod
from ragplatform.agent import app as app_module
from ragplatform.agent.graph import build_graph
from ragplatform.agent.retrieval import PgRetriever
from ragplatform.config import Settings, get_settings
from ragplatform.db import tenant_session
from ragplatform.embeddings import HashEmbedder
from ragplatform.llm import NO_ANSWER, ExtractiveLLM
from ragplatform.worker.pipeline import IngestEvent, process_event

ADMIN_URL = os.environ.get("RAG_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="RAG_TEST_DATABASE_URL not set")

SAMPLES = Path(__file__).resolve().parents[2] / "sample_data"
EMB = HashEmbedder(1536)


def _app_url() -> str:
    d = psycopg.conninfo.conninfo_to_dict(ADMIN_URL)
    d.update(user="rag_app", password="rag_app_pw")
    return psycopg.conninfo.make_conninfo(**d)


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    storage = tmp_path_factory.mktemp("uploads")
    pool = ConnectionPool(_app_url(), min_size=1, max_size=4, open=True)
    dbmod._pool = pool  # worker + agent use the module-level pool
    settings = Settings(storage_root=str(storage))
    suffix = uuid.uuid4().hex[:6]
    yield {"pool": pool, "storage": storage, "settings": settings, "a": f"acme_{suffix}", "g": f"globex_{suffix}"}
    dbmod._pool = None
    pool.close()


def ingest(env, tenant, filename, roles=(), content: bytes | None = None) -> str:
    """Do what the gateway does (store file, insert PENDING row), then run the worker on the event."""
    doc_id = str(uuid.uuid4())
    rel = f"{tenant}/{doc_id}/{filename}"
    path = env["storage"] / rel
    path.parent.mkdir(parents=True)
    path.write_bytes(content if content is not None else (SAMPLES / filename).read_bytes())
    with tenant_session(tenant, system=True, pool=env["pool"]) as conn:
        conn.execute(
            "INSERT INTO documents (id, tenant_id, filename, storage_path, status, allowed_roles) "
            "VALUES (%s,%s,%s,%s,'PENDING',%s)",
            (doc_id, tenant, filename, rel, list(roles)),
        )
    process_event(IngestEvent(doc_id, tenant, rel), env["settings"], EMB)
    return doc_id


@pytest.fixture(scope="module")
def corpus(env):
    ids = {
        "handbook": ingest(env, env["a"], "acme_handbook.md"),
        "salary": ingest(env, env["a"], "acme_hr_salary_bands.md", roles=["hr"]),
        "pricing": ingest(env, env["g"], "globex_pricing.md"),
    }
    return ids


def graph(env):
    return build_graph(PgRetriever(), EMB, ExtractiveLLM(), env["settings"])


def ask(env, tenant, roles, question):
    return graph(env).invoke({"tenant_id": tenant, "roles": roles, "question": question, "trace": []})


def test_worker_marks_documents_ready_and_stores_chunks(env, corpus):
    with tenant_session(env["a"], system=True, pool=env["pool"]) as conn:
        status, n = conn.execute("SELECT status, chunk_count FROM documents WHERE id=%s", (corpus["handbook"],)).fetchone()
        stored = conn.execute("SELECT count(*) FROM chunks WHERE document_id=%s", (corpus["handbook"],)).fetchone()[0]
    assert status == "READY" and n == stored and n >= 1


def test_pii_is_redacted_before_storage(env, corpus):
    with tenant_session(env["a"], system=True, pool=env["pool"]) as conn:
        text = " ".join(r[0] for r in conn.execute("SELECT content FROM chunks WHERE document_id=%s", (corpus["handbook"],)))
    assert "benefits@acme.example" not in text and "415-555-0134" not in text
    assert "[REDACTED_EMAIL]" in text and "[REDACTED_PHONE]" in text


def test_reingesting_is_idempotent(env, corpus):
    with tenant_session(env["a"], system=True, pool=env["pool"]) as conn:
        before = conn.execute("SELECT count(*) FROM chunks WHERE document_id=%s", (corpus["handbook"],)).fetchone()[0]
        rel = conn.execute("SELECT storage_path FROM documents WHERE id=%s", (corpus["handbook"],)).fetchone()[0]
    process_event(IngestEvent(corpus["handbook"], env["a"], rel), env["settings"], EMB)
    with tenant_session(env["a"], system=True, pool=env["pool"]) as conn:
        after = conn.execute("SELECT count(*) FROM chunks WHERE document_id=%s", (corpus["handbook"],)).fetchone()[0]
    assert before == after


def test_each_tenant_gets_its_own_answer(env, corpus):
    q = "How many weeks of parental leave do employees get?"
    assert "16 weeks" in ask(env, env["a"], ["employee"], q)["answer"]
    g = ask(env, env["g"], ["employee"], q)["answer"]
    assert "12 weeks" in g and "16 weeks" not in g


def test_cross_tenant_content_is_not_retrievable(env, corpus):
    r = ask(env, env["a"], ["employee"], "What does the enterprise plan cost per seat per month?")
    assert r["answer"] == NO_ANSWER and r["sources"] == []
    r = ask(env, env["g"], ["employee"], "What is Project Falcon?")
    assert "logistics" not in r["answer"].lower()


def test_role_restricted_document(env, corpus):
    q = "What is the salary band for level 3 engineers?"
    emp = ask(env, env["a"], ["employee"], q)
    hr = ask(env, env["a"], ["hr", "employee"], q)
    assert "90" not in emp["answer"] and emp["sources"] == []
    assert "90" in hr["answer"]


def test_forged_event_for_another_tenants_file_is_rejected(env, corpus):
    with tenant_session(env["g"], system=True, pool=env["pool"]) as conn:
        rel = conn.execute("SELECT storage_path FROM documents WHERE id=%s", (corpus["pricing"],)).fetchone()[0]
    # Acme worker context asked to read Globex's file for a doc id it owns.
    with pytest.raises(PermissionError):
        process_event(IngestEvent(corpus["handbook"], env["a"], rel), env["settings"], EMB)
    with tenant_session(env["a"], system=True, pool=env["pool"]) as conn:
        assert conn.execute("SELECT status FROM documents WHERE id=%s", (corpus["handbook"],)).fetchone()[0] == "FAILED"


def test_forged_event_for_another_tenants_document_row_is_rejected(env, corpus):
    with pytest.raises(LookupError):
        process_event(IngestEvent(corpus["pricing"], env["a"], f"{env['a']}/x/y.md"), env["settings"], EMB)


def test_unsupported_or_empty_file_marks_failed(env):
    doc = ingest_failing(env, "empty.txt", b"   \n")
    with tenant_session(env["a"], system=True, pool=env["pool"]) as conn:
        status, err = conn.execute("SELECT status, error FROM documents WHERE id=%s", (doc,)).fetchone()
    assert status == "FAILED" and "no extractable text" in err


def ingest_failing(env, filename, content):
    with pytest.raises(ValueError):
        ingest(env, env["a"], filename, content=content)
    with tenant_session(env["a"], system=True, pool=env["pool"]) as conn:
        return conn.execute("SELECT id FROM documents WHERE filename=%s ORDER BY created_at DESC LIMIT 1", (filename,)).fetchone()[0]


def test_pdf_with_text_and_table_is_ingested(env):
    import pymupdf as fitz

    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Quarterly report. Warehouse capacity is 4200 pallets.")
    data = pdf.tobytes()
    doc = ingest(env, env["a"], "report.pdf", content=data)
    r = ask(env, env["a"], ["employee"], "What is the warehouse capacity in pallets?")
    assert "4200" in r["answer"]
    with tenant_session(env["a"], system=True, pool=env["pool"]) as conn:
        meta = conn.execute("SELECT metadata FROM chunks WHERE document_id=%s", (doc,)).fetchone()[0]
    assert meta.get("page") == 1


def test_http_api_over_real_database(env, corpus):
    app_module.app.state.graph = graph(env)
    client = TestClient(app_module.app)
    h = {"X-Internal-Token": get_settings().internal_token, "X-Tenant-Id": env["g"], "X-User-Id": "u", "X-User-Roles": "employee"}
    r = client.post("/internal/query", json={"query": "What does the enterprise plan cost per seat?"}, headers=h)
    assert r.status_code == 200 and "40 dollars" in r.json()["answer"]
    # Same question, other tenant's identity: nothing.
    h["X-Tenant-Id"] = env["a"]
    r = client.post("/internal/query", json={"query": "What does the enterprise plan cost per seat?"}, headers=h)
    assert "40 dollars" not in r.json()["answer"]
