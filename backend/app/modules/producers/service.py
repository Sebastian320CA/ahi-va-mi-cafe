import uuid
from datetime import UTC, datetime
from decimal import Decimal

from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import LocationStatus, Role
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.modules.audit import service as audit
from app.modules.identity.models import Membership, User
from app.modules.identity.service import Actor, exporter_for_org, find_org_by_code
from app.modules.producers.models import ConsentRecord, Farm, Plot, Producer

CONSENT_TEXT = (
    "Para registrarte necesitamos tu autorización para tratar tus datos personales (nombre, número de "
    "WhatsApp, finca y ubicación) con el fin de registrar la trazabilidad de tu café y enviarte información "
    "sobre su recorrido, conforme a la Ley 1581 de 2012. Tus datos no se usan para entrenar modelos y puedes "
    "solicitar su consulta, corrección o eliminación en cualquier momento."
)


def validate_coordinates(lat: float, lon: float) -> None:
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValidationFailed("Las coordenadas no son válidas.")
    # Rough bounding box of Colombia (continental and insular). Locations outside are rejected for review.
    if not (-4.3 <= lat <= 13.5 and -82.0 <= lon <= -66.8):
        raise ValidationFailed("La ubicación está fuera de Colombia. Verifica la ubicación compartida.")


def register_producer(
    db: Session,
    *,
    phone: str,
    name: str,
    farm_name: str,
    consent_accepted: bool,
    consent_response: str,
    source_message_id: str | None,
    municipality: str | None = None,
    vereda: str | None = None,
    department: str | None = None,
    org_code: str | None = None,
) -> Producer:
    name = (name or "").strip()
    farm_name = (farm_name or "").strip()
    if not name or not farm_name:
        raise ValidationFailed("Necesito tu nombre y el nombre de tu finca.")
    if not consent_accepted:
        raise ValidationFailed("Sin autorización de tratamiento de datos no podemos registrar información.")
    org = find_org_by_code(db, org_code or get_settings().default_producer_org_code)
    if org is None:
        raise NotFound("No se encontró la organización de vinculación configurada.")
    exporter_id = exporter_for_org(db, org.id)
    # Shared family phones: a new person on a known phone is a new user, never merged by phone alone.
    for u in db.scalars(select(User).where(User.whatsapp_phone == phone)):
        if u.full_name.strip().lower() == name.lower():
            existing = db.scalar(select(Producer).where(Producer.user_id == u.id))
            if existing is not None:
                raise Conflict(f"{name} ya está registrado con este número.")
    user = User(full_name=name, whatsapp_phone=phone)
    db.add(user)
    db.flush()
    db.add(Membership(user_id=user.id, organization_id=org.id, role=Role.PRODUCER.value))
    db.add(ConsentRecord(user_id=user.id, version=get_settings().consent_version, accepted=True,
                         response_text=consent_response[:500], source_message_id=source_message_id))
    producer = Producer(user_id=user.id, organization_id=org.id, exporter_org_id=exporter_id, name=name,
                        whatsapp_phone=phone, consent_given=True, registration_status="registered")
    db.add(producer)
    db.flush()
    farm = Farm(producer_id=producer.id, name=farm_name, department=department or "Huila",
                municipality=municipality, vereda=vereda, location_status=LocationStatus.DECLARED.value)
    db.add(farm)
    db.flush()
    db.add(Plot(farm_id=farm.id, name=f"{farm_name} - parcela principal"))
    audit.record(db, operation="producer.registered", resource_type="producer", resource_id=producer.id,
                 actor_user_id=user.id, organization_id=org.id,
                 details={"farm": farm_name, "consent_version": get_settings().consent_version})
    return producer


def register_farm_location(db: Session, actor: Actor, farm_id: uuid.UUID, lat: float, lon: float,
                           source: str = "whatsapp_location") -> Farm:
    validate_coordinates(lat, lon)
    farm = db.get(Farm, farm_id, with_for_update=True)
    if farm is None:
        raise NotFound("Finca no encontrada.")
    producer = db.get(Producer, farm.producer_id)
    if producer is None or (producer.user_id != actor.id and not actor.is_admin):
        raise NotFound("Finca no encontrada.")
    old = None
    if farm.location is not None:
        old = db.scalar(select(Farm.location.ST_AsText()).where(Farm.id == farm.id))
    farm.location = from_shape(Point(lon, lat), srid=4326)
    farm.location_status = LocationStatus.PENDING_VERIFICATION.value
    farm.location_source = source
    audit.record(db, operation="farm.location_shared", resource_type="farm", resource_id=farm.id,
                 actor_user_id=actor.id, details={"lat": lat, "lon": lon, "previous": old,
                                                  "note": "Punto compartido; no representa linderos."})
    return farm


def review_farm_location(db: Session, actor: Actor, farm_id: uuid.UUID, notes: str) -> Farm:
    actor.require(Role.COMPLIANCE, Role.EXPORTER, Role.ADMIN)
    farm = db.get(Farm, farm_id, with_for_update=True)
    if farm is None:
        raise NotFound("Finca no encontrada.")
    producer = db.get(Producer, farm.producer_id)
    assert producer is not None
    if not actor.is_admin and producer.exporter_org_id not in actor.orgs_for(Role.COMPLIANCE, Role.EXPORTER):
        raise NotFound("Finca no encontrada.")
    if farm.location is None:
        raise ValidationFailed("La finca no tiene ubicación para revisar.")
    farm.location_status = LocationStatus.REVIEWED.value
    audit.record(db, operation="farm.location_reviewed", resource_type="farm", resource_id=farm.id,
                 actor_user_id=actor.id, organization_id=producer.exporter_org_id, details={"notes": notes})
    return farm


def producer_for_user(db: Session, user_id: uuid.UUID) -> Producer | None:
    return db.scalar(select(Producer).where(Producer.user_id == user_id))


def find_producer_by_name(db: Session, exporter_id: uuid.UUID, name: str) -> list[Producer]:
    pattern = f"%{name.strip()}%"
    return list(db.scalars(select(Producer).where(Producer.exporter_org_id == exporter_id,
                                                  Producer.name.ilike(pattern))))


def find_farm(db: Session, producer: Producer, farm_name: str | None) -> Farm | None:
    farms = producer.farms
    if farm_name:
        for f in farms:
            if f.name.strip().lower() == farm_name.strip().lower():
                return f
        for f in farms:
            if farm_name.strip().lower() in f.name.lower():
                return f
        return None
    return farms[0] if len(farms) == 1 else None


def utc_now() -> datetime:
    return datetime.now(UTC)


def dec(v) -> Decimal | None:
    return None if v is None else Decimal(str(v))
