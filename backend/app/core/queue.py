"""Redis and RQ helpers. A single queue system is used for all background work."""

from functools import lru_cache

from redis import Redis
from rq import Queue, Retry

from app.core.config import get_settings

QUEUE_NAME = "cafe"


@lru_cache
def get_redis() -> Redis:
    return Redis.from_url(get_settings().redis_url, socket_connect_timeout=2, socket_timeout=5)


def get_queue() -> Queue:
    return Queue(QUEUE_NAME, connection=get_redis())


def enqueue(func_path: str, *args, job_id: str | None = None):
    """Enqueues with retries and exponential-like backoff. job_id makes enqueueing idempotent."""
    queue = get_queue()
    if job_id:
        existing = queue.fetch_job(job_id)
        if existing is not None and existing.get_status(refresh=True) in ("queued", "started", "deferred"):
            return existing
    return queue.enqueue(
        func_path,
        *args,
        job_id=job_id,
        retry=Retry(max=3, interval=[5, 30, 120]),
        failure_ttl=7 * 24 * 3600,
        result_ttl=3600,
    )
