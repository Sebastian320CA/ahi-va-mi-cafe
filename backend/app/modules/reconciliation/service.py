"""Deterministic reconciliation of shipments and human-governed alert lifecycle."""

import uuid
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import AlertClassification, AlertStatus, Role, ShipmentStatus
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.modules.audit import service as audit
from app.modules.identity.models import User
from app.modules.identity.service import Actor, require_chain_access
from app.modules.reconciliation.models import AlertResolution, ReconciliationAlert
from app.modules.traceability.models import Shipment


@dataclass
class ReconciliationResult:
    state_match: bool
    weight_diff_kg: Decimal | None
    discrepancy_pct: Decimal | None
    sacks_diff: int | None
    seal_match: bool | None
    reasons: list[str] = field(default_factory=list)

    @property
    def requires_alert(self) -> bool:
        return bool(self.reasons)


def reconcile(
    *,
    dispatched_kg: Decimal,
    received_kg: Decimal,
    sacks_out: int | None,
    sacks_in: int | None,
    seal_out: str | None,
    seal_in: str | None,
    state_out: str,
    state_in: str,
    pct_threshold: Decimal,
    sack_tolerance: int,
) -> ReconciliationResult:
    """Pure function. difference = dispatched - received (positive means shortage)."""
    if dispatched_kg is None or Decimal(dispatched_kg) <= 0:
        raise ValidationFailed("El peso despachado debe ser positivo.")
    dispatched = Decimal(dispatched_kg)
    received = Decimal(received_kg)
    reasons: list[str] = []
    state_match = state_out == state_in
    diff: Decimal | None = None
    pct: Decimal | None = None
    if state_match:
        diff = (dispatched - received).quantize(Decimal("0.01"))
        pct = (diff / dispatched * Decimal("100")).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        if abs(pct) > pct_threshold:
            reasons.append("faltante_peso" if diff > 0 else "excedente_peso")
    else:
        reasons.append("estado_distinto")
    sacks_diff = None
    if sacks_out is not None and sacks_in is not None:
        sacks_diff = sacks_out - sacks_in
        if abs(sacks_diff) > sack_tolerance:
            reasons.append("diferencia_sacos")
    seal_match = None
    if seal_out is not None and seal_in is not None:
        seal_match = seal_out.strip().upper() == seal_in.strip().upper()
        if not seal_match:
            reasons.append("sello_distinto")
    return ReconciliationResult(state_match, diff, pct, sacks_diff, seal_match, reasons)


def create_alert_for_shipment(db: Session, shipment: Shipment, result: ReconciliationResult) -> ReconciliationAlert:
    settings = get_settings()
    seq: int = db.execute(text("SELECT nextval('alert_code_seq')")).scalar_one()
    alert = ReconciliationAlert(
        code=f"ALR-{seq:03d}",
        shipment_id=shipment.id,
        lot_id=shipment.lot_id,
        exporter_org_id=shipment.exporter_org_id,
        status=AlertStatus.OPEN.value,
        weight_diff_kg=result.weight_diff_kg,
        discrepancy_pct=result.discrepancy_pct,
        sacks_diff=result.sacks_diff,
        seal_match=result.seal_match,
        state_match=result.state_match,
        reasons=result.reasons,
        thresholds={
            "weight_pct": str(settings.alert_weight_pct_threshold),
            "sacks": settings.alert_sack_tolerance,
            "note": "Umbrales de demostración configurables, no estándares oficiales.",
        },
    )
    db.add(alert)
    db.flush()
    audit.record(db, operation="alert.created", resource_type="alert", resource_id=alert.id,
                 organization_id=shipment.exporter_org_id, details={"reasons": result.reasons})
    return alert


def request_justification(db: Session, alert: ReconciliationAlert, shipment: Shipment) -> None:
    """Asks dispatcher and receiver for an explanation through WhatsApp."""
    from app.modules.notifications.service import queue_outgoing

    alert.status = AlertStatus.JUSTIFICATION_REQUESTED.value
    parts = []
    if alert.weight_diff_kg is not None:
        parts.append(f"diferencia de {fmt_kg(alert.weight_diff_kg)} ({fmt_pct(alert.discrepancy_pct)})")
    if alert.sacks_diff:
        parts.append(f"diferencia de {abs(alert.sacks_diff)} saco(s)")
    if alert.seal_match is False:
        parts.append("sellos que no coinciden")
    if not alert.state_match:
        parts.append("estado del café distinto entre salida y llegada")
    body = (
        f"Se registró la alerta {alert.code} en el traslado {shipment.code}: {', '.join(parts)}. "
        f"Por favor cuéntanos qué pudo ocurrir. Puedes responder con un mensaje o una nota de voz "
        f"indicando el código {alert.code}. Esto no implica ninguna acusación; solo necesitamos registrar "
        f"la explicación."
    )
    for user_id in {shipment.dispatcher_user_id, shipment.receiver_user_id}:
        if user_id is None:
            continue
        user = db.get(User, user_id)
        if user and user.whatsapp_phone:
            queue_outgoing(db, phone=user.whatsapp_phone, body=body, kind="justification_request")


def suggest_classification(text_value: str) -> str | None:
    """Deterministic keyword suggestion. Only a hint for the human reviewer."""
    t = text_value.lower()
    if any(w in t for w in ("humedad", "sec", "lluvia", "mojad")):
        return AlertClassification.MOISTURE_VARIATION.value
    if any(w in t for w in ("error", "mal anotado", "digit", "equivoc")):
        return AlertClassification.RECORDING_ERROR.value
    if any(w in t for w in ("roto", "rompi", "derram", "cay", "perdi")):
        return AlertClassification.JUSTIFIED_SHORTAGE.value
    if "merma" in t:
        return AlertClassification.NATURAL_SHRINKAGE.value
    return None


def register_justification(
    db: Session, actor: Actor, alert_code: str, justification: str, suggested: str | None = None
) -> ReconciliationAlert:
    alert = db.scalar(
        select(ReconciliationAlert).where(ReconciliationAlert.code == alert_code.upper()).with_for_update()
    )
    if alert is None:
        raise NotFound(f"No encontré la alerta {alert_code}.")
    shipment = db.get(Shipment, alert.shipment_id)
    assert shipment is not None
    participants = {shipment.dispatcher_user_id, shipment.receiver_user_id}
    is_transporter = (
        shipment.transporter_org_id is not None
        and shipment.transporter_org_id in actor.orgs_for(Role.TRANSPORTER)
    )
    is_chain_owner = actor.is_admin or alert.exporter_org_id in actor.orgs_for(Role.EXPORTER)
    if actor.id not in participants and not is_transporter and not is_chain_owner:
        raise NotFound(f"No encontré la alerta {alert_code}.")
    if alert.status == AlertStatus.RESOLVED.value:
        raise Conflict("La alerta ya fue resuelta.")
    if not justification.strip():
        raise ValidationFailed("La justificación no puede estar vacía.")
    alert.justification_text = justification.strip()[:2000]
    alert.justification_by_user_id = actor.id
    alert.suggested_classification = suggested or suggest_classification(justification)
    alert.status = AlertStatus.IN_REVIEW.value
    audit.record(db, operation="alert.justified", resource_type="alert", resource_id=alert.id,
                 actor_user_id=actor.id, organization_id=alert.exporter_org_id)
    return alert


def resolve_alert(
    db: Session, actor: Actor, alert_id: uuid.UUID, classification: str, notes: str
) -> ReconciliationAlert:
    """Only an authorized human (exporter, compliance or admin of the chain) can close an alert."""
    actor.require(Role.EXPORTER, Role.COMPLIANCE, Role.ADMIN)
    alert = db.get(ReconciliationAlert, alert_id, with_for_update=True)
    if alert is None:
        raise NotFound("Alerta no encontrada.")
    require_chain_access(db, actor, alert.exporter_org_id)
    if not actor.is_admin and alert.exporter_org_id not in actor.orgs_for(Role.EXPORTER, Role.COMPLIANCE):
        raise NotFound("Alerta no encontrada.")
    if alert.status == AlertStatus.RESOLVED.value:
        raise Conflict("La alerta ya fue resuelta.")
    try:
        cls = AlertClassification(classification)
    except ValueError as exc:
        raise ValidationFailed("Clasificación no válida.") from exc
    if not notes or len(notes.strip()) < 5:
        raise ValidationFailed("La resolución requiere una nota explicativa.")
    db.add(AlertResolution(alert_id=alert.id, resolved_by_user_id=actor.id, classification=cls.value,
                           notes=notes.strip()))
    alert.classification = cls.value
    alert.status = AlertStatus.RESOLVED.value
    shipment = db.get(Shipment, alert.shipment_id)
    if shipment is not None:
        shipment.status = ShipmentStatus.RESOLVED.value
    audit.record(db, operation="alert.resolved", resource_type="alert", resource_id=alert.id,
                 actor_user_id=actor.id, organization_id=alert.exporter_org_id,
                 details={"classification": cls.value})
    return alert


def fmt_kg(value: Decimal | None) -> str:
    if value is None:
        return "sin dato"
    q = Decimal(value).quantize(Decimal("0.01"))
    s = f"{q:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if s.endswith(",00"):
        s = s[:-3]
    return f"{s} kg"


def fmt_pct(value: Decimal | None) -> str:
    if value is None:
        return "sin dato"
    q = Decimal(value).quantize(Decimal("0.01")).normalize()
    return f"{q:f}".replace(".", ",") + " %"
