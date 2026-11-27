"""Worker entrypoint: RQ worker plus a periodic recovery loop for persisted but unprocessed messages."""

import logging
import threading
import time

from rq import Worker

from app.core.config import get_settings
from app.core.observability import configure_logging
from app.core.queue import QUEUE_NAME, get_redis

logger = logging.getLogger("worker")


def recovery_loop(interval: int = 60) -> None:
    from app.workers.tasks import recover_unprocessed_messages

    while True:
        try:
            n = recover_unprocessed_messages()
            if n:
                logger.info("recovered messages", extra={"fields": {"count": n}})
        except Exception:
            logger.exception("recovery loop failed")
        time.sleep(interval)


def main() -> None:
    configure_logging(get_settings().log_level)
    threading.Thread(target=recovery_loop, daemon=True).start()
    worker = Worker([QUEUE_NAME], connection=get_redis())
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
