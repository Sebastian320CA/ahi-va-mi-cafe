"""Messaging persistence: inbound messages, conversation state, pending operations, outbound messages."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, IdMixin, TimestampMixin, utcnow
from app.core.enums import MessageStatus, PendingStatus, check_in


class IncomingMessage(IdMixin, Base):
    __tablename__ = "incoming_messages"
    __table_args__ = (
        CheckConstraint(check_in("status", MessageStatus), name="ck_incoming_status"),
        Index("ix_incoming_phone_ts", "phone", "message_timestamp"),
    )

    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_message_id: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    phone: Mapped[str] = mapped_column(String(30), nullable=False)
    message_type: Mapped[str] = mapped_column(String(20), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    message_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default=MessageStatus.RECEIVED.value, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    is_late: Mapped[bool] = mapped_column(default=False, nullable=False)
    interpreted_text: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)


class ConversationState(IdMixin, TimestampMixin, Base):
    __tablename__ = "conversation_states"

    phone: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    active_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_processed_message_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    turns: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    context: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class PendingOperation(IdMixin, TimestampMixin, Base):
    """A write operation prepared by the assistant that waits for explicit human confirmation."""

    __tablename__ = "pending_operations"
    __table_args__ = (CheckConstraint(check_in("status", PendingStatus), name="ck_pending_status"),)

    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    phone: Mapped[str] = mapped_column(String(30), index=True, nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    tool_name: Mapped[str] = mapped_column(String(60), nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False)
    missing_fields: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=PendingStatus.PENDING.value, nullable=False)
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_evidence.id")
    )
    source_message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incoming_messages.id"), nullable=False
    )
    source_message_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    history: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    result: Mapped[dict | None] = mapped_column(JSONB)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OutgoingMessage(IdMixin, Base):
    __tablename__ = "outgoing_messages"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'sent', 'failed', 'needs_template')", name="ck_outgoing_status"
        ),
    )

    phone: Mapped[str] = mapped_column(String(30), index=True, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(200))
    error: Mapped[str | None] = mapped_column(Text)
    in_reply_to_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incoming_messages.id")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Notification(IdMixin, Base):
    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True, nullable=False
    )
    phone: Mapped[str] = mapped_column(String(30), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    lot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("coffee_lots.id"))
    outgoing_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("outgoing_messages.id")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class UsageRecord(IdMixin, Base):
    """Basic operational metrics for cost estimation with configurable rates."""

    __tablename__ = "usage_records"

    kind: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30))
    lot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    producer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    details: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
