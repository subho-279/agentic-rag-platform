"""Vector retrieval, always executed inside a tenant-scoped transaction."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from ..db import tenant_session, vector_literal


@dataclass(frozen=True)
class Hit:
    chunk_id: int
    document_id: str
    filename: str
    content: str
    tenant_id: str
    score: float  # cosine similarity in [-1, 1]


class Retriever(Protocol):
    def search(self, tenant_id: str, roles: Sequence[str], query_vec: Sequence[float], k: int) -> list[Hit]: ...


class PgRetriever:
    """Two independent layers keep results inside the tenant:

    1. Row-Level Security (policies read app.current_tenant / app.current_roles, set by tenant_session)
    2. An explicit `c.tenant_id = %s` predicate, so a misconfigured role or a dropped policy
       still cannot return another tenant's rows.
    """

    def search(self, tenant_id: str, roles: Sequence[str], query_vec: Sequence[float], k: int) -> list[Hit]:
        vec = vector_literal(query_vec)
        with tenant_session(tenant_id, roles) as conn:
            rows = conn.execute(
                "SELECT c.id, c.document_id, d.filename, c.content, c.tenant_id, "
                "       1 - (c.embedding <=> %s::vector) AS score "
                "FROM chunks c JOIN documents d ON d.id = c.document_id "
                "WHERE c.tenant_id = %s "
                "ORDER BY c.embedding <=> %s::vector "
                "LIMIT %s",
                (vec, tenant_id, vec, k),
            ).fetchall()
        return [Hit(r[0], str(r[1]), r[2], r[3], r[4], float(r[5])) for r in rows]
