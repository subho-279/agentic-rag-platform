.PHONY: up down logs demo test test-python test-java test-integration it-services it-services-down prod-up prod-down

# ---- run the stack -----------------------------------------------------------
up:
	docker compose up --build -d --wait

down:
	docker compose down -v

logs:
	docker compose logs -f gateway agent worker

demo:
	python3 scripts/demo.py

# ---- tests -------------------------------------------------------------------
test: test-python test-java

test-python:
	cd python && pip install -e '.[dev]' && pytest -q

test-java:
	cd gateway && mvn -B verify

# Integration tests need real Postgres (pgvector) and Redis. `it-services` starts throwaway ones.
PG_URL    ?= postgresql://postgres:postgres@localhost:55432/ragdb
REDIS_URL ?= redis://localhost:56379/0

it-services:
	-docker rm -f rag-it-pg rag-it-redis >/dev/null 2>&1
	docker run -d --name rag-it-pg -p 55432:5432 -e POSTGRES_DB=ragdb -e POSTGRES_PASSWORD=postgres \
	  -v "$(CURDIR)/db/init.sql:/docker-entrypoint-initdb.d/01-init.sql:ro" pgvector/pgvector:pg16
	docker run -d --name rag-it-redis -p 56379:6379 redis:7.2-alpine
	@echo "waiting for Postgres..."; until docker exec rag-it-pg pg_isready -U postgres -d ragdb >/dev/null 2>&1; do sleep 1; done; sleep 3

it-services-down:
	-docker rm -f rag-it-pg rag-it-redis

test-integration:
	cd python && pip install -e '.[dev]' httpx && RAG_TEST_DATABASE_URL=$(PG_URL) RAG_TEST_REDIS_URL=$(REDIS_URL) pytest -q -rs

# ---- production (see DEPLOY.md) ------------------------------------------------
prod-up:
	docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.prod up -d --build --wait

prod-down:
	docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.prod down
