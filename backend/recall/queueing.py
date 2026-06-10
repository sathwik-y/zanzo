"""Job queue. Redis list locally; the protocol keeps an SQS swap trivial on AWS."""
import json
from typing import Protocol

import redis

from recall.config import get_settings


class JobQueue(Protocol):
    def enqueue(self, item_id: str) -> None: ...
    def dequeue(self, timeout: int = 5) -> str | None: ...
    def depth(self) -> int: ...


class RedisQueue:
    def __init__(self, url: str | None = None, name: str | None = None):
        settings = get_settings()
        self._redis = redis.Redis.from_url(url or settings.redis_url)
        self._name = name or settings.queue_name

    def enqueue(self, item_id: str) -> None:
        self._redis.lpush(self._name, json.dumps({"item_id": item_id}))

    def dequeue(self, timeout: int = 5) -> str | None:
        result = self._redis.brpop([self._name], timeout=timeout)
        if result is None:
            return None
        _, payload = result
        return json.loads(payload)["item_id"]

    def depth(self) -> int:
        return int(self._redis.llen(self._name))


class InMemoryQueue:
    """Test double."""

    def __init__(self):
        self.items: list[str] = []

    def enqueue(self, item_id: str) -> None:
        self.items.insert(0, item_id)

    def dequeue(self, timeout: int = 5) -> str | None:
        return self.items.pop() if self.items else None

    def depth(self) -> int:
        return len(self.items)
