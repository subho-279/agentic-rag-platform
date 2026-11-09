"""Embedding providers.

`hash` is the zero-dependency default: a signed feature-hashing embedder over
unigrams and bigrams. It is purely lexical (no semantic generalisation), which
is enough to make the whole platform runnable offline. Switch to `openai` for
real semantic embeddings.
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol, Sequence

import httpx

from .config import Settings

_TOKEN_RE = re.compile(r"[a-z0-9]+")

STOPWORDS = frozenset(
    "a an the and or but if then of to in on at for from by with about as is are was were be been being "
    "do does did have has had it its this that these those i you he she we they me my your our their "
    "what which who whom when where why how can could should would will shall may might must not no yes".split()
)


def tokenize(text: str) -> list[str]:
    """Lower-case word tokens with stopwords removed and a light plural stem."""
    out = []
    for tok in _TOKEN_RE.findall(text.lower()):
        if tok in STOPWORDS:
            continue
        if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
            tok = tok[:-1]
        out.append(tok)
    return out


class Embedder(Protocol):
    dim: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class HashEmbedder:
    def __init__(self, dim: int = 1536):
        self.dim = dim

    def _one(self, text: str) -> list[float]:
        toks = tokenize(text)
        feats = [(t, 1.0) for t in toks] + [(f"{a}_{b}", 0.5) for a, b in zip(toks, toks[1:])]
        vec = [0.0] * self.dim
        for feat, weight in feats:
            digest = hashlib.blake2b(feat.encode(), digest_size=9).digest()
            idx = int.from_bytes(digest[:8], "big") % self.dim
            sign = 1.0 if digest[8] & 1 else -1.0
            vec[idx] += sign * weight
        norm = math.sqrt(sum(x * x for x in vec))
        if norm == 0:
            # Empty text: return a fixed unit vector so the DB never stores NaN/zero vectors.
            vec[0] = 1.0
            return vec
        return [x / norm for x in vec]

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]


class OpenAIEmbedder:
    def __init__(self, api_key: str, model: str, dim: int):
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for EMBEDDING_PROVIDER=openai")
        self.api_key, self.model, self.dim = api_key, model, dim

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 64):
            batch = list(texts[i : i + 64])
            resp = httpx.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "input": batch, "dimensions": self.dim},
                timeout=60,
            )
            resp.raise_for_status()
            out.extend(item["embedding"] for item in resp.json()["data"])
        return out


def build_embedder(settings: Settings) -> Embedder:
    provider = settings.embedding_provider.lower()
    if provider == "hash":
        return HashEmbedder(settings.embedding_dim)
    if provider == "openai":
        return OpenAIEmbedder(settings.openai_api_key, settings.openai_embedding_model, settings.embedding_dim)
    raise ValueError(f"unknown EMBEDDING_PROVIDER: {provider}")
