"""Run a single poll cycle: discover new saved/DMed media and enqueue jobs.

Useful for cron-style setups and for testing. The long-running poller is
`python -m recall.services.poller`.
"""
import logging

from recall.db import get_session_factory
from recall.instagram.client import build_client
from recall.queueing import RedisQueue
from recall.services.poller import poll_once

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

cl = build_client()
with get_session_factory()() as db:
    new = poll_once(db, RedisQueue(), cl)
    print(f"poll complete: {new} new item(s) enqueued")
