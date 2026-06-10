import pytest

from recall.queueing import InMemoryQueue, RedisQueue


def test_in_memory_queue_fifo():
    q = InMemoryQueue()
    q.enqueue("a")
    q.enqueue("b")
    assert q.depth() == 2
    assert q.dequeue() == "a"
    assert q.dequeue() == "b"
    assert q.dequeue() is None


def test_redis_queue_round_trip():
    try:
        q = RedisQueue(name="recall:test-jobs")
        q._redis.delete("recall:test-jobs")
    except Exception:
        pytest.skip("redis not running (docker compose up -d redis)")
    q.enqueue("item-1")
    q.enqueue("item-2")
    assert q.depth() == 2
    assert q.dequeue(timeout=1) == "item-1"
    assert q.dequeue(timeout=1) == "item-2"
    assert q.dequeue(timeout=1) is None
