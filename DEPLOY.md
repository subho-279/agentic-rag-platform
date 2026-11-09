# Deploying

This is a runbook for a single Linux VM (any provider: EC2, Hetzner, DigitalOcean, Oracle free tier) running the whole stack with Docker Compose behind Caddy, which obtains and renews a TLS certificate automatically.

**Sizing:** 4 GB RAM / 2 vCPU is the practical minimum (Kafka and the JVM are the big consumers). 8 GB is comfortable.

> **Status of this runbook.** The production overlay's rendering and fail-fast behaviour, the Postgres password script, the token minter and the Python image's package install were verified locally. The container *builds* and the Caddy TLS setup could not be run in the environment this was written in, so do the smoke test in step 5 and treat the first deploy as the real test. CI runs the full stack on every push (the `e2e` job).

## 1. Prerequisites

- A VM with Docker Engine and the Compose plugin (`docker compose version` shows v2.24 or newer; the overlay uses `!reset`).
- A DNS `A` record for your domain pointing at the VM, and ports **80 and 443** open (Caddy needs both to issue certificates).
- Ports 5432, 6379, 9092 and 8080 do **not** need to be open and should stay closed: only Caddy is published.

## 2. Configure

```bash
git clone <your repo> && cd agentic-rag-platform
cp .env.prod.example .env.prod
chmod 600 .env.prod
```

Fill in `.env.prod`. Generate every secret with `openssl rand -hex 32`.

| Variable | Notes |
| --- | --- |
| `DOMAIN` | e.g. `rag.example.com` |
| `POSTGRES_PASSWORD`, `RAG_APP_PASSWORD`, `REDIS_PASSWORD`, `INTERNAL_TOKEN` | all required; compose refuses to start if any is missing |
| `OIDC_ISSUER_URI` **or** `JWT_SECRET` | how users authenticate; see below |
| `LLM_PROVIDER`, `EMBEDDING_PROVIDER` (+ keys) | defaults are offline; see the README for real models |

**Passwords are set only when the database volume is first created.** Changing `RAG_APP_PASSWORD` later requires `ALTER ROLE rag_app PASSWORD '...'` inside Postgres as well, or wiping the volume (which deletes data).

### Authentication

- **OIDC (recommended).** Set `OIDC_ISSUER_URI` to your provider's issuer (Keycloak realm URL, Auth0 domain, Entra tenant, ...). Tokens must carry a `tenant_id` claim (string, `[A-Za-z0-9_-]{1,64}`) and a `roles` claim (array of strings). Add those with a claim mapper / action in your provider. The gateway checks signature, issuer and expiry.
- **Self-managed tokens.** Leave `OIDC_ISSUER_URI` empty and set `JWT_SECRET` (at least 32 bytes). Mint a token per user:
  ```bash
  JWT_SECRET=... python3 scripts/mint_token.py --tenant acme --user alice --roles admin,employee --ttl 86400
  ```
  The gateway will not start with neither configured. The `/dev/token` demo endpoint is disabled in production and also blocked by Caddy.

Roles: `admin` and `editor` may upload documents; any role name can be used in a document's `allowedRoles`.

## 3. Start

```bash
make prod-up          # = docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.prod up -d --build --wait
docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.prod ps
```

First build takes several minutes (Maven and pip downloads). `--wait` returns when every healthcheck passes.

## 4. Onboarding a tenant

There is no tenant table: a tenant exists as soon as a token carries its `tenant_id`. To onboard `acme`, mint (or configure your IdP to issue) tokens with `tenant_id=acme`, give one user `admin`, and have them upload documents.

## 5. Smoke test

```bash
TOKEN=$(JWT_SECRET=... python3 scripts/mint_token.py --tenant smoke --user ops --roles admin,employee)
curl -fsS https://$DOMAIN/actuator/health                                   # {"status":"UP"}
curl -s -o /dev/null -w '%{http_code}\n' https://$DOMAIN/dev/token?tenant=x # 404 (never exposed)
curl -s -o /dev/null -w '%{http_code}\n' https://$DOMAIN/api/v1/documents   # 401 without a token
curl -fsS -H "Authorization: Bearer $TOKEN" -F file=@sample_data/acme_handbook.md https://$DOMAIN/api/v1/documents
# poll the returned documentId until status is READY, then:
curl -fsS -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"query":"How many weeks of parental leave?"}' https://$DOMAIN/api/v1/query
```

To run the full isolation demo against production you would need tokens for two tenants; it is simpler to run `make demo` against a staging copy (dev stack) instead. `scripts/demo.py` honours `GATEWAY_URL`.

## 6. Operations

**Logs:** `docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f gateway agent worker`

**Health:** gateway `/actuator/health` (database and Redis checked); the agent has an internal `/healthz`.

**Backups.** Postgres holds all metadata and vectors; uploaded files are in the `uploads` volume. Back up both:

```bash
docker compose exec -T postgres pg_dump -U postgres -Fc ragdb > ragdb-$(date +%F).dump
docker run --rm -v agentic-rag_uploads:/data -v "$PWD":/out alpine tar czf /out/uploads-$(date +%F).tgz -C /data .
```

Restore with `pg_restore -U postgres -d ragdb --clean` into a fresh database. Documents can also be re-ingested from the uploads volume. Note that `pg_dump` run as `postgres` bypasses Row-Level Security by design, so treat dumps as sensitive: they contain every tenant's data.

**Upgrades:** `git pull && make prod-up`. The schema is applied only on first volume creation; schema changes need a manual migration (there is no migration tool yet).

**Scaling workers:** `docker compose ... up -d --scale worker=3`. The topic has 3 partitions, so more than 3 workers will sit idle.

**Rate limits:** `RATE_LIMIT_CAPACITY` / `RATE_LIMIT_REFILL_PER_SEC` set the per-tenant bucket (a query or upload costs 5 tokens, other calls 1). Per-tenant overrides: `app.rate-limit.tenants.<id>.capacity` in `gateway/src/main/resources/application.yml`.

## Known gaps for a serious production deployment

- Single-node Kafka, Postgres and Redis: no high availability. Use managed services (RDS with pgvector, ElastiCache, MSK) for that; every endpoint is an environment variable.
- Internal traffic (gateway to agent, services to Postgres/Redis/Kafka) is plain TCP on the private Docker network, authenticated by a shared token or passwords. mTLS or a service mesh is the upgrade.
- Uploads live on a local Docker volume, so the gateway and worker must run on the same host. Swap `StorageService` for S3 to separate them.
- No metrics or tracing exporters beyond logs and the health endpoint.
- No automated schema migrations, no automated backups, no secret manager integration.
