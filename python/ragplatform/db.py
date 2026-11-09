"""Tenant-scoped database access.

Every query runs inside a transaction that first sets two transaction-local
settings, which the Row-Level Security policies in db/init.sql read:

    app.current_tenant  -> which tenant's rows are visible
    app.current_roles   -> which role-restricted documents are visible

`set_config(name, value, true)` is used instead of `SET LOCAL` so the value is
bound as a parameter and cannot be used for SQL injection.
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Iterator, Sequence

import psycopg
from psycopg_pool import ConnectionPool

from .config import get_settings

SYSTEM_ROLE = "__system__"
_TENANT_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_ROLE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")

_pool: ConnectionPool | None = None


def validate_tenant_id(tenant_id: str) -> str:
    if not tenant_id or not _TENANT_RE.match(tenant_id):
        raise ValueError("invalid tenant id")
    return tenant_id


def sanitize_roles(roles: Sequence[str]) -> list[str]:
    """Drop empty / malformed roles and the reserved system marker."""
    clean = []
    for role in roles:
        role = role.strip()
        if role and role != SYSTEM_ROLE and _ROLE_RE.match(role):
            clean.append(role)
    return clean


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(get_settings().database_url, min_size=1, max_size=10, open=True)
    return _pool


@contextmanager
def tenant_session(
    tenant_id: str,
    roles: Sequence[str] = (),
    *,
    system: bool = False,
    pool: ConnectionPool | None = None,
) -> Iterator[psycopg.Connection]:
    """Yield a connection inside a transaction scoped to one tenant.

    `system=True` is reserved for the trusted ingestion worker: it can see
    role-restricted rows of *its own tenant* (it still cannot cross tenants).
    """
    validate_tenant_id(tenant_id)
    roles_value = SYSTEM_ROLE if system else ",".join(sanitize_roles(roles))
    with (pool or get_pool()).connection() as conn:
        with conn.transaction():
            conn.execute("SELECT set_config('app.current_tenant', %s, true)", (tenant_id,))
            conn.execute("SELECT set_config('app.current_roles', %s, true)", (roles_value,))
            yield conn


def vector_literal(vec: Sequence[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"
