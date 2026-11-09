"""Proves database-level tenant isolation. Needs Postgres+pgvector with db/init.sql applied.

    RAG_TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ragdb pytest tests/test_rls_integration.py

The test connects as the superuser only to seed data, then uses the unprivileged
`rag_app` role (the one the services use) for every assertion.
"""
import os
import uuid

import psycopg
import pytest
from psycopg_pool import ConnectionPool

from ragplatform.agent.retrieval import PgRetriever
from ragplatform.db import tenant_session, vector_literal
from ragplatform.embeddings import HashEmbedder

ADMIN_URL = os.environ.get("RAG_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="RAG_TEST_DATABASE_URL not set")

EMB = HashEmbedder(1536)


def app_url() -> str:
    base = psycopg.conninfo.conninfo_to_dict(ADMIN_URL)
    base.update(user="rag_app", password="rag_app_pw")
    return psycopg.conninfo.make_conninfo(**base)


@pytest.fixture(scope="module")
def pool():
    p = ConnectionPool(app_url(), min_size=1, max_size=4, open=True)
    yield p
    p.close()


@pytest.fixture(scope="module")
def seeded(pool):
    """Seed two tenants (+ one role-restricted doc) through the app role itself."""
    suffix = uuid.uuid4().hex[:6]
    a, b = f"tenant_a_{suffix}", f"tenant_b_{suffix}"
    docs = {}
    for tenant, fname, text, roles in [
        (a, "a_public.md", "Acme parental leave is sixteen weeks.", []),
        (a, "a_hr.md", "Acme salary band for engineers is confidential.", ["hr"]),
        (b, "b_public.md", "Globex parental leave is twelve weeks.", []),
    ]:
        doc_id = str(uuid.uuid4())
        docs[fname] = doc_id
        with tenant_session(tenant, system=True, pool=pool) as conn:
            conn.execute(
                "INSERT INTO documents (id, tenant_id, filename, storage_path, status, allowed_roles) "
                "VALUES (%s,%s,%s,%s,'READY',%s)",
                (doc_id, tenant, fname, f"{tenant}/{doc_id}/{fname}", roles),
            )
            conn.execute(
                "INSERT INTO chunks (tenant_id, document_id, chunk_index, content, allowed_roles, embedding) "
                "VALUES (%s,%s,0,%s,%s,%s::vector)",
                (tenant, doc_id, text, roles, vector_literal(EMB.embed([text])[0])),
            )
    return a, b


def test_tenant_only_sees_own_rows(pool, seeded):
    a, b = seeded
    with tenant_session(a, pool=pool) as conn:
        tenants = {r[0] for r in conn.execute("SELECT DISTINCT tenant_id FROM chunks")}
    assert tenants == {a}


def test_milestone_1_tenant_a_gets_empty_result_for_tenant_b_content(pool, seeded):
    a, _ = seeded
    with tenant_session(a, ["hr"], pool=pool) as conn:
        rows = conn.execute("SELECT 1 FROM chunks WHERE content ILIKE '%%Globex%%'").fetchall()
    assert rows == []


def test_no_tenant_set_means_no_rows(pool, seeded):
    with pool.connection() as conn:
        assert conn.execute("SELECT count(*) FROM chunks").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM documents").fetchone()[0] == 0


def test_even_a_wrong_sql_filter_cannot_cross_tenants(pool, seeded):
    a, b = seeded
    with tenant_session(a, pool=pool) as conn:
        rows = conn.execute("SELECT 1 FROM chunks WHERE tenant_id = %s", (b,)).fetchall()
    assert rows == []


def test_cannot_insert_rows_for_another_tenant(pool, seeded):
    a, b = seeded
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with tenant_session(a, system=True, pool=pool) as conn:
            conn.execute(
                "INSERT INTO documents (id, tenant_id, filename, storage_path) VALUES (%s,%s,'x','x')",
                (str(uuid.uuid4()), b),
            )


def test_role_restricted_documents(pool, seeded):
    a, _ = seeded
    q = EMB.embed(["salary band for engineers"])[0]
    retr = PgRetriever()
    import ragplatform.agent.retrieval as r
    import ragplatform.db as dbmod

    dbmod._pool = pool  # PgRetriever uses the module-level pool
    try:
        employee = retr.search(a, ["employee"], q, 5)
        hr = retr.search(a, ["hr"], q, 5)
    finally:
        dbmod._pool = None
    assert all("salary" not in h.content for h in employee)
    assert any("salary" in h.content for h in hr)
    assert {h.tenant_id for h in employee + hr} == {a}
