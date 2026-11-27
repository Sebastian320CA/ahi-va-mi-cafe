"""Basic due diligence dossier per lot, with versioned and configurable demo rules.

The rules below are DEMO RULES PENDING LEGAL VALIDATION, inspired by Regulation (EU) 2023/1115 (geolocation of
plots, polygons above 4 ha, cutoff date 31 December 2020). They are not a legal interpretation.
"""

import uuid
from decimal import Decimal

from geoalchemy2.shape import to_shape
from shapely.geometry import mapping
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import AlertStatus, AssessmentResult, CaseStatus, LocationStatus, Role
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.integrations.geo.assessment import latest_assessment
from app.modules.audit import service as audit
from app.modules.compliance.models import DueDiligenceCase, DueDiligenceReview
from app.modules.identity.models import Organization, User
from app.modules.identity.service import Actor, require_chain_access
from app.modules.producers.models import Farm, Producer
from app.modules.reconciliation.models import AlertResolution, ReconciliationAlert
from app.modules.traceability import service as tr
from app.modules.traceability.models import CustodyEvent, DocumentEvidence, Purchase, Shipment

DISCLAIMER = ("Esta plataforma apoya la recopilación y revisión de evidencias para la diligencia debida. No constituye "
              "una certificación ni sustituye las responsabilidades legales del operador.")

RULESET = {
    "version": "demo-2026-11",
    "status": "Reglas de demostración pendientes de validación con fuentes oficiales vigentes.",
    "reference": "Reglamento (UE) 2023/1115, modificado por el Reglamento (UE) 2025/2650 (aplicación desde el "
                 "30/12/2026 para operadores grandes y medianos, según fuentes oficiales consultadas el 27/11/2026)",
    "cutoff_date": "2020-12-31",
    "rules": [
        {"id": "GEO-1", "text": "Cada finca de origen debe tener geolocalización.", "blocking": True},
        {"id": "GEO-2", "text": "Parcelas con área mayor a 4 ha, o sin área declarada, requieren polígono.",
         "blocking": True},
        {"id": "GEO-3", "text": "La ubicación debe estar revisada por una persona autorizada.", "blocking": True},
        {"id": "ENV-1", "text": "Cada finca debe tener una evaluación ambiental con información suficiente.",
         "blocking": True},
        {"id": "ENV-2", "text": "Una evaluación con riesgo identificado impide la aprobación interna.",
         "blocking": True},
        {"id": "LOG-1", "text": "No deben existir alertas logísticas abiertas en el lote.", "blocking": True},
        {"id": "LEG-1", "text": "Debe registrarse evidencia sobre la legalidad de la producción.", "blocking": True},
    ],
}


def _geojson(geom) -> dict | None:
    return mapping(to_shape(geom)) if geom is not None else None


def _case(db: Session, lot) -> DueDiligenceCase:
    case = db.scalar(select(DueDiligenceCase).where(DueDiligenceCase.lot_id == lot.id))
    if case is None:
        case = DueDiligenceCase(lot_id=lot.id, exporter_org_id=lot.exporter_org_id, status=CaseStatus.INCOMPLETE.value,
                                rule_version=get_settings().due_diligence_rule_version)
        db.add(case)
        db.flush()
    return case


def _evaluate(farms: list[dict], alerts: list[dict], case: DueDiligenceCase) -> tuple[list[dict], bool]:
    threshold = get_settings().polygon_required_above_ha
    missing: list[dict] = []
    risk = False
    for f in farms:
        name = f["name"]
        if f["location"] is None and f["polygon"] is None:
            missing.append({"rule": "GEO-1", "farm": name, "text": f"{name}: falta geolocalización."})
        area = Decimal(f["declared_area_ha"]) if f["declared_area_ha"] is not None else None
        if f["polygon"] is None and (area is None or area > threshold):
            missing.append({"rule": "GEO-2", "farm": name,
                            "text": f"{name}: falta polígono de la parcela o área declarada menor o igual a 4 ha."})
        if f["location_status"] != LocationStatus.REVIEWED.value:
            missing.append({"rule": "GEO-3", "farm": name, "text": f"{name}: ubicación pendiente de verificación."})
        a = f["assessment"]
        if a is None or a["result"] == AssessmentResult.INSUFFICIENT_INFORMATION.value:
            missing.append({"rule": "ENV-1", "farm": name, "text": f"{name}: evaluación ambiental insuficiente."})
        elif a["result"] == AssessmentResult.RISK_IDENTIFIED.value:
            risk = True
    open_alerts = [a for a in alerts if a["status"] != AlertStatus.RESOLVED.value]
    if open_alerts:
        missing.append({"rule": "LOG-1", "farm": None,
                        "text": f"Hay {len(open_alerts)} alerta(s) logística(s) abierta(s)."})
    if not (case.legality_evidence or "").strip():
        missing.append({"rule": "LEG-1", "farm": None, "text": "Falta evidencia sobre la legalidad de la producción."})
    return missing, risk


def computed_status(missing: list[dict], risk: bool) -> str:
    if missing:
        return CaseStatus.INCOMPLETE.value
    if risk:
        return CaseStatus.RISK_IDENTIFIED.value
    return CaseStatus.PENDING_REVIEW.value


def build_dossier(db: Session, actor: Actor, lot_code: str) -> dict:
    lot = tr.get_lot_by_code(db, lot_code)
    require_chain_access(db, actor, lot.exporter_org_id)
    family = tr.lot_family(db, lot)
    root = family[0]
    case = _case(db, root)
    comps = tr.origin_compositions(db, root)
    exporter = db.get(Organization, root.exporter_org_id)
    farms, purchases = [], []
    for c in comps:
        farm = db.get(Farm, c.farm_id)
        producer = db.get(Producer, c.producer_id)
        purchase = db.get(Purchase, c.purchase_id)
        plot = next((pl for pl in farm.plots if pl.polygon is not None), None)
        a = latest_assessment(db, farm.id)
        farms.append({
            "id": str(farm.id), "name": farm.name, "producer": producer.name if producer else None,
            "municipality": farm.municipality, "vereda": farm.vereda, "department": farm.department,
            "declared_area_ha": str(farm.declared_area_ha) if farm.declared_area_ha is not None else None,
            "location": _geojson(farm.location), "location_status": farm.location_status,
            "polygon": _geojson(plot.polygon) if plot else None, "plot": plot.name if plot else None,
            "contributed_kg": str(c.contributed_kg), "is_synthetic": farm.is_synthetic,
            "assessment": assessment_dict(a) if a else None,
        })
        purchases.append({"code": purchase.code, "producer": producer.name if producer else None, "farm": farm.name,
                          "net_weight_kg": str(purchase.net_weight_kg), "coffee_state": purchase.coffee_state,
                          "occurred_at": purchase.occurred_at.isoformat(), "receipt_number": purchase.receipt_number,
                          "document_id": str(purchase.document_id) if purchase.document_id else None})
    ids = [x.id for x in family]
    events = [event_dict(db, e) for e in db.scalars(select(CustodyEvent).where(CustodyEvent.lot_id.in_(ids))
                                                    .order_by(CustodyEvent.occurred_at, CustodyEvent.confirmed_at))]
    shipments = [shipment_dict(db, s) for s in db.scalars(select(Shipment).where(Shipment.lot_id.in_(ids))
                                                           .order_by(Shipment.dispatched_at))]
    alerts = [alert_dict(db, a) for a in db.scalars(select(ReconciliationAlert)
                                                     .where(ReconciliationAlert.lot_id.in_(ids)))]
    doc_ids = {e["evidence_document_id"] for e in events if e["evidence_document_id"]}
    doc_ids |= {p["document_id"] for p in purchases if p["document_id"]}
    documents = [document_dict(d) for d in db.scalars(select(DocumentEvidence).where(
        DocumentEvidence.id.in_([uuid.UUID(i) for i in doc_ids])))] if doc_ids else []
    missing, risk = _evaluate(farms, alerts, case)
    status = case.status
    if status not in (CaseStatus.REVIEWED.value, CaseStatus.APPROVED_INTERNAL.value, CaseStatus.NOT_APPROVED.value):
        status = computed_status(missing, risk)
        case.status = status
    reviews = [{"decision": r.decision, "notes": r.notes, "reviewed_at": r.reviewed_at.isoformat(),
                "reviewer": (db.get(User, r.reviewer_user_id).full_name if db.get(User, r.reviewer_user_id) else None)}
               for r in db.scalars(select(DueDiligenceReview).where(DueDiligenceReview.case_id == case.id)
                                   .order_by(DueDiligenceReview.reviewed_at))]
    current = max(family, key=lambda x: x.created_at)
    return {
        "disclaimer": DISCLAIMER,
        "ruleset": RULESET,
        "case": {"id": str(case.id), "status": status, "computed_status": computed_status(missing, risk),
                 "legality_evidence": case.legality_evidence, "observations": case.observations,
                 "rule_version": case.rule_version},
        "lot": {"code": root.code, "current_code": current.code, "product": "Café (HS 0901)",
                "coffee_state": current.coffee_state, "initial_weight_kg": str(root.initial_weight_kg),
                "current_weight_kg": str(current.current_weight_kg),
                "family": [{"code": x.code, "coffee_state": x.coffee_state, "status": x.status,
                            "initial_weight_kg": str(x.initial_weight_kg)} for x in family]},
        "exporter": exporter.name if exporter else None,
        "farms": farms, "purchases": purchases, "events": events, "shipments": shipments, "alerts": alerts,
        "documents": documents, "missing": missing, "risk_identified": risk, "reviews": reviews,
    }


def update_case(db: Session, actor: Actor, lot_code: str, legality_evidence: str | None,
                observations: str | None) -> DueDiligenceCase:
    actor.require(Role.COMPLIANCE, Role.EXPORTER, Role.ADMIN)
    lot = tr.ancestors(db, tr.get_lot_by_code(db, lot_code))[-1]
    require_chain_access(db, actor, lot.exporter_org_id)
    case = _case(db, lot)
    if legality_evidence is not None:
        case.legality_evidence = legality_evidence.strip()[:4000]
    if observations is not None:
        case.observations = observations.strip()[:4000]
    audit.record(db, operation="due_diligence.updated", resource_type="due_diligence_case", resource_id=case.id,
                 actor_user_id=actor.id, organization_id=lot.exporter_org_id)
    return case


def review_case(db: Session, actor: Actor, lot_code: str, decision: str, notes: str) -> dict:
    """Only an authorized person can review or approve. Approval is blocked while information is missing."""
    actor.require(Role.COMPLIANCE, Role.EXPORTER, Role.ADMIN)
    allowed = {CaseStatus.REVIEWED.value, CaseStatus.APPROVED_INTERNAL.value, CaseStatus.NOT_APPROVED.value}
    if decision not in allowed:
        raise ValidationFailed("Decisión no válida.")
    if not notes or len(notes.strip()) < 5:
        raise ValidationFailed("La revisión requiere observaciones.")
    dossier = build_dossier(db, actor, lot_code)
    lot = tr.get_lot_by_code(db, dossier["lot"]["code"])
    if not actor.is_admin and lot.exporter_org_id not in actor.orgs_for(Role.COMPLIANCE, Role.EXPORTER):
        raise NotFound("Recurso no encontrado.")
    if decision == CaseStatus.APPROVED_INTERNAL.value and (dossier["missing"] or dossier["risk_identified"]):
        raise Conflict("No se puede aprobar internamente: hay información obligatoria pendiente o riesgos "
                       "identificados.")
    case = db.scalar(select(DueDiligenceCase).where(DueDiligenceCase.lot_id == lot.id))
    case.status = decision
    db.add(DueDiligenceReview(case_id=case.id, reviewer_user_id=actor.id, decision=decision, notes=notes.strip(),
                              snapshot={"missing": dossier["missing"], "risk": dossier["risk_identified"],
                                        "rule_version": case.rule_version}))
    audit.record(db, operation="due_diligence.reviewed", resource_type="due_diligence_case", resource_id=case.id,
                 actor_user_id=actor.id, organization_id=lot.exporter_org_id, details={"decision": decision})
    db.flush()
    return build_dossier(db, actor, lot_code)


# ---------------------------------------------------------------- serializers shared with the API

def assessment_dict(a) -> dict:
    return {"result": a.result, "geometry_basis": a.geometry_basis,
            "assessed_area_ha": str(a.assessed_area_ha) if a.assessed_area_ha is not None else None,
            "forest_2020_overlap_ha": str(a.forest_2020_overlap_ha) if a.forest_2020_overlap_ha is not None else None,
            "loss_after_cutoff_ha": str(a.loss_after_cutoff_ha) if a.loss_after_cutoff_ha is not None else None,
            "sources": a.sources, "limitations": a.limitations, "reasons": a.reasons,
            "uses_synthetic_layers": a.uses_synthetic_layers, "rule_version": a.rule_version,
            "queried_at": a.queried_at.isoformat()}


def _org_name(db: Session, org_id) -> str | None:
    if org_id is None:
        return None
    org = db.get(Organization, org_id)
    return org.name if org else None


def event_dict(db: Session, e: CustodyEvent) -> dict:
    actor = db.get(User, e.actor_user_id)
    lot_code = None
    if e.lot_id:
        from app.modules.traceability.models import CoffeeLot

        lot = db.get(CoffeeLot, e.lot_id)
        lot_code = lot.code if lot else None
    return {"id": str(e.id), "lot_code": lot_code, "event_type": e.event_type, "occurred_at": e.occurred_at.isoformat(),
            "confirmed_at": e.confirmed_at.isoformat(), "coffee_state": e.coffee_state,
            "quantity_kg": str(e.quantity_kg) if e.quantity_kg is not None else None,
            "location": _org_name(db, e.location_org_id), "organization": _org_name(db, e.organization_id),
            "actor": actor.full_name if actor else None, "details": e.details,
            "evidence_document_id": str(e.evidence_document_id) if e.evidence_document_id else None,
            "corrects_event_id": str(e.corrects_event_id) if e.corrects_event_id else None}


def shipment_dict(db: Session, s: Shipment) -> dict:
    def kg(v):
        return str(v) if v is not None else None
    return {"id": str(s.id), "code": s.code, "status": s.status, "origin": _org_name(db, s.origin_org_id),
            "destination": _org_name(db, s.destination_org_id), "transporter": _org_name(db, s.transporter_org_id),
            "coffee_state_out": s.coffee_state_out, "coffee_state_in": s.coffee_state_in,
            "dispatched_kg": kg(s.dispatched_kg), "received_kg": kg(s.received_kg), "sacks_out": s.sacks_out,
            "sacks_in": s.sacks_in, "seal_out": s.seal_out, "seal_in": s.seal_in, "vehicle_plate": s.vehicle_plate,
            "dispatched_at": s.dispatched_at.isoformat(),
            "received_at": s.received_at.isoformat() if s.received_at else None,
            "dispatch_document_id": str(s.dispatch_document_id) if s.dispatch_document_id else None,
            "reception_document_id": str(s.reception_document_id) if s.reception_document_id else None}


def alert_dict(db: Session, a: ReconciliationAlert) -> dict:
    shp = db.get(Shipment, a.shipment_id)
    resolutions = [{"classification": r.classification, "notes": r.notes, "resolved_at": r.resolved_at.isoformat(),
                    "resolved_by": (db.get(User, r.resolved_by_user_id).full_name
                                    if db.get(User, r.resolved_by_user_id) else None)}
                   for r in db.scalars(select(AlertResolution).where(AlertResolution.alert_id == a.id))]
    from app.modules.traceability.models import CoffeeLot

    lot = db.get(CoffeeLot, a.lot_id)
    justifier = db.get(User, a.justification_by_user_id) if a.justification_by_user_id else None
    return {"id": str(a.id), "code": a.code, "status": a.status, "lot_code": lot.code if lot else None,
            "weight_diff_kg": str(a.weight_diff_kg) if a.weight_diff_kg is not None else None,
            "discrepancy_pct": str(a.discrepancy_pct) if a.discrepancy_pct is not None else None,
            "sacks_diff": a.sacks_diff, "seal_match": a.seal_match, "state_match": a.state_match,
            "reasons": a.reasons, "thresholds": a.thresholds, "classification": a.classification,
            "justification_text": a.justification_text, "justification_by": justifier.full_name if justifier else None,
            "suggested_classification": a.suggested_classification, "created_at": a.created_at.isoformat(),
            "shipment": shipment_dict(db, shp) if shp else None, "resolutions": resolutions}


def document_dict(d: DocumentEvidence) -> dict:
    return {"id": str(d.id), "kind": d.kind, "mime_type": d.mime_type, "size_bytes": d.size_bytes, "sha256": d.sha256,
            "provider": d.provider, "status": d.status, "extracted_fields": d.extracted_fields,
            "confidence": d.confidence, "corrections": d.corrections, "transcript": d.transcript,
            "processed_at": d.processed_at.isoformat() if d.processed_at else None,
            "confirmed_at": d.confirmed_at.isoformat() if d.confirmed_at else None,
            "resource_type": d.resource_type}
