"""TEST-ONLY stand-in for the Java gateway.

It reproduces the gateway's HTTP contract (JWT auth -> tenant context -> Redis token bucket ->
upload/ingest/query) so scripts/demo.py can be exercised against the REAL agent, worker pipeline,
Postgres (RLS) and Redis (the real token_bucket.lua) in an environment without Maven or Docker.

It does NOT test the Java code. Kafka is replaced by a background thread calling the worker's
message handler with the same JSON event the gateway publishes.
"""
from __future__ import annotations

import json
import math
import re
import threading
import uuid
from pathlib import Path
from typing import List

import httpx
import jwt
import redis
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse

from ragplatform.config import get_settings
from ragplatform.db import sanitize_roles, tenant_session, validate_tenant_id
from ragplatform.embeddings import build_embedder
from ragplatform.worker.main import handle_message

LUA = (Path(__file__).resolve().parents[3] / "gateway/src/main/resources/scripts/token_bucket.lua").read_text()
QUERY_COST = UPLOAD_COST = 5


def create_app(*, secret: str, agent_url: str, redis_url: str, storage_root: str, internal_token: str,
               capacity: int = 20, refill_per_sec: float = 5) -> FastAPI:
    app = FastAPI()
    bucket = redis.Redis.from_url(redis_url).register_script(LUA)
    settings = get_settings()
    embedder = build_embedder(settings)
    root = Path(storage_root)

    @app.middleware("http")
    async def security_chain(request: Request, call_next):
        path = request.url.path
        if path.startswith("/actuator/health") or path.startswith("/dev/"):
            return await call_next(request)
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            claims = jwt.decode(auth[7:], secret, algorithms=["HS256"])
            tenant = validate_tenant_id(claims.get("tenant_id") or "")
        except jwt.PyJWTError:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        except ValueError:
            return JSONResponse({"error": "token has no valid tenant_id claim"}, status_code=403)
        request.state.tenant = tenant
        request.state.user = claims.get("sub", "")
        request.state.roles = sanitize_roles(claims.get("roles") or [])

        cost = QUERY_COST if path.startswith("/api/v1/query") else UPLOAD_COST if (request.method == "POST" and path.startswith("/api/v1/documents")) else 1
        allowed, _remaining, retry_ms = bucket(keys=[f"rl:tenant:{tenant}"], args=[capacity, refill_per_sec, cost])
        if not allowed:
            retry = max(1, math.ceil(retry_ms / 1000))
            return JSONResponse({"error": "tenant rate limit exceeded"}, status_code=429, headers={"Retry-After": str(retry)})
        return await call_next(request)

    @app.get("/actuator/health")
    def health():
        return {"status": "UP"}

    @app.get("/dev/token")
    def dev_token(tenant: str, user: str = "demo-user", roles: List[str] = Query(["employee"])):
        try:
            validate_tenant_id(tenant)
        except ValueError:
            raise HTTPException(400, "invalid tenant id")
        return {"token": jwt.encode({"sub": user, "tenant_id": tenant, "roles": sanitize_roles(roles)}, secret, algorithm="HS256")}

    @app.post("/api/v1/documents", status_code=202)
    def upload(request: Request, file: UploadFile = File(...), allowedRoles: str = Form("")):
        if not ({"admin", "editor"} & set(request.state.roles)):
            raise HTTPException(403, "forbidden")
        name = re.sub(r"[^A-Za-z0-9._-]", "_", (file.filename or "").replace("\\", "/").split("/")[-1])
        if "." not in name or name.startswith(".") or name.rsplit(".", 1)[1].lower() not in {"pdf", "txt", "md", "csv"}:
            raise HTTPException(400, "bad file")
        tenant, doc_id = request.state.tenant, str(uuid.uuid4())
        rel = f"{tenant}/{doc_id}/{name}"
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(file.file.read())
        roles = sanitize_roles(allowedRoles.split(","))
        with tenant_session(tenant, request.state.roles) as conn:
            conn.execute(
                "INSERT INTO documents (id, tenant_id, filename, storage_path, status, allowed_roles, created_by) "
                "VALUES (%s,%s,%s,%s,'PENDING',%s,%s)",
                (doc_id, tenant, name, rel, roles, request.state.user),
            )
        event = json.dumps({"document_id": doc_id, "tenant_id": tenant, "file_path": rel}).encode()
        threading.Thread(target=handle_message, args=(event, settings, embedder), daemon=True).start()  # stands in for Kafka
        return {"documentId": doc_id, "status": "PENDING"}

    @app.get("/api/v1/documents/{doc_id}")
    def get_document(doc_id: str, request: Request):
        with tenant_session(request.state.tenant, request.state.roles) as conn:
            row = conn.execute("SELECT id, filename, status, chunk_count FROM documents WHERE id = %s", (doc_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "not found")  # RLS-hidden rows look identical to missing ones
        return {"id": str(row[0]), "filename": row[1], "status": row[2], "chunkCount": row[3]}

    @app.post("/api/v1/query")
    def query(request: Request, body: dict):
        r = httpx.post(
            f"{agent_url}/internal/query",
            json={"query": body.get("query", "")},
            headers={"X-Internal-Token": internal_token, "X-Tenant-Id": request.state.tenant,
                     "X-User-Id": request.state.user, "X-User-Roles": ",".join(request.state.roles)},
            timeout=60,
        )
        return JSONResponse(r.json(), status_code=r.status_code)

    return app
