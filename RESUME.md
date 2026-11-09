# Résumé / portfolio copy

## One-line summary
Multi-tenant agentic RAG platform (Java/Spring Boot + Python/LangGraph + Kafka + Redis + PostgreSQL/pgvector) with database-enforced tenant isolation, per-tenant rate limiting and guarded, self-correcting retrieval.

## Résumé bullets (pick 3-4)
- Designed and built a multi-tenant RAG platform on a hybrid Java 21 / Python stack: Spring Boot gateway (OAuth2 JWT, virtual threads) fronting a FastAPI + LangGraph agent, with asynchronous ingestion over Kafka and pgvector for retrieval.
- Enforced tenant and per-document role isolation inside PostgreSQL using Row-Level Security (fail-closed policies, transaction-local session settings, unprivileged app role), backed by CI tests that prove one tenant's queries return nothing from another's data.
- Implemented per-tenant token-bucket rate limiting in Redis (atomic Lua script) so a noisy tenant is throttled with 429s while other tenants stay unaffected.
- Built a LangGraph agent with input/output guardrails, relevance grading and bounded query-rewrite retries, streaming answers with source citations over SSE; pluggable LLM/embedding providers (Ollama, OpenAI, Anthropic) with a fully offline default.
- Hardened the ingestion path: tenant-prefixed storage with path-traversal checks, PII redaction before embedding, idempotent Kafka consumers with manual offset commits, and an audit log that stores query hashes rather than raw text.

## Forward Deployment Engineer angle (talking points)
- **Customer reality:** enterprises ask "can my data leak to another customer?" first. This project answers with a mechanism (RLS) and a test, not a promise.
- **Deployability:** one `docker compose up`, no API keys needed, and a scripted demo that shows isolation, roles, guardrails and rate limiting live in a few minutes.
- **Trade-off fluency:** documented choices (Kafka over Celery, MVC+Loom over reactive gateway, internal token vs mTLS) and an explicit list of what is not built yet.

## Interview questions this prepares you for
- Why RLS and an explicit `WHERE` clause? (defence in depth; what if a policy is dropped?)
- Why `set_config(..., true)` rather than `SET LOCAL` or a session setting on pooled connections?
- What happens if Kafka is down after the DB insert? (document marked FAILED; outbox pattern as the fix)
- How would you evaluate answer quality? (Ragas faithfulness / context precision on a labelled query set; not yet implemented)
- How would you move from the shared secret to mTLS, and from HS256 to a real OIDC provider?
