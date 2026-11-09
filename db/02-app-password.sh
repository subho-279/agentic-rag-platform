#!/bin/bash
# Runs once, after 01-init.sql, on first start of the postgres container.
# Sets the application role's password from RAG_APP_PASSWORD (init.sql creates it with a dev-only default).
#
# The postgres entrypoint *sources* init scripts that are not executable, so everything runs in a subshell:
# `set -e` / `set -u` must not leak into the entrypoint's own shell.
(
  set -euo pipefail
  if [ -n "${RAG_APP_PASSWORD:-}" ]; then
    # :'pw' is psql's safe literal quoting, so any password characters are handled correctly.
    psql -v ON_ERROR_STOP=1 -v pw="$RAG_APP_PASSWORD" -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<'SQL'
ALTER ROLE rag_app PASSWORD :'pw';
SQL
  fi
)
