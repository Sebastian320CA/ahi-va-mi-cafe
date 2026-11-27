"""Core traceability rules. PostgreSQL constraints plus these deterministic checks guard data integrity.

All functions run inside the caller's transaction and never commit. Callers commit once per operation.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import (
    COFFEE_STATE_LABELS,
    CoffeeState,
    EventType,
    LotStatus,
    OrgKind,
    Role,
    ShipmentStatus,
)
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.modules.audit import service as audit
from app.modules.identity.models import Organization, User
from app.modules.identity.service import Actor, exporter_for_org, org_in_same_chain
from app.modules.notifications.service import notify_user
from app.modules.producers.models import Farm, Producer
from app.modules.reconciliation import service as reconciliation
from app.modules.reconciliation.service import fmt_kg
from app.modules.traceability.models import (
    CoffeeLot,
    CustodyEvent,
    DocumentEvidence,
    LotComposition,
    Purchase,
    Shipment,
)

TWO = Decimal("0.01")


def _kg(value) -> Decimal:
    try:
        d = Decimal(str(value)).quantize(TWO)
    except Exception as exc:
        raise ValidationFailed("El peso no es un número válido.") from exc
    if d <= 0:
        raise ValidationFailed("El peso debe ser mayor que cero.")
    return d


def _state(value: str) -> CoffeeState:
    try:
        return CoffeeState(value)
    except ValueError as exc:
        raise ValidationFailed("Estado del café no reconocido.") from exc


def _next(db: Session, seq: str) -> int:
    return int(db.execute(text(f"SELECT nextval('{seq}')")).scalar_one())


def _event(db: Session, actor: Actor, *, org_id: uuid.UUID, exporter_id: uuid.UUID, event_type: EventType,
           occurred_at: datetime, lot: CoffeeLot | None = None, purchase: Purchase | None = None,
           shipment: Shipment | None = None, state: str | None = None, qty: Decimal | None = None,
           location: uuid.UUID | None = None, document_id: uuid.UUID | None = None,
           details: dict | None = None, corrects: uuid.UUID | None = None, notes: str | None = None
           ) -> CustodyEvent:
    ev = CustodyEvent(
        lot_id=lot.id if lot else None,
        purchase_id=purchase.id if purchase else None,
        shipment_id=shipment.id if shipment else None,
        exporter_org_id=exporter_id,
        event_type=event_type.value,
        actor_user_id=actor.id,
        organization_id=org_id,
        location_org_id=location,
        occurred_at=occurred_at,
        coffee_state=state,
        quantity_kg=qty,
        evidence_document_id=document_id,
        details=details or {},
        corrects_event_id=corrects,
        notes=notes,
    )
    db.add(ev)
    db.flush()
    return ev


def _ensure_chronology(db: Session, lots: list[CoffeeLot], occurred_at: datetime) -> None:
    """A new event cannot predate the latest confirmed event of the lot (late or out-of-order data)."""
    last = last_confirmed_event(db, lots)
    # WhatsApp timestamps have one-second resolution, so comparisons are made at that granularity.
    if last is not None and occurred_at < last.occurred_at.replace(microsecond=0):
        raise ValidationFailed(
            "La fecha indicada es anterior al último evento confirmado del lote. Verifica la fecha de la "
            "planilla antes de registrarla.", code="chronology")


def _confirm_document(db: Session, document_id: uuid.UUID | None, actor: Actor, resource_type: str,
                      resource_id: uuid.UUID) -> None:
    if document_id is None:
        return
    doc = db.get(DocumentEvidence, document_id)
    if doc is None:
        raise NotFound("Documento de evidencia no encontrado.")
    doc.status = "confirmed"
    doc.confirmed_by_user_id = actor.id
    doc.confirmed_at = datetime.now(UTC)
    doc.resource_type = resource_type
    doc.resource_id = resource_id


# ---------------------------------------------------------------- purchases

@dataclass
class PurchaseInput:
    producer_id: uuid.UUID
    farm_id: uuid.UUID
    net_weight_kg: Decimal
    coffee_state: str
    occurred_at: datetime
    sacks: int | None = None
    moisture_pct: Decimal | None = None
    yield_factor: Decimal | None = None
    receipt_number: str | None = None
    document_id: uuid.UUID | None = None


def register_purchase(db: Session, actor: Actor, data: PurchaseInput, idempotency_key: str) -> Purchase:
    existing = db.scalar(select(Purchase).where(Purchase.idempotency_key == idempotency_key))
    if existing is not None:
        return existing
    center_id = actor.org_for(Role.COLLECTION_OPERATOR)
    exporter_id = exporter_for_org(db, center_id)
    producer = db.get(Producer, data.producer_id)
    farm = db.get(Farm, data.farm_id)
    if producer is None or farm is None or farm.producer_id != producer.id:
        raise ValidationFailed("La finca no corresponde al productor indicado.")
    if producer.exporter_org_id != exporter_id:
        raise Forbidden("El productor no pertenece a la cadena autorizada.")
    if not producer.consent_given:
        raise ValidationFailed("El productor aún no ha autorizado el tratamiento de datos.")
    weight = _kg(data.net_weight_kg)
    state = _state(data.coffee_state)
    if data.receipt_number:
        dup = db.scalar(select(Purchase).where(Purchase.receipt_number == data.receipt_number,
                                               Purchase.collection_center_org_id == center_id))
        if dup is not None:
            raise Conflict(f"El recibo {data.receipt_number} ya fue registrado como {dup.code}.")
    plot_id = farm.plots[0].id if len(farm.plots) == 1 else None
    purchase = Purchase(
        code=f"COM-{_next(db, 'purchase_code_seq'):04d}",
        producer_id=producer.id,
        farm_id=farm.id,
        plot_id=plot_id,
        collection_center_org_id=center_id,
        exporter_org_id=exporter_id,
        occurred_at=data.occurred_at,
        coffee_state=state.value,
        net_weight_kg=weight,
        sacks=data.sacks,
        moisture_pct=data.moisture_pct,
        yield_factor=data.yield_factor,
        receipt_number=data.receipt_number,
        document_id=data.document_id,
        operator_user_id=actor.id,
        available_kg=weight,
        idempotency_key=idempotency_key,
    )
    db.add(purchase)
    db.flush()
    _event(db, actor, org_id=center_id, exporter_id=exporter_id, event_type=EventType.PURCHASE,
           occurred_at=data.occurred_at, purchase=purchase, state=state.value, qty=weight,
           location=center_id, document_id=data.document_id,
           details={"producer": producer.name, "farm": farm.name})
    _confirm_document(db, data.document_id, actor, "purchase", purchase.id)
    audit.record(db, operation="purchase.registered", resource_type="purchase", resource_id=purchase.id,
                 actor_user_id=actor.id, organization_id=center_id,
                 details={"net_weight_kg": str(weight), "farm": farm.name})
    center = db.get(Organization, center_id)
    user = db.get(User, producer.user_id)
    notify_user(
        db, user_id=producer.user_id, phone=user.whatsapp_phone if user else producer.whatsapp_phone,
        kind="purchase_registered", dedupe_key=f"purchase_registered:{purchase.id}",
        body=(f"Registramos tu venta de {fmt_kg(weight).replace(' kg', ' kilos')} de "
              f"{COFFEE_STATE_LABELS[state]} en {center.name if center else 'el centro de acopio'}."),
    )
    return purchase


def correct_purchase_weight(db: Session, actor: Actor, purchase_id: uuid.UUID, new_weight,
                            reason: str) -> Purchase:
    """Corrections keep history: the original value stays in a correction event and the audit log."""
    purchase = db.get(Purchase, purchase_id, with_for_update=True)
    if purchase is None:
        raise NotFound("Compra no encontrada.")
    if purchase.collection_center_org_id not in actor.orgs_for(Role.COLLECTION_OPERATOR):
        raise Forbidden("Solo el centro de acopio que registró la compra puede corregirla.")
    if purchase.available_kg != purchase.net_weight_kg:
        raise Conflict("La compra ya fue asignada a un lote; registra la corrección sobre el lote.")
    weight = _kg(new_weight)
    original_event = db.scalar(select(CustodyEvent).where(
        CustodyEvent.purchase_id == purchase.id, CustodyEvent.event_type == EventType.PURCHASE.value))
    old = purchase.net_weight_kg
    purchase.net_weight_kg = weight
    purchase.available_kg = weight
    purchase.status = "corrected"
    _event(db, actor, org_id=purchase.collection_center_org_id, exporter_id=purchase.exporter_org_id,
           event_type=EventType.CORRECTION, occurred_at=datetime.now(UTC), purchase=purchase,
           state=purchase.coffee_state, qty=weight, location=purchase.collection_center_org_id,
           corrects=original_event.id if original_event else None,
           details={"field": "net_weight_kg", "old": str(old), "new": str(weight)}, notes=reason)
    audit.record(db, operation="purchase.corrected", resource_type="purchase", resource_id=purchase.id,
                 actor_user_id=actor.id, organization_id=purchase.collection_center_org_id,
                 details={"old": str(old), "new": str(weight), "reason": reason})
    return purchase


# ---------------------------------------------------------------- lots

def create_lot(db: Session, actor: Actor, purchase_ids: list[uuid.UUID], idempotency_key: str,
               occurred_at: datetime | None = None) -> CoffeeLot:
    existing = db.scalar(select(CoffeeLot).where(CoffeeLot.idempotency_key == idempotency_key))
    if existing is not None:
        return existing
    center_id = actor.org_for(Role.COLLECTION_OPERATOR)
    if not purchase_ids:
        raise ValidationFailed("Debes indicar al menos una compra.")
    if len(set(purchase_ids)) != len(purchase_ids):
        raise ValidationFailed("La misma compra aparece más de una vez.")
    purchases = list(db.scalars(
        select(Purchase).where(Purchase.id.in_(purchase_ids)).order_by(Purchase.code).with_for_update()
    ))
    if len(purchases) != len(purchase_ids):
        raise NotFound("Alguna de las compras no existe.")
    states = {p.coffee_state for p in purchases}
    if len(states) != 1:
        raise ValidationFailed("No se pueden consolidar compras de diferentes estados del café.")
    for p in purchases:
        if p.collection_center_org_id != center_id:
            raise Forbidden(f"La compra {p.code} no pertenece a tu centro de acopio.")
        if p.available_kg <= 0:
            raise Conflict(f"La compra {p.code} ya fue asignada a otro lote.")
        if p.available_kg != p.net_weight_kg:
            raise Conflict(f"La compra {p.code} tiene asignaciones parciales; el MVP consolida compras completas.")
    exporter_id = purchases[0].exporter_org_id
    total = sum((p.available_kg for p in purchases), Decimal("0")).quantize(TWO)
    sacks = sum(p.sacks or 0 for p in purchases) or None
    when = occurred_at or datetime.now(UTC)
    if when < max(p.occurred_at for p in purchases):
        raise ValidationFailed("El lote no puede crearse antes de sus compras.", code="chronology")
    lot = CoffeeLot(
        code=f"CAF-{_next(db, 'lot_code_seq'):03d}",
        exporter_org_id=exporter_id,
        organization_id=center_id,
        custodian_org_id=center_id,
        coffee_state=states.pop(),
        initial_weight_kg=total,
        current_weight_kg=total,
        sacks=sacks,
        status=LotStatus.IN_STORAGE.value,
        idempotency_key=idempotency_key,
    )
    db.add(lot)
    db.flush()
    for p in purchases:
        db.add(LotComposition(lot_id=lot.id, purchase_id=p.id, farm_id=p.farm_id, producer_id=p.producer_id,
                              contributed_kg=p.available_kg, coffee_state=p.coffee_state))
        p.available_kg = Decimal("0")
    db.flush()
    contributed = db.scalar(select(func.sum(LotComposition.contributed_kg)).where(
        LotComposition.lot_id == lot.id))
    if Decimal(contributed or 0) != lot.initial_weight_kg:
        raise Conflict("La suma de los aportes no coincide con el peso inicial del lote.")
    _event(db, actor, org_id=center_id, exporter_id=exporter_id, event_type=EventType.LOT_CREATION,
           occurred_at=when, lot=lot, state=lot.coffee_state, qty=total, location=center_id)
    _event(db, actor, org_id=center_id, exporter_id=exporter_id, event_type=EventType.CONSOLIDATION,
           occurred_at=when, lot=lot, state=lot.coffee_state, qty=total, location=center_id,
           details={"purchases": [p.code for p in purchases]})
    audit.record(db, operation="lot.created", resource_type="lot", resource_id=lot.id, actor_user_id=actor.id,
                 organization_id=center_id, details={"code": lot.code, "purchases": [p.code for p in purchases],
                                                     "total_kg": str(total)})
    return lot


def get_lot_by_code(db: Session, code: str, *, for_update: bool = False) -> CoffeeLot:
    stmt = select(CoffeeLot).where(CoffeeLot.code == code.strip().upper())
    if for_update:
        stmt = stmt.with_for_update()
    lot = db.scalar(stmt)
    if lot is None:
        raise NotFound(f"No encontré el lote {code}.")
    return lot


def ancestors(db: Session, lot: CoffeeLot) -> list[CoffeeLot]:
    """Returns [lot, parent, grandparent, ...]. Guards against cycles."""
    chain = [lot]
    seen = {lot.id}
    current = lot
    while current.parent_lot_id is not None:
        parent = db.get(CoffeeLot, current.parent_lot_id)
        if parent is None or parent.id in seen:
            raise Conflict("Genealogía inconsistente: se detectó un ciclo.")
        chain.append(parent)
        seen.add(parent.id)
        current = parent
    return chain


def descendants(db: Session, lot: CoffeeLot) -> list[CoffeeLot]:
    result: list[CoffeeLot] = []
    frontier = [lot.id]
    seen = {lot.id}
    while frontier:
        children = list(db.scalars(select(CoffeeLot).where(CoffeeLot.parent_lot_id.in_(frontier))))
        frontier = []
        for c in children:
            if c.id in seen:
                raise Conflict("Genealogía inconsistente: se detectó un ciclo.")
            seen.add(c.id)
            result.append(c)
            frontier.append(c.id)
    return result


def origin_compositions(db: Session, lot: CoffeeLot) -> list[LotComposition]:
    root = ancestors(db, lot)[-1]
    return list(db.scalars(select(LotComposition).where(LotComposition.lot_id == root.id)))


def lot_family(db: Session, lot: CoffeeLot) -> list[CoffeeLot]:
    root = ancestors(db, lot)[-1]
    return [root, *descendants(db, root)]


def _notify_lot_producers(db: Session, lot: CoffeeLot, kind: str, body: str, key_suffix: str) -> None:
    for comp in origin_compositions(db, lot):
        producer = db.get(Producer, comp.producer_id)
        if producer is None:
            continue
        user = db.get(User, producer.user_id)
        notify_user(db, user_id=producer.user_id, phone=user.whatsapp_phone if user else None, kind=kind,
                    body=body, dedupe_key=f"{kind}:{key_suffix}:{producer.user_id}", lot_id=lot.id)


# ---------------------------------------------------------------- shipments

@dataclass
class DispatchInput:
    lot_code: str
    destination_org_id: uuid.UUID
    dispatched_kg: Decimal
    coffee_state: str
    occurred_at: datetime
    sacks: int | None = None
    seal: str | None = None
    vehicle_plate: str | None = None
    transporter_org_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None


def register_dispatch(db: Session, actor: Actor, data: DispatchInput, idempotency_key: str) -> Shipment:
    existing = db.scalar(select(Shipment).where(Shipment.dispatch_idempotency_key == idempotency_key))
    if existing is not None:
        return existing
    actor.require(Role.COLLECTION_OPERATOR, Role.MILL_OPERATOR)
    lot = get_lot_by_code(db, data.lot_code, for_update=True)
    origin = lot.custodian_org_id
    if origin not in actor.orgs_for(Role.COLLECTION_OPERATOR, Role.MILL_OPERATOR):
        raise Forbidden(f"El lote {lot.code} no se encuentra en tu organización.")
    if lot.status != LotStatus.IN_STORAGE.value:
        raise Conflict(f"El lote {lot.code} no está disponible para despacho (estado {lot.status}).")
    if not org_in_same_chain(db, data.destination_org_id, lot.exporter_org_id):
        raise Forbidden("El destino no pertenece a la cadena autorizada.")
    if data.destination_org_id == origin:
        raise ValidationFailed("El destino debe ser distinto del origen.")
    state = _state(data.coffee_state)
    if state.value != lot.coffee_state:
        raise ValidationFailed(
            f"El lote está en {COFFEE_STATE_LABELS[CoffeeState(lot.coffee_state)]} y el despacho indica "
            f"{COFFEE_STATE_LABELS[state]}. Confirma el estado del café.")
    weight = _kg(data.dispatched_kg)
    if weight > lot.current_weight_kg:
        raise Conflict(f"No puedes despachar {fmt_kg(weight)}: el lote tiene {fmt_kg(lot.current_weight_kg)}.")
    _ensure_chronology(db, lot_family(db, lot), data.occurred_at)
    shipment = Shipment(
        code=f"TRA-{_next(db, 'shipment_code_seq'):03d}",
        lot_id=lot.id,
        exporter_org_id=lot.exporter_org_id,
        origin_org_id=origin,
        destination_org_id=data.destination_org_id,
        transporter_org_id=data.transporter_org_id,
        dispatcher_user_id=actor.id,
        coffee_state_out=state.value,
        dispatched_kg=weight,
        sacks_out=data.sacks,
        seal_out=data.seal,
        vehicle_plate=data.vehicle_plate,
        dispatched_at=data.occurred_at,
        dispatch_document_id=data.document_id,
        status=ShipmentStatus.IN_TRANSIT.value,
        dispatch_idempotency_key=idempotency_key,
    )
    db.add(shipment)
    db.flush()
    lot.status = LotStatus.IN_TRANSIT.value
    lot.current_weight_kg = weight
    if data.sacks is not None:
        lot.sacks = data.sacks
    _event(db, actor, org_id=origin, exporter_id=lot.exporter_org_id, event_type=EventType.DISPATCH,
           occurred_at=data.occurred_at, lot=lot, shipment=shipment, state=state.value, qty=weight,
           location=origin, document_id=data.document_id,
           details={"destination": str(data.destination_org_id), "sacks": data.sacks, "seal": data.seal})
    _confirm_document(db, data.document_id, actor, "shipment", shipment.id)
    audit.record(db, operation="shipment.dispatched", resource_type="shipment", resource_id=shipment.id,
                 actor_user_id=actor.id, organization_id=origin, details={"lot": lot.code, "kg": str(weight)})
    origin_org = db.get(Organization, origin)
    dest = db.get(Organization, data.destination_org_id)
    if origin_org and origin_org.kind == OrgKind.COLLECTION_CENTER.value and dest:
        _notify_lot_producers(db, lot, "lot_departed",
                              f"Tu café salió de {origin_org.name} rumbo a {dest.name}.", str(shipment.id))
    return shipment


@dataclass
class ReceptionInput:
    lot_code: str
    received_kg: Decimal
    coffee_state: str
    occurred_at: datetime
    sacks: int | None = None
    seal: str | None = None
    document_id: uuid.UUID | None = None
    shipment_code: str | None = None


def register_reception(db: Session, actor: Actor, data: ReceptionInput, idempotency_key: str) -> Shipment:
    """Reception is recorded independently by the destination. A discrepancy never blocks it."""
    existing = db.scalar(select(Shipment).where(Shipment.reception_idempotency_key == idempotency_key))
    if existing is not None:
        return existing
    actor.require(Role.MILL_OPERATOR, Role.PORT_OPERATOR, Role.COLLECTION_OPERATOR)
    lot = get_lot_by_code(db, data.lot_code, for_update=True)
    stmt = select(Shipment).where(Shipment.lot_id == lot.id, Shipment.status == ShipmentStatus.IN_TRANSIT.value)
    if data.shipment_code:
        stmt = stmt.where(Shipment.code == data.shipment_code.upper())
    shipment = db.scalar(stmt.with_for_update())
    if shipment is None:
        raise Conflict(f"No hay un despacho en tránsito para el lote {lot.code}.")
    if shipment.destination_org_id not in actor.orgs_for(Role.MILL_OPERATOR, Role.PORT_OPERATOR,
                                                         Role.COLLECTION_OPERATOR):
        raise Forbidden("Solo la organización de destino puede registrar la recepción.")
    if shipment.dispatcher_user_id == actor.id:
        raise Forbidden("La recepción debe registrarla una persona distinta de quien despachó.")
    received = Decimal(str(data.received_kg)).quantize(TWO)
    if received < 0:
        raise ValidationFailed("El peso recibido no puede ser negativo.")
    state = _state(data.coffee_state)
    if data.occurred_at < shipment.dispatched_at.replace(microsecond=0):
        raise ValidationFailed("La fecha de recepción es anterior a la fecha de despacho.", code="chronology")
    settings = get_settings()
    result = reconciliation.reconcile(
        dispatched_kg=shipment.dispatched_kg, received_kg=received, sacks_out=shipment.sacks_out,
        sacks_in=data.sacks, seal_out=shipment.seal_out, seal_in=data.seal, state_out=shipment.coffee_state_out,
        state_in=state.value, pct_threshold=settings.alert_weight_pct_threshold,
        sack_tolerance=settings.alert_sack_tolerance)
    shipment.received_kg = received
    shipment.sacks_in = data.sacks
    shipment.seal_in = data.seal
    shipment.coffee_state_in = state.value
    shipment.receiver_user_id = actor.id
    shipment.received_at = data.occurred_at
    shipment.reception_document_id = data.document_id
    shipment.reception_idempotency_key = idempotency_key
    shipment.status = (ShipmentStatus.DISCREPANCY if result.requires_alert else ShipmentStatus.RECONCILED).value
    lot.custodian_org_id = shipment.destination_org_id
    lot.status = LotStatus.IN_STORAGE.value
    lot.current_weight_kg = received
    lot.coffee_state = state.value
    if data.sacks is not None:
        lot.sacks = data.sacks
    _event(db, actor, org_id=shipment.destination_org_id, exporter_id=lot.exporter_org_id,
           event_type=EventType.RECEPTION, occurred_at=data.occurred_at, lot=lot, shipment=shipment,
           state=state.value, qty=received, location=shipment.destination_org_id, document_id=data.document_id,
           details={"sacks": data.sacks, "seal": data.seal, "reconciliation": result.reasons})
    _confirm_document(db, data.document_id, actor, "shipment", shipment.id)
    audit.record(db, operation="shipment.received", resource_type="shipment", resource_id=shipment.id,
                 actor_user_id=actor.id, organization_id=shipment.destination_org_id,
                 details={"lot": lot.code, "kg": str(received), "reasons": result.reasons})
    if result.requires_alert:
        alert = reconciliation.create_alert_for_shipment(db, shipment, result)
        reconciliation.request_justification(db, alert, shipment)
    dest = db.get(Organization, shipment.destination_org_id)
    if dest is not None:
        kind = "lot_arrived_port" if dest.kind == OrgKind.PORT.value else "lot_arrived"
        _notify_lot_producers(db, lot, kind, f"El lote que contiene tu café llegó a {dest.name}.",
                              str(shipment.id))
    return shipment


# ---------------------------------------------------------------- transformation

@dataclass
class TransformationInput:
    lot_code: str
    input_kg: Decimal
    output_kg: Decimal
    output_state: str
    occurred_at: datetime
    document_id: uuid.UUID | None = None
    sacks: int | None = None


def register_transformation(db: Session, actor: Actor, data: TransformationInput,
                            idempotency_key: str) -> CoffeeLot:
    """Dry parchment to green coffee. The weight reduction is a transformation, never a logistic loss.

    transformation_yield_pct = output_kg / input_kg * 100. This differs from the coffee "factor de
    rendimiento", which is the kg of dry parchment needed to obtain 70 kg of exportable green coffee.
    """
    existing = db.scalar(select(CoffeeLot).where(CoffeeLot.idempotency_key == idempotency_key))
    if existing is not None:
        return existing
    mill_id = actor.org_for(Role.MILL_OPERATOR)
    source = get_lot_by_code(db, data.lot_code, for_update=True)
    if source.custodian_org_id != mill_id:
        raise Forbidden(f"El lote {source.code} no se encuentra en tu trilladora.")
    if source.status != LotStatus.IN_STORAGE.value:
        raise Conflict(f"El lote {source.code} no está disponible para transformación.")
    if source.coffee_state != CoffeeState.DRY_PARCHMENT.value:
        raise ValidationFailed("La transformación del MVP requiere café pergamino seco como entrada.")
    out_state = _state(data.output_state)
    if out_state != CoffeeState.GREEN:
        raise ValidationFailed("La salida de la trilla debe ser café verde.")
    input_kg = _kg(data.input_kg)
    output_kg = _kg(data.output_kg)
    if input_kg != source.current_weight_kg:
        raise ValidationFailed(
            f"El peso de entrada ({fmt_kg(input_kg)}) no coincide con el peso actual del lote "
            f"({fmt_kg(source.current_weight_kg)}). El MVP transforma el lote completo.")
    if output_kg >= input_kg:
        raise ValidationFailed("El peso de salida debe ser menor que el de entrada.")
    _ensure_chronology(db, lot_family(db, source), data.occurred_at)
    yield_pct = (output_kg / input_kg * 100).quantize(TWO)
    child = CoffeeLot(
        code=f"{source.code}-V",
        exporter_org_id=source.exporter_org_id,
        organization_id=mill_id,
        custodian_org_id=mill_id,
        coffee_state=out_state.value,
        initial_weight_kg=output_kg,
        current_weight_kg=output_kg,
        sacks=data.sacks,
        status=LotStatus.IN_STORAGE.value,
        parent_lot_id=source.id,
        idempotency_key=idempotency_key,
    )
    db.add(child)
    db.flush()
    ancestors(db, child)  # cycle guard
    source.status = LotStatus.TRANSFORMED.value
    source.current_weight_kg = Decimal("0")
    details = {"input_state": source.coffee_state, "input_kg": str(input_kg), "output_state": out_state.value,
               "output_kg": str(output_kg), "transformation_yield_pct": str(yield_pct),
               "weight_reduction_kg": str(input_kg - output_kg), "source_lot": source.code,
               "output_lot": child.code, "is_logistic_loss": False,
               "note": "Rendimiento de transformación registrado; no constituye pérdida logística."}
    for target, qty, state in ((source, input_kg, source.coffee_state), (child, output_kg, out_state.value)):
        _event(db, actor, org_id=mill_id, exporter_id=source.exporter_org_id, event_type=EventType.TRANSFORMATION,
               occurred_at=data.occurred_at, lot=target, state=state, qty=qty, location=mill_id,
               document_id=data.document_id, details=details)
    _confirm_document(db, data.document_id, actor, "lot", child.id)
    audit.record(db, operation="lot.transformed", resource_type="lot", resource_id=child.id, actor_user_id=actor.id,
                 organization_id=mill_id, details=details)
    return child


# ---------------------------------------------------------------- queries

def last_confirmed_event(db: Session, lots: list[CoffeeLot]) -> CustodyEvent | None:
    ids = [lot.id for lot in lots]
    return db.scalar(
        select(CustodyEvent)
        .where(CustodyEvent.lot_id.in_(ids), CustodyEvent.event_type != EventType.CORRECTION.value)
        .order_by(CustodyEvent.occurred_at.desc(), CustodyEvent.confirmed_at.desc())
        .limit(1)
    )


def producer_coffee_status(db: Session, producer: Producer) -> list[dict]:
    """For each purchase of the producer, the latest confirmed logistic event of the lot family."""
    out = []
    purchases = list(db.scalars(select(Purchase).where(Purchase.producer_id == producer.id)
                                .order_by(Purchase.occurred_at.desc()).limit(5)))
    for p in purchases:
        comp = db.scalar(select(LotComposition).where(LotComposition.purchase_id == p.id))
        item: dict = {"purchase": p, "lot": None, "event": None, "location": None, "open_shipment": None}
        if comp is not None:
            root = db.get(CoffeeLot, comp.lot_id)
            assert root is not None
            family = lot_family(db, root)
            event = last_confirmed_event(db, family)
            current = max(family, key=lambda lot: lot.created_at)
            item.update(lot=current, event=event)
            if event and event.location_org_id:
                item["location"] = db.get(Organization, event.location_org_id)
            if event and event.event_type == EventType.DISPATCH.value and event.shipment_id:
                shp = db.get(Shipment, event.shipment_id)
                item["open_shipment"] = shp
                if shp:
                    item["destination"] = db.get(Organization, shp.destination_org_id)
        out.append(item)
    return out
