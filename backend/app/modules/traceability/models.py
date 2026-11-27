import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, IdMixin, TimestampMixin, utcnow
from app.core.enums import CoffeeState, EventType, LotStatus, ShipmentStatus, check_in

KG = Numeric(12, 2)


class DocumentEvidence(IdMixin, TimestampMixin, Base):
    __tablename__ = "document_evidence"
    __table_args__ = (
        CheckConstraint(
            "status IN ('received', 'extracted', 'confirmed', 'rejected', 'failed')", name="ck_doc_status"
        ),
    )

    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(400), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(80), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), index=True
    )
    exporter_org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), index=True
    )
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    incoming_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incoming_messages.id")
    )
    provider: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="received", nullable=False)
    extracted_fields: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    confidence: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    corrections: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    transcript: Mapped[str | None] = mapped_column(Text)
    confirmed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resource_type: Mapped[str | None] = mapped_column(String(40))
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    error: Mapped[str | None] = mapped_column(Text)


class Purchase(IdMixin, TimestampMixin, Base):
    __tablename__ = "purchases"
    __table_args__ = (
        CheckConstraint("net_weight_kg > 0", name="ck_purchase_weight_positive"),
        CheckConstraint(
            "available_kg >= 0 AND available_kg <= net_weight_kg", name="ck_purchase_available_range"
        ),
        CheckConstraint(check_in("coffee_state", CoffeeState), name="ck_purchase_state"),
        CheckConstraint("status IN ('confirmed', 'corrected')", name="ck_purchase_status"),
    )

    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    producer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("producers.id"), index=True, nullable=False
    )
    farm_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("farms.id"), index=True, nullable=False
    )
    plot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("plots.id"))
    collection_center_org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), index=True, nullable=False
    )
    exporter_org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), index=True, nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    coffee_state: Mapped[str] = mapped_column(String(30), nullable=False)
    net_weight_kg: Mapped[Decimal] = mapped_column(KG, nullable=False)
    sacks: Mapped[int | None] = mapped_column(Integer)
    moisture_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    yield_factor: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    receipt_number: Mapped[str | None] = mapped_column(String(60))
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_evidence.id")
    )
    operator_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), default="confirmed", nullable=False)
    available_kg: Mapped[Decimal] = mapped_column(KG, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)


class CoffeeLot(IdMixin, TimestampMixin, Base):
    __tablename__ = "coffee_lots"
    __table_args__ = (
        CheckConstraint("initial_weight_kg > 0", name="ck_lot_initial_positive"),
        CheckConstraint("current_weight_kg >= 0", name="ck_lot_current_nonneg"),
        CheckConstraint(check_in("coffee_state", CoffeeState), name="ck_lot_state"),
        CheckConstraint(check_in("status", LotStatus), name="ck_lot_status"),
        CheckConstraint("parent_lot_id IS NULL OR parent_lot_id <> id", name="ck_lot_no_self_parent"),
    )

    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    exporter_org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), index=True, nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    custodian_org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), index=True, nullable=False
    )
    coffee_state: Mapped[str] = mapped_column(String(30), nullable=False)
    initial_weight_kg: Mapped[Decimal] = mapped_column(KG, nullable=False)
    current_weight_kg: Mapped[Decimal] = mapped_column(KG, nullable=False)
    sacks: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    parent_lot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("coffee_lots.id"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)

    compositions: Mapped[list["LotComposition"]] = relationship(back_populates="lot", lazy="selectin")


class LotComposition(IdMixin, Base):
    """Immutable record of which purchase and farm contributed how many kilograms to a lot."""

    __tablename__ = "lot_compositions"
    __table_args__ = (
        UniqueConstraint("purchase_id", name="uq_composition_purchase"),
        CheckConstraint("contributed_kg > 0", name="ck_composition_positive"),
    )

    lot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("coffee_lots.id"), index=True, nullable=False
    )
    purchase_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchases.id"), nullable=False
    )
    farm_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("farms.id"), nullable=False)
    producer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("producers.id"), index=True, nullable=False
    )
    contributed_kg: Mapped[Decimal] = mapped_column(KG, nullable=False)
    coffee_state: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    lot: Mapped[CoffeeLot] = relationship(back_populates="compositions")


class Shipment(IdMixin, TimestampMixin, Base):
    __tablename__ = "shipments"
    __table_args__ = (
        CheckConstraint("dispatched_kg > 0", name="ck_shipment_dispatched_positive"),
        CheckConstraint("received_kg IS NULL OR received_kg >= 0", name="ck_shipment_received_nonneg"),
        CheckConstraint("origin_org_id <> destination_org_id", name="ck_shipment_distinct_ends"),
        CheckConstraint(check_in("status", ShipmentStatus), name="ck_shipment_status"),
        Index(
            "uq_one_open_shipment_per_lot",
            "lot_id",
            unique=True,
            postgresql_where="status = 'in_transit'",
        ),
    )

    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    lot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("coffee_lots.id"), index=True, nullable=False
    )
    exporter_org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), index=True, nullable=False
    )
    origin_org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    destination_org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    transporter_org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id")
    )
    dispatcher_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    receiver_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    coffee_state_out: Mapped[str] = mapped_column(String(30), nullable=False)
    coffee_state_in: Mapped[str | None] = mapped_column(String(30))
    dispatched_kg: Mapped[Decimal] = mapped_column(KG, nullable=False)
    received_kg: Mapped[Decimal | None] = mapped_column(KG)
    sacks_out: Mapped[int | None] = mapped_column(Integer)
    sacks_in: Mapped[int | None] = mapped_column(Integer)
    seal_out: Mapped[str | None] = mapped_column(String(40))
    seal_in: Mapped[str | None] = mapped_column(String(40))
    vehicle_plate: Mapped[str | None] = mapped_column(String(20))
    dispatched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatch_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_evidence.id")
    )
    reception_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_evidence.id")
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    dispatch_idempotency_key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    reception_idempotency_key: Mapped[str | None] = mapped_column(String(120), unique=True)


class CustodyEvent(IdMixin, Base):
    """Append-only chain of custody. Corrections reference the original event."""

    __tablename__ = "custody_events"
    __table_args__ = (CheckConstraint(check_in("event_type", EventType), name="ck_event_type"),)

    lot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("coffee_lots.id"), index=True
    )
    purchase_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchases.id"), index=True
    )
    shipment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("shipments.id"))
    exporter_org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), index=True, nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    location_org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id")
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    coffee_state: Mapped[str | None] = mapped_column(String(30))
    quantity_kg: Mapped[Decimal | None] = mapped_column(KG)
    evidence_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_evidence.id")
    )
    corrects_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("custody_events.id")
    )
    details: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
