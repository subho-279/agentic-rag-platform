"""Structure-aware chunking: split on blank lines / headings, pack up to a size, overlap on overflow."""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Chunk:
    index: int
    text: str
    metadata: dict = field(default_factory=dict)


_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+\S")


def _split_blocks(text: str) -> list[str]:
    """Paragraph blocks; a markdown heading always starts a new block."""
    blocks: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            if current:
                blocks.append("\n".join(current).strip())
                current = []
            continue
        if _HEADING_RE.match(line) and current:
            blocks.append("\n".join(current).strip())
            current = []
        current.append(line)
    if current:
        blocks.append("\n".join(current).strip())
    return [b for b in blocks if b]


def _hard_split(block: str, max_chars: int, overlap: int) -> list[str]:
    if len(block) <= max_chars:
        return [block]
    pieces, start = [], 0
    step = max(1, max_chars - overlap)
    while start < len(block):
        pieces.append(block[start : start + max_chars].strip())
        if start + max_chars >= len(block):
            break
        start += step
    return [p for p in pieces if p]


def chunk_text(text: str, max_chars: int = 1000, overlap: int = 150, metadata: dict | None = None) -> list[Chunk]:
    if overlap >= max_chars:
        raise ValueError("overlap must be smaller than max_chars")
    packed: list[str] = []
    buf = ""
    for block in _split_blocks(text):
        for piece in _hard_split(block, max_chars, overlap):
            if buf and len(buf) + 2 + len(piece) > max_chars:
                packed.append(buf)
                buf = piece
            else:
                buf = f"{buf}\n\n{piece}" if buf else piece
    if buf:
        packed.append(buf)
    base = metadata or {}
    return [Chunk(index=i, text=t, metadata=dict(base)) for i, t in enumerate(packed)]
