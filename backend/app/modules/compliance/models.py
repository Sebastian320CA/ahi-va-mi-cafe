import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, IdMixin, TimestampMixin, utcnow
from app.core.enums import CaseStatus, check_in


class DueDiligenceCase(IdMixin, TimestampMixin, Base):
    """Supporting dossier for due diligence. Not an official EUDR statement."""

    __tablename__ = "due_diligence_cases"
    __table_args__ = (CheckConstraint(check_in("status", CaseStatus), name="ck_case_status"),)

    lot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("coffee_lots.id"), unique=True, nullable=False
    )
    exporter_org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    legality_evidence: Mapped[str | None] = mapped_column(Text)
    observations: Mapped[str | None] = mapped_column(Text)
    rule_version: Mapped[str] = mapped_column(String(40), nullable=False)


class DueDiligenceReview(IdMixin, Base):
    __tablename__ = "due_diligence_reviews"

    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("due_diligence_cases.id"), index=True, nullable=False
    )
    reviewer_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(30), nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
