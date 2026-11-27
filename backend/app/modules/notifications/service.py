"""Outbound messaging through a transactional outbox.

Business services create OutgoingMessage rows inside their transaction. After a successful commit the
rows are dispatched (RQ job or synchronous send). A rollback discards them, so no message is sent for an
operation that did not persist.
"""

import logging
import re
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import event, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.notifications.models import ConversationState, Notification, OutgoingMessage

logger = logging.getLogger(__name__)

OUTBOX_KEY = "outbox_ids"

DECORATIVE_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F900-\U0001F9FF\U00002B00-\U00002BFF"
    "\U0000FE00-\U0000FE0F\U0000200D\U00002190-\U000021FF\U000025A0-\U000025FF]+"
)


def strip_decorative(text: str) -> str:
    """Removes emojis and decorative symbols from any outgoing text, including LLM output."""
    return re.sub(r"[ \t]{2,}", " ", DECORATIVE_RE.sub("", text or "")).strip()


def queue_outgoing(
    db: Session, *, phone: str, body: str, kind: str, in_reply_to: uuid.UUID | None = None
) -> OutgoingMessage:
    msg = OutgoingMessage(
        phone=phone,
        body=strip_decorative(body),
        kind=kind,
        provider=get_settings().whatsapp_provider,
        in_reply_to_id=in_reply_to,
    )
    db.add(msg)
    db.flush()
    db.info.setdefault(OUTBOX_KEY, []).append(msg.id)
    return msg


def notify_user(
    db: Session,
    *,
    user_id: uuid.UUID,
    phone: str | None,
    kind: str,
    body: str,
    dedupe_key: str,
    lot_id: uuid.UUID | None = None,
) -> Notification | None:
    """Creates a notification at most once per dedupe key."""
    if not phone:
        return None
    stmt = (
        insert(Notification)
        .values(
            id=uuid.uuid4(),
            user_id=user_id,
            phone=phone,
            kind=kind,
            body=strip_decorative(body),
            dedupe_key=dedupe_key,
            lot_id=lot_id,
            created_at=datetime.now(UTC),
        )
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
        .returning(Notification.id)
    )
    new_id = db.execute(stmt).scalar()
    if new_id is None:
        return None
    notification = db.get(Notification, new_id)
    assert notification is not None
    out = queue_outgoing(db, phone=phone, body=body, kind=f"notification:{kind}")
    notification.outgoing_message_id = out.id
    return notification


def within_service_window(db: Session, phone: str) -> bool:
    state = db.scalar(select(ConversationState).where(ConversationState.phone == phone))
    if state is None or state.last_inbound_at is None:
        return False
    window = timedelta(hours=get_settings().whatsapp_service_window_hours)
    return datetime.now(UTC) - state.last_inbound_at <= window


def deliver(db: Session, message_id: uuid.UUID) -> OutgoingMessage | None:
    """Sends one outgoing message through the configured WhatsApp adapter. Idempotent."""
    from app.integrations.whatsapp.client import get_whatsapp_client
    from app.modules.notifications.metrics import record_usage

    msg = db.get(OutgoingMessage, message_id, with_for_update=True)
    if msg is None or msg.status in ("sent", "needs_template"):
        return msg
    client = get_whatsapp_client()
    settings = get_settings()
    try:
        if client.requires_service_window and not within_service_window(db, msg.phone):
            if settings.whatsapp_notification_template:
                result = client.send_template(msg.phone, settings.whatsapp_notification_template, [msg.body])
            else:
                msg.status = "needs_template"
                msg.error = "Fuera de la ventana de 24 horas y sin plantilla aprobada configurada."
                db.commit()
                return msg
        else:
            result = client.send_text(msg.phone, msg.body)
        msg.status = "sent"
        msg.provider_message_id = result
        msg.sent_at = datetime.now(UTC)
        record_usage(db, kind="whatsapp_message", provider=client.name, quantity=1, unit="message",
                     phone=msg.phone)
    except Exception as exc:  # provider errors are recorded, not raised to the caller
        logger.exception("outgoing message failed", extra={"fields": {"message_id": str(msg.id)}})
        msg.status = "failed"
        msg.error = str(exc)[:500]
    db.commit()
    return msg


def dispatch_outbox(ids: list[uuid.UUID]) -> None:
    if not ids:
        return
    settings = get_settings()
    if settings.queue_mode == "rq":
        try:
            from app.core.queue import enqueue

            for mid in ids:
                enqueue("app.workers.tasks.send_outgoing_message", str(mid), job_id=f"out-{mid}")
            return
        except Exception:
            logger.exception("enqueue of outgoing messages failed, sending synchronously")
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        for mid in ids:
            deliver(db, mid)


@event.listens_for(Session, "after_commit")
def _after_commit(session: Session) -> None:
    ids = session.info.pop(OUTBOX_KEY, [])
    if ids:
        dispatch_outbox(ids)


@event.listens_for(Session, "after_rollback")
def _after_rollback(session: Session) -> None:
    session.info.pop(OUTBOX_KEY, None)
