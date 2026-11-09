"""Runs scripts/demo.py unchanged against: fake gateway -> REAL agent (uvicorn, lifespan, LangGraph)
-> REAL Postgres/pgvector (RLS) + REAL Redis token bucket + REAL worker pipeline.

Needs RAG_TEST_DATABASE_URL (superuser URL, schema applied) and RAG_TEST_REDIS_URL.
"""
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import psycopg
import pytest
import uvicorn

ADMIN_URL = os.environ.get("RAG_TEST_DATABASE_URL")
REDIS_URL = os.environ.get("RAG_TEST_REDIS_URL")
pytestmark = pytest.mark.skipif(not (ADMIN_URL and REDIS_URL), reason="RAG_TEST_DATABASE_URL / RAG_TEST_REDIS_URL not set")

ROOT = Path(__file__).resolve().parents[2]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve(app, port) -> uvicorn.Server:
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    deadline = time.time() + 20
    while not server.started:
        assert time.time() < deadline, "server did not start"
        time.sleep(0.05)
    return server


@pytest.fixture
def stack(tmp_path, monkeypatch):
    info = psycopg.conninfo.conninfo_to_dict(ADMIN_URL)
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("TRUNCATE chunks, documents, audit_log RESTART IDENTITY CASCADE")
    info.update(user="rag_app", password="rag_app_pw")
    monkeypatch.setenv("DATABASE_URL", psycopg.conninfo.make_conninfo(**info))
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("INTERNAL_TOKEN", "demo-e2e-internal")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "hash")
    monkeypatch.setenv("LLM_PROVIDER", "extractive")

    from ragplatform import config, db
    from ragplatform.agent.app import app as agent_app

    config.get_settings.cache_clear()
    if db._pool is not None:
        db._pool.close()
        db._pool = None

    from support.fake_gateway import create_app

    agent_port, gw_port = free_port(), free_port()
    agent = serve(agent_app, agent_port)  # runs the real lifespan: builds the LangGraph + embedder + LLM
    gateway = serve(
        create_app(secret="e2e-secret-at-least-32-bytes-long!!!", agent_url=f"http://127.0.0.1:{agent_port}",
                   redis_url=REDIS_URL, storage_root=str(tmp_path), internal_token="demo-e2e-internal"),
        gw_port,
    )
    import redis
    redis.Redis.from_url(REDIS_URL).flushdb()
    yield f"http://127.0.0.1:{gw_port}"
    gateway.should_exit = agent.should_exit = True
    time.sleep(0.3)
    if db._pool is not None:
        db._pool.close()
        db._pool = None
    config.get_settings.cache_clear()


def test_demo_script_passes_end_to_end(stack):
    r = subprocess.run([sys.executable, str(ROOT / "scripts/demo.py")], capture_output=True, text=True,
                       env={**os.environ, "GATEWAY_URL": stack}, timeout=180)
    print(r.stdout, r.stderr)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "All checks passed" in r.stdout
