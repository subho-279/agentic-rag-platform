"""Input and output guardrails.

The default guards are heuristic (regex) so the stack runs offline. They are a
cheap first filter, not a substitute for a safety model: swap in Llama Guard
(or any classifier) by implementing the same `check` signature.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from ..pii import redact

MAX_QUERY_CHARS = 2000

_INJECTION_PATTERNS = [
    r"ignore (all |any )?(the )?(previous|prior|above) (instructions|rules|prompts?)",
    r"disregard (all |any )?(the )?(previous|prior|above|system)",
    r"(reveal|show|print|repeat) (me )?(your |the )?(system|hidden|initial) (prompt|instructions)",
    r"\bapp\.current_(tenant|roles)\b",
    r"\bset\s+(local\s+)?app\.",
    r"(other|another|different|all) tenants?\b",
    r"\bdrop\s+table\b|\bunion\s+select\b|;\s*--",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)


@dataclass(frozen=True)
class GuardResult:
    ok: bool
    reason: str = ""


class InputGuard:
    def check(self, query: str) -> GuardResult:
        if not query or not query.strip():
            return GuardResult(False, "empty query")
        if len(query) > MAX_QUERY_CHARS:
            return GuardResult(False, "query too long")
        if _INJECTION_RE.search(query):
            return GuardResult(False, "query looks like a prompt-injection or tenant-escape attempt")
        return GuardResult(True)


class OutputGuard:
    def __init__(self, blacklist: Sequence[str] = ()):
        self._terms = [t.lower() for t in blacklist if t]

    def check(self, answer: str, hit_tenants: Sequence[str], active_tenant: str) -> tuple[GuardResult, str]:
        """Return (verdict, possibly-redacted answer).

        Defence in depth: RLS and the explicit WHERE clause should make a foreign-tenant
        chunk impossible. If one ever shows up anyway, fail closed instead of answering.
        """
        if any(t != active_tenant for t in hit_tenants):
            return GuardResult(False, "cross-tenant context detected"), ""
        lowered = answer.lower()
        if any(term in lowered for term in self._terms):
            return GuardResult(False, "answer matched a blocked term"), ""
        redacted, _ = redact(answer)
        return GuardResult(True), redacted
