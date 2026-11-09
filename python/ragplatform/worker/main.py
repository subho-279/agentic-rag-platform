"""Kafka consumer entrypoint for the ingestion worker (run several for horizontal scale)."""
from __future__ import annotations

import json
import logging
import signal
import sys
import time
from typing import Any, Callable

from confluent_kafka import Consumer, KafkaError

from ..config import Settings, get_settings
from ..embeddings import Embedder, build_embedder
from .pipeline import IngestEvent, process_event

log = logging.getLogger("worker")

# Errors that retrying cannot fix: bad payload, forged tenant/path, missing row or file, unreadable content.
PERMANENT_ERRORS = (ValueError, TypeError, PermissionError, LookupError, FileNotFoundError)
MAX_ATTEMPTS = 3


def handle_message(
    raw: bytes | str,
    settings: Settings,
    embedder: Embedder,
    *,
    attempts: int = MAX_ATTEMPTS,
    sleep: Callable[[float], None] = time.sleep,
    process: Callable[..., Any] = process_event,
) -> bool:
    """Process one Kafka message. Returns True if the document was ingested.

    Permanent errors are dropped immediately (the pipeline has already marked the document FAILED).
    Anything else (database restart, network blip) is retried with backoff before giving up.
    """
    try:
        event = IngestEvent.from_dict(json.loads(raw))
    except PERMANENT_ERRORS:
        log.exception("dropping malformed ingest event")
        return False
    for attempt in range(1, attempts + 1):
        try:
            process(event, settings, embedder)
            return True
        except PERMANENT_ERRORS:
            log.warning("permanent failure for doc=%s; not retrying", event.document_id)
            return False
        except Exception:
            log.exception("transient failure for doc=%s (attempt %d/%d)", event.document_id, attempt, attempts)
            if attempt < attempts:
                sleep(2**attempt)
    return False


def run(
    consumer: Any,
    settings: Settings,
    embedder: Embedder,
    should_stop: Callable[[], bool] = lambda: False,
    **handler_kwargs: Any,
) -> None:
    """Poll -> handle -> commit. The offset is committed only after handling finished, so a crash
    mid-document re-delivers it (ingestion is idempotent per document)."""
    while not should_stop():
        msg = consumer.poll(1.0)
        if msg is None:
            continue
        err = msg.error()
        if err:
            # The topic is auto-created on first publish, so "unknown topic" at startup is expected.
            if err.code() not in (KafkaError._PARTITION_EOF, KafkaError.UNKNOWN_TOPIC_OR_PART):
                log.error("kafka error: %s", err)
            continue
        handle_message(msg.value(), settings, embedder, **handler_kwargs)
        consumer.commit(message=msg, asynchronous=False)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    embedder = build_embedder(settings)
    consumer = Consumer(
        {
            "bootstrap.servers": settings.kafka_bootstrap,
            "group.id": settings.kafka_group,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )
    consumer.subscribe([settings.kafka_topic])

    running = True

    def stop(*_: Any) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    log.info("worker started topic=%s group=%s embedder=%s", settings.kafka_topic, settings.kafka_group, settings.embedding_provider)
    try:
        run(consumer, settings, embedder, should_stop=lambda: not running)
    finally:
        consumer.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
