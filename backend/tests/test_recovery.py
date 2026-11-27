"""Recovery of persisted-but-unprocessed messages through Redis and RQ (skipped when Redis is unavailable)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.queue import get_queue, get_redis
from app.modules.notifications.models import IncomingMessage
from app.workers.tasks import recover_unprocessed_messages


def redis_available() -> bool:
    try:
        return bool(get_redis().ping())
    except Exception:
        return False


@pytest.mark.skipif(not redis_available(), reason="Redis no disponible")
def test_recover_requeues_persisted_messages(db):
    queue = get_queue()
    queue.empty()
    old = datetime.now(UTC) - timedelta(minutes=5)
    msg = IncomingMessage(provider="simulated", provider_message_id=f"wamid.REC.{uuid.uuid4().hex}",
                          phone="573009999999", message_type="text", payload={"text": {"body": "hola"}},
                          message_timestamp=old, received_at=old, status="received", correlation_id="t")
    done = IncomingMessage(provider="simulated", provider_message_id=f"wamid.REC.{uuid.uuid4().hex}",
                           phone="573009999999", message_type="text", payload={"text": {"body": "hola"}},
                           message_timestamp=old, received_at=old, status="processed", correlation_id="t")
    db.add_all([msg, done])
    db.commit()
    assert recover_unprocessed_messages() == 1
    jobs = [queue.fetch_job(j) for j in queue.job_ids]
    assert any(j.args == (str(msg.id),) for j in jobs if j is not None)
    queue.empty()
