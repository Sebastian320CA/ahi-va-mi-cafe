import uuid
from datetime import datetime
from decimal import Decimal

from geoalchemy2 import Geometry
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, IdMixin, TimestampMixin, utcnow
from app.core.enums import AssessmentResult, LocationStatus, check_in


class ConsentRecord(IdMixin, Base):
    __tablename__ = "consent_records"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True, nullable=False
    )
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    response_text: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(String(20), default="whatsapp", nullable=False)
    source_message_id: Mapped[str | None] = mapped_column(String(120))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Producer(IdMixin, TimestampMixin, Base):
    __tablename__ = "producers"
    __table_args__ = (
        CheckConstraint("registration_status IN ('pending', 'registered')", name="ck_producer_status"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), index=True, nullable=False
    )
    exporter_org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    whatsapp_phone: Mapped[str | None] = mapped_column(String(30), index=True)
    registration_status: Mapped[str] = mapped_column(String(20), default="registered", nullable=False)
    consent_given: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    farms: Mapped[list["Farm"]] = relationship(back_populates="producer", lazy="selectin")


class Farm(IdMixin, TimestampMixin, Base):
    __tablename__ = "farms"
    __table_args__ = (CheckConstraint(check_in("location_status", LocationStatus), name="ck_farm_loc"),)

    producer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("producers.id"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    department: Mapped[str | None] = mapped_column(String(120))
    municipality: Mapped[str | None] = mapped_column(String(120))
    vereda: Mapped[str | None] = mapped_column(String(120))
    location = mapped_column(Geometry("POINT", srid=4326, spatial_index=True), nullable=True)
    location_status: Mapped[str] = mapped_column(
        String(30), default=LocationStatus.DECLARED.value, nullable=False
    )
    location_source: Mapped[str | None] = mapped_column(String(60))
    declared_area_ha: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    producer: Mapped[Producer] = relationship(back_populates="farms")
    plots: Mapped[list["Plot"]] = relationship(back_populates="farm", lazy="selectin")


class Plot(IdMixin, TimestampMixin, Base):
    """Productive parcel inside a farm. The demo uses one plot per synthetic farm."""

    __tablename__ = "plots"

    farm_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("farms.id"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    polygon = mapped_column(Geometry("POLYGON", srid=4326, spatial_index=True), nullable=True)
    polygon_source: Mapped[str | None] = mapped_column(String(120))

    farm: Mapped[Farm] = relationship(back_populates="plots")


class FarmAssessment(IdMixin, Base):
    """Preliminary environmental signal. Not a certification."""

    __tablename__ = "farm_assessments"
    __table_args__ = (CheckConstraint(check_in("result", AssessmentResult), name="ck_assessment_result"),)

    farm_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("farms.id"), index=True, nullable=False
    )
    plot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("plots.id"))
    result: Mapped[str] = mapped_column(String(40), nullable=False)
    geometry_basis: Mapped[str] = mapped_column(String(40), nullable=False)
    assessed_area_ha: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    forest_2020_overlap_ha: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    loss_after_cutoff_ha: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    sources: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    limitations: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    reasons: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    uses_synthetic_layers: Mapped[bool] = mapped_column(Boolean, nullable=False)
    rule_version: Mapped[str] = mapped_column(String(40), nullable=False)
    queried_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class GeoLayerFeature(IdMixin, Base):
    """Reference environmental layer loaded from prepared GeoJSON files (real or synthetic)."""

    __tablename__ = "geo_layer_features"

    layer: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    source: Mapped[str] = mapped_column(String(200), nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reference_date: Mapped[str | None] = mapped_column(String(40))
    resolution_m: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    properties: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    geom = mapped_column(Geometry("MULTIPOLYGON", srid=4326, spatial_index=True), nullable=False)
