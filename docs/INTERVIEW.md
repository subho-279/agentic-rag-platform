# Interview guide

How to present this project, what to demo, and answers to the questions you are most likely to get. Everything here is true of the code as delivered; the "unverified" notes matter, because an interviewer may ask exactly those questions.

## Before any interview: make it yours

An interviewer will test whether you understand the project, not whether it exists. Spend a few hours on this and you will be fine.

1. **Run it.** Follow [SETUP.md](SETUP.md) until `python scripts/demo.py` is all PASS. If CI on GitHub is green, add the badge to the README.
2. **Break it on purpose, so you can explain why it works.**
   - Disable RLS in Postgres and run the integration tests: all six isolation tests fail (`ALTER TABLE chunks DISABLE ROW LEVEL SECURITY; ALTER TABLE documents DISABLE ROW LEVEL SECURITY;`). Re-enable it afterwards. Being able to *show* this is far more convincing than describing it.
   - Lower `RATE_LIMIT_CAPACITY` and watch the 429s.
   - Change `SIMILARITY_THRESHOLD` and watch the agent rewrite queries (read the `trace` in the JSON response).
3. **Read these files end to end** (about 800 lines in total, and each is short): `db/init.sql`, `python/ragplatform/db.py`, `agent/graph.py`, `worker/pipeline.py`, `worker/main.py`, `gateway/.../security/SecurityConfig.java`, `ratelimit/token_bucket.lua`, `scripts/demo.py`.
4. **Record a 2-minute screen capture of the demo** and link it from the README. It is your fallback if Docker misbehaves in a live setting.
5. **Be straightforward about how you built it.** If you used AI assistance, say so; the honest and strong framing is "I used it to build faster, and I can explain and change every part", which you can only say truthfully after step 3.

## The 30-second pitch

> "I built a multi-tenant RAG platform where many companies share one deployment but can never see each other's documents. A Spring Boot gateway authenticates users and rate-limits per tenant, uploads are processed asynchronously through Kafka, and a LangGraph agent answers questions with citations and retries when retrieval is weak. The key design choice is that isolation is enforced by Postgres Row-Level Security rather than application code, and I have tests that prove a tenant gets nothing back for another tenant's content."

## The 2-minute architecture walkthrough

Open [ARCHITECTURE.md](ARCHITECTURE.md) and walk the first diagram left to right:

1. **Client to gateway.** JWT in, identity out. The gateway decides who the caller is and nothing downstream trusts the client.
2. **Rate limit.** A per-tenant token bucket in Redis, so one tenant's burst can't starve others.
3. **Upload path.** File saved, `PENDING` row written, event on Kafka, `202` returned. A Python worker extracts, chunks, redacts PII, embeds and stores.
4. **Query path.** Gateway forwards tenant and roles to the agent. The agent guards the input, retrieves inside a tenant-scoped transaction, grades results, rewrites and retries up to three times, generates with citations, then guards the output.
5. **Isolation.** Close with the seven-layer diagram: the point is no single layer is trusted alone.

## Live demo script (about 5 minutes)

Run `python scripts/demo.py` and narrate each section as it prints:

| Section | What to say |
| --- | --- |
| 1. Ingest | "Uploads return immediately; the worker processes them through Kafka. The HR salary document is restricted to the `hr` role." |
| 2. Isolation | "Same question, two tenants, different answers. Then Acme asks about Globex's pricing and gets nothing, and Globex asks about Acme's codename and gets nothing." |
| 3. Roles | "Within one tenant an employee can't see the HR document, an HR user can. That is enforced by a second restrictive database policy, not by an `if` in the application." |
| 4. Guardrails | "Prompt-injection and tenant-escape attempts are blocked before any retrieval happens." |
| 5. Rate limit | "Acme floods the API and gets 429s; Globex, at the same moment, is served normally." |

Then, if time allows, show `docker compose exec postgres psql ...` and `SELECT * FROM pg_policies;` to point at the actual policies, or run the RLS tests and mention they fail when RLS is disabled.

## Questions you should expect

**Why Row-Level Security instead of filtering in code?**
Application filters are easy to forget in one query; RLS applies to every query on the table, including ones written later or by mistake. If the tenant setting is missing the policy compares against NULL and returns zero rows, so it fails closed. I still add an explicit `WHERE tenant_id = ...` as a second layer.

**How does the database know which tenant is asking?**
Each transaction begins with `set_config('app.current_tenant', <tenant>, true)`. The `true` makes it transaction-local, so with a connection pool a connection can't carry one request's identity into the next. I use `set_config` with bound parameters rather than string-built `SET LOCAL`, which avoids SQL injection.

**Can't a superuser or the table owner bypass RLS?**
Superusers always can, so the services connect as `rag_app`, a non-superuser role. `FORCE ROW LEVEL SECURITY` makes policies apply to the owner too. The tests connect as `rag_app` for every assertion.

**What happens if Kafka is down when someone uploads?**
The document row is marked `FAILED`, the client gets a 503, and nothing is silently lost. There is no automatic retry; the proper fix is a transactional outbox, which I list as a next step.

**What if a worker crashes mid-document?**
Offsets are committed only after the document is handled, so Kafka redelivers. Ingestion deletes and rewrites that document's chunks, so redelivery is idempotent. That is at-least-once delivery with idempotent processing.

**What about a malformed or forged event?**
Permanent errors are not retried and don't block the partition. The worker checks the file path is inside the event's own tenant folder and that the document row exists for that tenant (RLS hides other tenants' rows), so a forged event can't read another tenant's file.

**Why a token bucket, and why Lua?**
A token bucket allows short bursts while enforcing an average rate, which suits interactive use. The check-and-take must be atomic across gateway instances, so it runs as one Lua script in Redis. I tested it with 16 concurrent callers: exactly `capacity` succeeded.

**Why does the limiter fail open?**
If Redis is down I'd rather serve traffic than take every tenant offline. It is configurable (`fail-open`); a stricter deployment can fail closed.

**How do you stop prompt injection?**
Honest answer: partially. There is an input guard for obvious injection and tenant-escape patterns, retrieved text is passed to the model as untrusted data with an instruction not to follow it, and, most importantly, **injection can't cross tenants because the tenant never comes from the prompt**. The heuristic guard won't stop a sophisticated attack; the interface is small so a classifier (e.g. Llama Guard) can replace it.

**How do you evaluate answer quality?**
Not built yet. The plan is Ragas (faithfulness and context precision) over a labelled query set. The API already returns the retrieved sources and a step trace, which is what such an evaluation needs. Say this plainly: it was on the original roadmap and is the honest next milestone.

**Why are the default embeddings "hash"? Is that real RAG?**
The default is a lexical feature-hashing embedder so the whole stack runs offline with no keys; it matches overlapping words, not meaning. One environment variable switches to OpenAI embeddings (or a local model) for real semantic retrieval. The pipeline, isolation and tests are identical either way.

**How would this scale?**
Gateway instances are stateless (state is in Redis and Postgres) so they scale horizontally. Workers scale with Kafka partitions (3 by default). The bottleneck will be Postgres: next steps would be read replicas, partitioning `chunks` by tenant, and tuning HNSW. For very large tenants, a dedicated database or schema is the escape hatch.

**RLS performance?**
Policies add a predicate to each query; with an index on `tenant_id` the cost is small. The restrictive role policy uses an array overlap, which is cheap at this scale; I'd measure before optimising.

**How do you delete a customer's data?**
Chunks cascade from documents, so deleting a tenant's documents removes its vectors. There is no delete endpoint yet (a gap). The audit log stores query hashes, not text, so it contains no document content.

**How does authentication work in production?**
The gateway is an OAuth2 resource server. Locally it validates HS256 tokens so it runs without an identity provider; in production you set `OIDC_ISSUER_URI` and it validates against your provider (signature, issuer, expiry). Tokens need a `tenant_id` claim and a `roles` array.

## Forward-deployment angle

If the role is customer-facing, these are the points to lean on:
- **A customer's first question is "can my data leak to another customer?"** You can answer with a mechanism and a test, and demonstrate it live.
- **Deployability:** the stack runs from one `docker compose up`, needs no external accounts or keys, and has a production overlay, a runbook and a smoke test ([DEPLOY.md](../DEPLOY.md)).
- **Customer integration points are explicit:** SSO via OIDC, model provider via an environment variable, storage via one class, tenants onboarded by token claims.
- **You can discuss trade-offs and limits honestly** (see the table in ARCHITECTURE.md), which builds more trust than claiming it's finished.

## What is and isn't verified (say this proactively)

| Verified by running it | Not yet verified in the environment where it was written |
| --- | --- |
| Schema and RLS on real Postgres 16 + pgvector; 78 Python tests pass against real Postgres and Redis | The Java gateway build and its unit tests (CI runs `mvn verify`) |
| RLS tests fail when RLS is disabled (checked) | Docker image builds, Kafka, Caddy TLS (CI `e2e` job covers all but Caddy) |
| Redis token bucket, including concurrency | Real-model quality (only the offline answerer was exercised) |
| The demo, end to end, via a stand-in gateway | |

After your CI run is green, update this table in your README to say the Java and Docker parts are verified by CI.

## Honest limitations (and what you'd do next)

- No evaluation harness yet (Ragas), no load tests (Locust), no dashboards.
- No transactional outbox or dead-letter queue; no schema-migration tool.
- Regex PII redaction misses names and free-form identifiers.
- Single-node Kafka, Postgres and Redis; internal traffic is not encrypted (shared token instead of mTLS).
- Uploads are on a shared volume rather than S3.
- A document restricted to roles the uploader lacks returns 404 to the uploader.

Being able to list these unprompted, with the fix for each, signals seniority more than a project with none listed.

## Checklist the day before

- [ ] `docker compose down -v && docker compose up --build -d --wait` works from scratch
- [ ] `python scripts/demo.py` ends with "All checks passed."
- [ ] GitHub Actions is green and the badge is in the README
- [ ] Repo pinned on your GitHub profile; a short description and topics set (`rag`, `multi-tenant`, `spring-boot`, `fastapi`, `langgraph`, `kafka`, `pgvector`)
- [ ] 2-minute screen recording linked in the README
- [ ] You can explain, without notes, the seven isolation layers and the upload flow
