"""Webhook ingestion: verify signature, persist, acknowledge, then enqueue processing.

The same function serves the real Meta webhook and the local simulator, so both use identical business logic.
"""

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import MessageStatus
from app.core.observability import correlation_id_var, new_correlation_id
from app.core.security import verify_meta_signature
from app.modules.notifications.metrics import record_usage
from app.modules.notifications.models import IncomingMessage

logger = logging.getLogger(__name__)

SUPPORTED_TYPES = {"text", "audio", "image", "location"}


class InvalidSignature(Exception):
    pass


@dataclass
class IngestResult:
    accepted: list[uuid.UUID]
    duplicates: int
    ignored: int


def parse_messages(payload: dict) -> list[dict]:
    out = []
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value") or {}
            for m in value.get("messages", []) or []:
                out.append(m)
    return out


def ingest(db: Session, raw_body: bytes, signature: str | None, provider: str) -> IngestResult:
    if not verify_meta_signature(raw_body, signature, get_settings().meta_app_secret):
        raise InvalidSignature()
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid json") from exc
    accepted: list[uuid.UUID] = []
    duplicates = ignored = 0
    for m in parse_messages(payload):
        mtype = m.get("type")
        if mtype == "voice":
            mtype = "audio"
        if mtype not in SUPPORTED_TYPES or not m.get("id") or not m.get("from"):
            ignored += 1
            continue
        try:
            ts = datetime.fromtimestamp(int(m.get("timestamp") or ""), tz=UTC)
        except (TypeError, ValueError):
            ts = datetime.now(UTC)
        stmt = (
            insert(IncomingMessage)
            .values(id=uuid.uuid4(), provider=provider, provider_message_id=str(m["id"])[:200],
                    phone="".join(ch for ch in str(m["from"]) if ch.isdigit())[:30], message_type=mtype,
                    payload=m, message_timestamp=ts, received_at=datetime.now(UTC),
                    status=MessageStatus.RECEIVED.value, attempts=0, is_late=False,
                    correlation_id=correlation_id_var.get() if correlation_id_var.get() != "-"
                    else new_correlation_id())
            .on_conflict_do_nothing(index_elements=["provider_message_id"])
            .returning(IncomingMessage.id)
        )
        new_id = db.execute(stmt).scalar()
        if new_id is None:
            duplicates += 1
            record_usage(db, kind="duplicate_message_avoided", provider=provider, quantity=1, unit="message")
        else:
            accepted.append(new_id)
    db.commit()
    return IngestResult(accepted, duplicates, ignored)


def schedule_processing(ids: list[uuid.UUID]) -> None:
    """Enqueues after the messages are safely persisted. If enqueueing fails the recovery job retries."""
    settings = get_settings()
    if settings.queue_mode == "sync":
        from app.workers.tasks import process_incoming_message

        for mid in ids:
            process_incoming_message(str(mid))
        return
    from app.core.database import SessionLocal
    from app.core.queue import enqueue

    for mid in ids:
        try:
            enqueue("app.workers.tasks.process_incoming_message", str(mid), job_id=f"in-{mid}")
            with SessionLocal() as db:
                msg = db.get(IncomingMessage, mid)
                if msg is not None and msg.status == MessageStatus.RECEIVED.value:
                    msg.status = MessageStatus.QUEUED.value
                    db.commit()
        except Exception:
            logger.exception("enqueue failed; message stays persisted for recovery",
                             extra={"fields": {"message_id": str(mid)}})
