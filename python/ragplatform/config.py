"""Environment-driven settings shared by the worker and the agent."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _split(value: str) -> tuple[str, ...]:
    return tuple(p.strip() for p in value.split(",") if p.strip())


@dataclass(frozen=True)
class Settings:
    database_url: str = field(
        default_factory=lambda: _env("DATABASE_URL", "postgresql://rag_app:rag_app_pw@localhost:5432/ragdb")
    )
    kafka_bootstrap: str = field(default_factory=lambda: _env("KAFKA_BOOTSTRAP", "localhost:9092"))
    kafka_topic: str = field(default_factory=lambda: _env("KAFKA_TOPIC", "documents.ingest"))
    kafka_group: str = field(default_factory=lambda: _env("KAFKA_GROUP", "rag-ingest-workers"))
    storage_root: str = field(default_factory=lambda: _env("STORAGE_ROOT", "/data/uploads"))

    embedding_provider: str = field(default_factory=lambda: _env("EMBEDDING_PROVIDER", "hash"))
    embedding_dim: int = field(default_factory=lambda: int(_env("EMBEDDING_DIM", "1536")))
    openai_api_key: str = field(default_factory=lambda: _env("OPENAI_API_KEY"))
    openai_embedding_model: str = field(default_factory=lambda: _env("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"))

    llm_provider: str = field(default_factory=lambda: _env("LLM_PROVIDER", "extractive"))
    ollama_base_url: str = field(default_factory=lambda: _env("OLLAMA_BASE_URL", "http://localhost:11434"))
    ollama_model: str = field(default_factory=lambda: _env("OLLAMA_MODEL", "llama3.1:8b"))
    openai_model: str = field(default_factory=lambda: _env("OPENAI_MODEL", "gpt-4o-mini"))
    anthropic_api_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    anthropic_model: str = field(default_factory=lambda: _env("ANTHROPIC_MODEL", "claude-sonnet-5-5"))

    # Shared secret the gateway presents to the agent (stand-in for mTLS).
    internal_token: str = field(default_factory=lambda: _env("INTERNAL_TOKEN", "dev-internal-token-change-me"))

    retrieval_top_k: int = field(default_factory=lambda: int(_env("RETRIEVAL_TOP_K", "5")))
    similarity_threshold: float = field(default_factory=lambda: float(_env("SIMILARITY_THRESHOLD", "0.2")))
    max_rewrites: int = field(default_factory=lambda: int(_env("MAX_REWRITES", "3")))

    chunk_max_chars: int = field(default_factory=lambda: int(_env("CHUNK_MAX_CHARS", "1000")))
    chunk_overlap_chars: int = field(default_factory=lambda: int(_env("CHUNK_OVERLAP_CHARS", "150")))

    guard_blacklist: tuple[str, ...] = field(default_factory=lambda: _split(_env("GUARD_BLACKLIST")))


@lru_cache
def get_settings() -> Settings:
    return Settings()
