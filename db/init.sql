-- Multi-tenant schema with Row-Level Security.
-- Executed once by the postgres container entrypoint (as the bootstrap superuser).

CREATE EXTENSION IF NOT EXISTS vector;

-- Application role: NOT a superuser and NOBYPASSRLS, so every policy below applies to it.
-- Dev-only password; override via your secret manager in any real deployment.
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'rag_app') THEN
    CREATE ROLE rag_app LOGIN PASSWORD 'rag_app_pw' NOSUPERUSER NOBYPASSRLS;
  END IF;
END
$$;

CREATE TABLE IF NOT EXISTS documents (
  id            uuid PRIMARY KEY,
  tenant_id     text        NOT NULL,
  filename      text        NOT NULL,
  content_type  text,
  storage_path  text        NOT NULL,
  status        text        NOT NULL DEFAULT 'PENDING',  -- PENDING | PROCESSING | READY | FAILED
  allowed_roles text[]      NOT NULL DEFAULT '{}',       -- empty = every user in the tenant
  chunk_count   integer     NOT NULL DEFAULT 0,
  error         text,
  created_by    text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
  id            bigserial PRIMARY KEY,
  tenant_id     text        NOT NULL,
  document_id   uuid        NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  chunk_index   integer     NOT NULL,
  content       text        NOT NULL,
  allowed_roles text[]      NOT NULL DEFAULT '{}',
  embedding     vector(1536) NOT NULL,
  metadata      jsonb       NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE (document_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS audit_log (
  id         bigserial PRIMARY KEY,
  tenant_id  text        NOT NULL,
  user_id    text        NOT NULL,
  action     text        NOT NULL,
  detail     jsonb       NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_documents_tenant ON documents (tenant_id);
CREATE INDEX IF NOT EXISTS idx_chunks_tenant    ON chunks (tenant_id);
CREATE INDEX IF NOT EXISTS idx_audit_tenant     ON audit_log (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON chunks USING hnsw (embedding vector_cosine_ops);

-- ---------------------------------------------------------------------------
-- Row-Level Security
--   * app.current_tenant is set per transaction with set_config(..., true).
--   * If it is unset, current_setting(..., true) is NULL, the comparison is NULL,
--     and zero rows are visible: the policy fails closed.
--   * FORCE makes the policies apply even to the table owner.
-- ---------------------------------------------------------------------------
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents FORCE  ROW LEVEL SECURITY;
ALTER TABLE chunks    ENABLE ROW LEVEL SECURITY;
ALTER TABLE chunks    FORCE  ROW LEVEL SECURITY;
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log FORCE  ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON documents FOR ALL
  USING      (tenant_id = current_setting('app.current_tenant', true))
  WITH CHECK (tenant_id = current_setting('app.current_tenant', true));

CREATE POLICY tenant_isolation ON chunks FOR ALL
  USING      (tenant_id = current_setting('app.current_tenant', true))
  WITH CHECK (tenant_id = current_setting('app.current_tenant', true));

CREATE POLICY tenant_isolation ON audit_log FOR ALL
  USING      (tenant_id = current_setting('app.current_tenant', true))
  WITH CHECK (tenant_id = current_setting('app.current_tenant', true));

-- User-level document permissions, layered on top of tenant isolation.
-- RESTRICTIVE policies are AND-ed with the permissive ones above.
-- '__system__' is set only by the trusted ingestion worker; the gateway and the
-- agent strip that value from user-supplied roles.
CREATE POLICY role_filter ON documents AS RESTRICTIVE FOR SELECT
  USING (
    current_setting('app.current_roles', true) = '__system__'
    OR cardinality(allowed_roles) = 0
    OR allowed_roles && string_to_array(coalesce(current_setting('app.current_roles', true), ''), ',')
  );

CREATE POLICY role_filter ON chunks AS RESTRICTIVE FOR SELECT
  USING (
    current_setting('app.current_roles', true) = '__system__'
    OR cardinality(allowed_roles) = 0
    OR allowed_roles && string_to_array(coalesce(current_setting('app.current_roles', true), ''), ',')
  );

GRANT SELECT, INSERT, UPDATE, DELETE ON documents, chunks, audit_log TO rag_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO rag_app;
