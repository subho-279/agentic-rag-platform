"""Document ingestion: validate event -> extract -> chunk -> redact PII -> embed -> store."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from psycopg.types.json import Jsonb

from ..chunking import chunk_text
from ..config import Settings
from ..db import tenant_session, validate_tenant_id, vector_literal
from ..embeddings import Embedder
from ..extract import extract_sections
from ..pii import redact

log = logging.getLogger("worker.pipeline")


@dataclass(frozen=True)
class IngestEvent:
    document_id: str
    tenant_id: str
    file_path: str  # relative to STORAGE_ROOT, e.g. "acme/<doc-uuid>/handbook.md"

    @staticmethod
    def from_dict(d: dict) -> "IngestEvent":
        return IngestEvent(
            document_id=str(d["document_id"]),
            tenant_id=validate_tenant_id(str(d["tenant_id"])),
            file_path=str(d["file_path"]),
        )


def resolve_storage_path(storage_root: str, tenant_id: str, relative: str) -> Path:
    """Resolve an event's file path, refusing traversal and files outside the tenant's own prefix.

    The Kafka event is data from another process; a forged event must not make the
    worker read another tenant's files or anything outside the storage root.
    """
    root = Path(storage_root).resolve()
    path = (root / relative).resolve()
    tenant_dir = (root / tenant_id).resolve()
    if not path.is_relative_to(tenant_dir):
        raise PermissionError("file path is outside the tenant's storage prefix")
    if not path.is_file():
        raise FileNotFoundError(f"no such file: {relative}")
    return path


def _set_status(tenant_id: str, doc_id: str, status: str, *, error: str | None = None, chunks: int = 0) -> None:
    with tenant_session(tenant_id, system=True) as conn:
        conn.execute(
            "UPDATE documents SET status = %s, error = %s, chunk_count = %s, updated_at = now() WHERE id = %s",
            (status, error, chunks, doc_id),
        )


def process_event(event: IngestEvent, settings: Settings, embedder: Embedder) -> int:
    """Process one document. Returns the number of chunks stored. Idempotent per document."""
    with tenant_session(event.tenant_id, system=True) as conn:
        row = conn.execute(
            "SELECT allowed_roles FROM documents WHERE id = %s", (event.document_id,)
        ).fetchone()
    if row is None:
        # RLS hides other tenants' rows, so this also covers a forged tenant_id/document_id pair.
        raise LookupError("document row not found for this tenant")
    allowed_roles: list[str] = list(row[0])

    _set_status(event.tenant_id, event.document_id, "PROCESSING")
    try:
        path = resolve_storage_path(settings.storage_root, event.tenant_id, event.file_path)
        records: list[tuple[int, str, dict]] = []
        redactions = 0
        for section in extract_sections(path):
            meta = {"page": section.page} if section.page is not None else {}
            for ch in chunk_text(section.text, settings.chunk_max_chars, settings.chunk_overlap_chars, meta):
                clean, counts = redact(ch.text)
                redactions += sum(counts.values())
                records.append((len(records), clean, ch.metadata))
        if not records:
            raise ValueError("no extractable text")

        vectors = embedder.embed([text for _, text, _ in records])
        with tenant_session(event.tenant_id, system=True) as conn:
            conn.execute("DELETE FROM chunks WHERE document_id = %s", (event.document_id,))
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO chunks (tenant_id, document_id, chunk_index, content, allowed_roles, embedding, metadata) "
                    "VALUES (%s, %s, %s, %s, %s, %s::vector, %s)",
                    [
                        (event.tenant_id, event.document_id, idx, text, allowed_roles, vector_literal(vec), Jsonb(meta))
                        for (idx, text, meta), vec in zip(records, vectors)
                    ],
                )
        _set_status(event.tenant_id, event.document_id, "READY", chunks=len(records))
        log.info("ingested doc=%s tenant=%s chunks=%d pii_redactions=%d", event.document_id, event.tenant_id, len(records), redactions)
        return len(records)
    except Exception as exc:
        log.exception("ingestion failed doc=%s tenant=%s", event.document_id, event.tenant_id)
        _set_status(event.tenant_id, event.document_id, "FAILED", error=str(exc)[:500])
        raise
