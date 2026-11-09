"""The gateway's Redis token-bucket script, run against a real Redis (the gateway executes this exact file)."""
import os
import time
import uuid
from pathlib import Path

import pytest

REDIS_URL = os.environ.get("RAG_TEST_REDIS_URL")
pytestmark = pytest.mark.skipif(not REDIS_URL, reason="RAG_TEST_REDIS_URL not set")

LUA = (Path(__file__).resolve().parents[2] / "gateway/src/main/resources/scripts/token_bucket.lua").read_text()


@pytest.fixture(scope="module")
def bucket():
    import redis

    r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    script = r.register_script(LUA)

    def acquire(key, capacity=10, rate=5, cost=5):
        allowed, remaining, retry_ms = script(keys=[key], args=[capacity, rate, cost])
        return bool(allowed), remaining, retry_ms

    acquire.redis = r
    return acquire


def key():
    return f"rl:test:{uuid.uuid4().hex}"


def test_burst_up_to_capacity_then_denied_with_retry_hint(bucket):
    k = key()
    assert bucket(k)[0] and bucket(k)[0]  # 10 tokens = two requests of cost 5
    allowed, remaining, retry_ms = bucket(k)
    assert not allowed and remaining == 0
    assert 800 <= retry_ms <= 1100  # 5 tokens at 5/s


def test_tokens_refill_over_time(bucket):
    k = key()
    bucket(k), bucket(k)
    assert not bucket(k)[0]
    time.sleep(1.1)
    assert bucket(k)[0]


def test_denied_requests_do_not_consume_tokens(bucket):
    k = key()
    bucket(k), bucket(k)
    for _ in range(20):
        bucket(k)  # hammering while empty
    time.sleep(1.1)
    assert bucket(k)[0]  # still recovers on schedule


def test_buckets_are_independent_per_tenant(bucket):
    a, b = key(), key()
    bucket(a), bucket(a)
    assert not bucket(a)[0]
    assert bucket(b)[0]  # the noisy neighbour does not affect another tenant


def test_never_exceeds_capacity_after_idle(bucket):
    k = key()
    bucket(k, capacity=10, rate=1000, cost=1)
    time.sleep(0.1)  # would refill 100 tokens
    _, remaining, _ = bucket(k, capacity=10, rate=1000, cost=1)
    assert remaining <= 9


def test_idle_bucket_expires(bucket):
    k = key()
    bucket(k, capacity=10, rate=5, cost=1)
    ttl = bucket.redis.pttl(k)
    assert 0 < ttl <= 4000  # 2 x capacity/rate seconds


def test_concurrent_requests_cannot_overspend(bucket):
    from concurrent.futures import ThreadPoolExecutor

    k = key()
    with ThreadPoolExecutor(16) as pool:
        results = list(pool.map(lambda _: bucket(k, capacity=10, rate=0.001, cost=1)[0], range(60)))
    assert results.count(True) == 10  # atomic: exactly capacity many succeed
