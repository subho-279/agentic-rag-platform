"""Regex-based PII redaction applied before embedding and again on answers.

This is a pragmatic first line of defence, not a DLP product: regexes miss
names, addresses and free-form identifiers.
"""
from __future__ import annotations

import re
from collections import Counter

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_AADHAAR = re.compile(r"(?<!\d{4}\s)\b\d{4}\s\d{4}\s\d{4}\b(?!\s\d{4})")
_CARD = re.compile(r"\b(?:\d[ -]?){13,16}\b")
_PHONE = re.compile(r"(?<![\w-])(?:\+?\d{1,3}[ -]?)?(?:\(\d{3}\)|\d{3})[ -]?\d{3}[ -]?\d{4}(?![\w-])")


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def redact(text: str) -> tuple[str, Counter]:
    counts: Counter = Counter()

    def sub(label: str, pattern: re.Pattern, s: str, check=None) -> str:
        def repl(m: re.Match) -> str:
            if check and not check(m.group(0)):
                return m.group(0)
            counts[label] += 1
            return f"[REDACTED_{label}]"

        return pattern.sub(repl, s)

    text = sub("EMAIL", _EMAIL, text)
    text = sub("CARD", _CARD, text, check=lambda s: _luhn_ok(re.sub(r"\D", "", s)))
    text = sub("SSN", _SSN, text)
    text = sub("AADHAAR", _AADHAAR, text)
    text = sub("PHONE", _PHONE, text)
    return text, counts
