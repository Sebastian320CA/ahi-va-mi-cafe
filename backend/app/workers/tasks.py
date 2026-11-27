"""Background tasks executed by the RQ worker (or synchronously in tests and simple local runs)."""

import logging
import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select, text

from app.core.database import SessionLocal
from app.core.enums import MessageStatus
from app.core.observability import correlation_id_var
from app.modules.notifications.models import IncomingMessage
from app.modules.notifications.service import deliver, queue_outgoing

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 4
UNPROCESSED = (MessageStatus.RECEIVED.value, MessageStatus.QUEUED.value, MessageStatus.FAILED.value,
               MessageStatus.PROCESSING.value)


def _phone_lock(db, phone: str) -> None:
    """Serializes processing per phone number (concurrency control across worker processes)."""
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"phone:{phone}"})


def process_incoming_message(message_id: str) -> str:
    """Processes the target message and any earlier unprocessed messages of the same phone, in timestamp order."""
    from app.agent.assistant import handle_message

    with SessionLocal() as db:
        target = db.get(IncomingMessage, uuid.UUID(message_id))
        if target is None:
            return "missing"
        if target.status == MessageStatus.PROCESSED.value:
            return "already_processed"
        phone, target_ts = target.phone, target.message_timestamp
        db.rollback()

    while True:
        with SessionLocal() as db:
            _phone_lock(db, phone)
            msg = db.scalar(
                select(IncomingMessage)
                .where(IncomingMessage.phone == phone, IncomingMessage.status.in_(UNPROCESSED),
                       IncomingMessage.attempts < MAX_ATTEMPTS, IncomingMessage.message_timestamp <= target_ts)
                .order_by(IncomingMessage.message_timestamp, IncomingMessage.received_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if msg is None:
                db.commit()
                break
            correlation_id_var.set(msg.correlation_id)
            started = time.monotonic()
            msg.status = MessageStatus.PROCESSING.value
            msg.processing_started_at = datetime.now(UTC)
            msg.attempts += 1
            msg_id = msg.id
            try:
                with db.begin_nested():
                    replies = handle_message(db, msg)
                    for r in replies:
                        queue_outgoing(db, phone=msg.phone, body=r, kind="reply", in_reply_to=msg.id)
                msg.status = MessageStatus.PROCESSED.value
                msg.processed_at = datetime.now(UTC)
                msg.error = None
                msg.duration_ms = int((time.monotonic() - started) * 1000)
                db.commit()
                logger.info("message processed", extra={"fields": {"message_id": str(msg_id),
                                                                   "duration_ms": msg.duration_ms}})
            except Exception as exc:
                db.rollback()
                with SessionLocal() as db2:
                    failed = db2.get(IncomingMessage, msg_id)
                    if failed is not None:
                        failed.status = MessageStatus.FAILED.value
                        failed.attempts += 1
                        failed.error = f"{type(exc).__name__}: {str(exc)[:400]}"
                        db2.commit()
                logger.exception("message processing failed", extra={"fields": {"message_id": str(msg_id)}})
                if str(msg_id) == message_id:
                    raise
                break
    return "ok"


def send_outgoing_message(message_id: str) -> str:
    with SessionLocal() as db:
        msg = deliver(db, uuid.UUID(message_id))
        return msg.status if msg else "missing"


def recover_unprocessed_messages(older_than_seconds: int = 30) -> int:
    """Re-enqueues persisted messages whose processing never started or failed, avoiding message loss."""
    from app.core.queue import enqueue

    cutoff = datetime.now(UTC) - timedelta(seconds=older_than_seconds)
    stale_processing = datetime.now(UTC) - timedelta(minutes=10)
    with SessionLocal() as db:
        rows = list(db.scalars(
            select(IncomingMessage.id).where(
                IncomingMessage.attempts < MAX_ATTEMPTS,
                or_(
                    (IncomingMessage.status.in_((MessageStatus.RECEIVED.value, MessageStatus.QUEUED.value,
                                                 MessageStatus.FAILED.value))) & (IncomingMessage.received_at < cutoff),
                    (IncomingMessage.status == MessageStatus.PROCESSING.value)
                    & (IncomingMessage.processing_started_at < stale_processing),
                ),
            ).order_by(IncomingMessage.message_timestamp).limit(200)
        ))
    for mid in rows:
        enqueue("app.workers.tasks.process_incoming_message", str(mid), job_id=f"recover-{mid}-{int(time.time())}")
    return len(rows)


def message_stats() -> dict:
    with SessionLocal() as db:
        rows = db.execute(select(IncomingMessage.status, func.count()).group_by(IncomingMessage.status)).all()
        return {s: c for s, c in rows}
