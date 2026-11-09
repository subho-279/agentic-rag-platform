"""Worker consumer-loop behaviour with a fake Kafka consumer (no broker needed)."""
import json

import pytest

from ragplatform.config import Settings
from ragplatform.embeddings import HashEmbedder
from ragplatform.worker.main import handle_message, run

S = Settings()
E = HashEmbedder(8)
GOOD = json.dumps({"document_id": "d1", "tenant_id": "acme", "file_path": "acme/d1/a.md"}).encode()


class Msg:
    def __init__(self, value, error=None):
        self._v, self._e = value, error

    def value(self):
        return self._v

    def error(self):
        return self._e


class FakeConsumer:
    def __init__(self, msgs, log):
        self.msgs, self.log = list(msgs), log

    def poll(self, _timeout):
        return self.msgs.pop(0) if self.msgs else None

    def commit(self, message, asynchronous):
        assert asynchronous is False
        self.log.append(("commit", message.value()))


def drive(msgs, process):
    log = []
    consumer = FakeConsumer(msgs, log)

    def traced(event, *_):
        log.append(("process", event.document_id))
        return process(event)

    run(consumer, S, E, should_stop=lambda: not consumer.msgs, process=traced, sleep=lambda _s: None)
    return log


def test_commit_happens_after_processing():
    log = drive([Msg(GOOD)], lambda e: 1)
    assert log == [("process", "d1"), ("commit", GOOD)]


def test_malformed_payload_is_committed_and_skipped():
    bad = [Msg(b"not json"), Msg(json.dumps({"tenant_id": "a b", "document_id": "x", "file_path": "y"}).encode()), Msg(GOOD)]
    log = drive(bad, lambda e: 1)
    assert [x[0] for x in log] == ["commit", "commit", "process", "commit"]  # poison messages never block the partition


def test_permanent_error_is_not_retried():
    calls = []

    def boom(e):
        calls.append(1)
        raise PermissionError("outside tenant prefix")

    drive([Msg(GOOD)], boom)
    assert len(calls) == 1


def test_transient_error_is_retried_then_succeeds():
    attempts = []

    def flaky(e):
        attempts.append(1)
        if len(attempts) < 3:
            raise ConnectionError("db restarting")

    log = drive([Msg(GOOD)], flaky)
    assert len(attempts) == 3 and log[-1][0] == "commit"


def test_transient_error_gives_up_after_max_attempts_and_still_commits():
    attempts = []

    def down(e):
        attempts.append(1)
        raise ConnectionError("db down")

    log = drive([Msg(GOOD), Msg(GOOD)], down)
    assert len(attempts) == 6  # 3 attempts x 2 messages
    assert [x[0] for x in log].count("commit") == 2


def test_handle_message_return_values():
    assert handle_message(GOOD, S, E, process=lambda *a: None) is True
    assert handle_message(b"{}", S, E, process=lambda *a: None) is False


def test_kafka_error_messages_are_skipped_without_commit():
    class Err:
        def code(self):
            return -1

    log = drive([Msg(None, error=Err())], lambda e: 1)
    assert log == []
