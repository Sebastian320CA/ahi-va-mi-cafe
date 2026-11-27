import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, IdMixin, TimestampMixin, utcnow
from app.core.enums import AlertClassification, AlertStatus, check_in


class ReconciliationAlert(IdMixin, TimestampMixin, Base):
    __tablename__ = "reconciliation_alerts"
    __table_args__ = (
        CheckConstraint(check_in("status", AlertStatus), name="ck_alert_status"),
        CheckConstraint(
            "classification IS NULL OR " + check_in("classification", AlertClassification),
            name="ck_alert_classification",
        ),
    )

    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    shipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shipments.id"), unique=True, nullable=False
    )
    lot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("coffee_lots.id"), index=True, nullable=False
    )
    exporter_org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    weight_diff_kg: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    discrepancy_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 3))
    sacks_diff: Mapped[int | None] = mapped_column(Integer)
    seal_match: Mapped[bool | None] = mapped_column(Boolean)
    state_match: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reasons: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    thresholds: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    classification: Mapped[str | None] = mapped_column(String(40))
    justification_text: Mapped[str | None] = mapped_column(Text)
    justification_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    suggested_classification: Mapped[str | None] = mapped_column(String(40))


class AlertResolution(IdMixin, Base):
    __tablename__ = "alert_resolutions"
    __table_args__ = (
        CheckConstraint(check_in("classification", AlertClassification), name="ck_resolution_class"),
    )

    alert_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reconciliation_alerts.id"), index=True, nullable=False
    )
    resolved_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    classification: Mapped[str] = mapped_column(String(40), nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
