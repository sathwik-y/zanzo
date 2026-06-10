"""Worker service: consumes the job queue and runs the processing pipeline.

Run with: python -m recall.services.worker
"""
import logging
import time

from recall.ai.gemini import build_ai_client
from recall.db import get_session_factory
from recall.instagram.client import build_client
from recall.pipeline.ai_stages import (
    make_classify_stage,
    make_embed_stage,
    make_extract_stage,
)
from recall.pipeline.fetch import make_fetch_stage
from recall.pipeline.runner import Stage, process_item
from recall.pipeline.transcribe import make_transcribe_stage
from recall.queueing import RedisQueue
from recall.storage import S3Storage

logger = logging.getLogger(__name__)


def build_stages(storage=None, ai=None) -> dict[str, Stage]:
    storage = storage or S3Storage()
    ai = ai or build_ai_client()

    _client_cache = {}

    def get_client():
        if "cl" not in _client_cache:
            _client_cache["cl"] = build_client()
        return _client_cache["cl"]

    return {
        "fetch": make_fetch_stage(storage, get_client),
        "transcribe": make_transcribe_stage(storage),
        "classify": make_classify_stage(ai, storage),
        "extract": make_extract_stage(ai),
        "embed": make_embed_stage(ai),
    }


def run_forever() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    factory = get_session_factory()
    queue = RedisQueue()
    stages = build_stages()
    logger.info("worker started; waiting for jobs")

    while True:
        try:
            item_id = queue.dequeue(timeout=5)
            if item_id is None:
                continue
            with factory() as db:
                process_item(db, item_id, stages)
        except KeyboardInterrupt:
            logger.info("worker shutting down")
            break
        except Exception:
            # process_item already parks failed items; anything that leaks
            # here is infrastructure trouble - log it and keep consuming
            logger.exception("worker loop error")
            time.sleep(3)


if __name__ == "__main__":
    run_forever()
