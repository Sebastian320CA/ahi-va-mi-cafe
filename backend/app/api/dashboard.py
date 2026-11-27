"""Read and decision endpoints for the exporter's web panel. All data is scoped to the authorized chains."""

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from geoalchemy2.shape import to_shape
from pydantic import BaseModel
from shapely.geometry import mapping
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db, panel_actor
from app.core.enums import AlertStatus, CoffeeState, LocationStatus
from app.integrations.geo.assessment import assess_farm, latest_assessment
from app.integrations.storage.client import get_storage
from app.modules.audit.models import AuditLog
from app.modules.compliance import service as compliance
from app.modules.identity.models import Organization
from app.modules.identity.service import Actor, accessible_exporters, chain_members, require_chain_access
from app.modules.notifications.metrics import usage_summary
from app.modules.notifications.models import IncomingMessage, Notification
from app.modules.producers import service as producers
from app.modules.producers.models import Farm, GeoLayerFeature, Producer
from app.modules.reconciliation import service as recon
from app.modules.reconciliation.models import ReconciliationAlert
from app.modules.traceability import service as tr
from app.modules.traceability.models import CoffeeLot, CustodyEvent, DocumentEvidence, Purchase, Shipment

router = APIRouter(prefix="/api", tags=["panel"])


def scope(stmt, column, actor: Actor, db: Session):
    allowed = accessible_exporters(db, actor)
    return stmt if allowed is None else stmt.where(column.in_(allowed or [uuid.uuid4()]))


def _org(db: Session, org_id) -> str | None:
    o = db.get(Organization, org_id) if org_id else None
    return o.name if o else None


# ---------------------------------------------------------------- farms and map

@router.get("/farms")
def farms_geojson(actor: Actor = Depends(panel_actor), db: Session = Depends(get_db)) -> dict:
    stmt = scope(select(Farm, Producer).join(Producer, Producer.id == Farm.producer_id), Producer.exporter_org_id,
                 actor, db)
    features = []
    for farm, producer in db.execute(stmt.order_by(Farm.name)).all():
        a = latest_assessment(db, farm.id)
        plot = next((pl for pl in farm.plots if pl.polygon is not None), None)
        props = {"id": str(farm.id), "name": farm.name, "producer": producer.name, "municipality": farm.municipality,
                 "vereda": farm.vereda, "department": farm.department, "location_status": farm.location_status,
                 "declared_area_ha": str(farm.declared_area_ha) if farm.declared_area_ha is not None else None,
                 "has_polygon": plot is not None, "is_synthetic": farm.is_synthetic,
                 "assessment": compliance.assessment_dict(a) if a else None}
        if farm.location is not None:
            features.append({"type": "Feature", "geometry": mapping(to_shape(farm.location)),
                             "properties": {**props, "geometry_kind": "point"}})
        if plot is not None:
            features.append({"type": "Feature", "geometry": mapping(to_shape(plot.polygon)),
                             "properties": {**props, "geometry_kind": "polygon"}})
        if farm.location is None and plot is None:
            features.append({"type": "Feature", "geometry": None, "properties": {**props, "geometry_kind": "none"}})
    return {"type": "FeatureCollection", "features": features}


@router.get("/geo/layers")
def geo_layers(actor: Actor = Depends(panel_actor), db: Session = Depends(get_db)) -> dict:
    features = [{"type": "Feature", "geometry": mapping(to_shape(f.geom)),
                 "properties": {"layer": f.layer, "source": f.source, "is_synthetic": f.is_synthetic,
                                "reference_date": f.reference_date, **f.properties}}
                for f in db.scalars(select(GeoLayerFeature))]
    return {"type": "FeatureCollection", "features": features}


@router.post("/farms/assess")
def assess_all(actor: Actor = Depends(panel_actor), db: Session = Depends(get_db)) -> dict:
    stmt = scope(select(Farm).join(Producer, Producer.id == Farm.producer_id), Producer.exporter_org_id, actor, db)
    results = {}
    for farm in db.scalars(stmt):
        results[farm.name] = assess_farm(db, farm).result
    db.commit()
    return {"results": results}


class ReviewLocationIn(BaseModel):
    notes: str = "Ubicación revisada"


@router.post("/farms/{farm_id}/review-location")
def review_location(farm_id: uuid.UUID, body: ReviewLocationIn, actor: Actor = Depends(panel_actor),
                    db: Session = Depends(get_db)) -> dict:
    farm = producers.review_farm_location(db, actor, farm_id, body.notes)
    db.commit()
    return {"id": str(farm.id), "location_status": farm.location_status}


@router.get("/farms/export.geojson")
def export_geojson(actor: Actor = Depends(panel_actor), db: Session = Depends(get_db)) -> Response:
    import json

    data = farms_geojson(actor, db)
    return Response(json.dumps(data, ensure_ascii=False), media_type="application/geo+json",
                    headers={"Content-Disposition": "attachment; filename=fincas.geojson"})


# ---------------------------------------------------------------- lots

def lot_summary(db: Session, lot: CoffeeLot) -> dict:
    comps = tr.origin_compositions(db, lot)
    event = tr.last_confirmed_event(db, [lot])
    alerts = db.scalar(select(func.count()).select_from(ReconciliationAlert).where(
        ReconciliationAlert.lot_id == lot.id, ReconciliationAlert.status != AlertStatus.RESOLVED.value))
    parent = db.get(CoffeeLot, lot.parent_lot_id) if lot.parent_lot_id else None
    root = tr.ancestors(db, lot)[-1]
    origin_complete = bool(comps) and sum((c.contributed_kg for c in comps), Decimal("0")) == root.initial_weight_kg
    return {"id": str(lot.id), "code": lot.code, "coffee_state": lot.coffee_state, "status": lot.status,
            "initial_weight_kg": str(lot.initial_weight_kg), "current_weight_kg": str(lot.current_weight_kg),
            "sacks": lot.sacks, "custodian": _org(db, lot.custodian_org_id), "created_at": lot.created_at.isoformat(),
            "parent_code": parent.code if parent else None, "farms": len({c.farm_id for c in comps}),
            "origin_complete": origin_complete,
            "last_event": {"type": event.event_type, "occurred_at": event.occurred_at.isoformat(),
                           "location": _org(db, event.location_org_id)} if event else None,
            "open_alerts": alerts}


@router.get("/lots")
def list_lots(actor: Actor = Depends(panel_actor), db: Session = Depends(get_db)) -> list[dict]:
    stmt = scope(select(CoffeeLot), CoffeeLot.exporter_org_id, actor, db).order_by(CoffeeLot.created_at)
    return [lot_summary(db, lot) for lot in db.scalars(stmt)]


@router.get("/lots/{code}")
def lot_detail(code: str, actor: Actor = Depends(panel_actor), db: Session = Depends(get_db)) -> dict:
    lot = tr.get_lot_by_code(db, code)
    require_chain_access(db, actor, lot.exporter_org_id)
    family = tr.lot_family(db, lot)
    ids = [x.id for x in family]
    comps = tr.origin_compositions(db, lot)
    composition = []
    for c in comps:
        farm, producer, purchase = db.get(Farm, c.farm_id), db.get(Producer, c.producer_id), db.get(Purchase,
                                                                                                     c.purchase_id)
        composition.append({"purchase_code": purchase.code, "producer": producer.name, "farm": farm.name,
                            "contributed_kg": str(c.contributed_kg), "coffee_state": c.coffee_state,
                            "purchase_date": purchase.occurred_at.isoformat(),
                            "moisture_pct": str(purchase.moisture_pct) if purchase.moisture_pct is not None else None,
                            "document_id": str(purchase.document_id) if purchase.document_id else None})
    events = [compliance.event_dict(db, e) for e in db.scalars(
        select(CustodyEvent).where(CustodyEvent.lot_id.in_(ids)).order_by(CustodyEvent.occurred_at,
                                                                           CustodyEvent.confirmed_at))]
    shipments = [compliance.shipment_dict(db, s) for s in db.scalars(
        select(Shipment).where(Shipment.lot_id.in_(ids)).order_by(Shipment.dispatched_at))]
    alerts = [compliance.alert_dict(db, a) for a in db.scalars(
        select(ReconciliationAlert).where(ReconciliationAlert.lot_id.in_(ids)))]
    last = tr.last_confirmed_event(db, family)
    return {"lot": lot_summary(db, lot), "family": [lot_summary(db, x) for x in family], "composition": composition,
            "events": events, "shipments": shipments, "alerts": alerts,
            "last_confirmed_location": {"location": _org(db, last.location_org_id), "event": last.event_type,
                                        "occurred_at": last.occurred_at.isoformat()} if last else None,
            "note": "La ubicación corresponde al último evento confirmado; no es rastreo GPS en tiempo real."}


# ---------------------------------------------------------------- alerts

@router.get("/alerts")
def list_alerts(actor: Actor = Depends(panel_actor), db: Session = Depends(get_db)) -> list[dict]:
    stmt = scope(select(ReconciliationAlert), ReconciliationAlert.exporter_org_id, actor, db)
    return [compliance.alert_dict(db, a) for a in db.scalars(stmt.order_by(ReconciliationAlert.created_at.desc()))]


@router.get("/alerts/{alert_id}")
def alert_detail(alert_id: uuid.UUID, actor: Actor = Depends(panel_actor), db: Session = Depends(get_db)) -> dict:
    alert = db.get(ReconciliationAlert, alert_id)
    if alert is None:
        raise HTTPException(404, "Alerta no encontrada.")
    require_chain_access(db, actor, alert.exporter_org_id)
    data = compliance.alert_dict(db, alert)
    shp = db.get(Shipment, alert.shipment_id)
    doc_ids = [i for i in (shp.dispatch_document_id, shp.reception_document_id) if i]
    data["documents"] = [compliance.document_dict(d) for d in
                         db.scalars(select(DocumentEvidence).where(DocumentEvidence.id.in_(doc_ids)))]
    return data


class ResolveIn(BaseModel):
    classification: str
    notes: str


@router.post("/alerts/{alert_id}/resolve")
def resolve(alert_id: uuid.UUID, body: ResolveIn, actor: Actor = Depends(panel_actor),
            db: Session = Depends(get_db)) -> dict:
    alert = recon.resolve_alert(db, actor, alert_id, body.classification, body.notes)
    db.commit()
    return compliance.alert_dict(db, alert)


# ---------------------------------------------------------------- documents

@router.get("/documents/{doc_id}")
def document(doc_id: uuid.UUID, actor: Actor = Depends(panel_actor), db: Session = Depends(get_db)) -> dict:
    doc = _doc_with_access(db, actor, doc_id)
    return compliance.document_dict(doc)


@router.get("/documents/{doc_id}/file")
def document_file(doc_id: uuid.UUID, actor: Actor = Depends(panel_actor), db: Session = Depends(get_db)) -> Response:
    doc = _doc_with_access(db, actor, doc_id)
    return Response(get_storage().get(doc.storage_key), media_type=doc.mime_type,
                    headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


def _doc_with_access(db: Session, actor: Actor, doc_id: uuid.UUID) -> DocumentEvidence:
    doc = db.get(DocumentEvidence, doc_id)
    if doc is None or (doc.exporter_org_id is None and not actor.is_admin):
        raise HTTPException(404, "Documento no encontrado.")
    if doc.exporter_org_id is not None:
        require_chain_access(db, actor, doc.exporter_org_id)
    return doc


# ---------------------------------------------------------------- due diligence

@router.get("/due-diligence/{lot_code}")
def dossier(lot_code: str, actor: Actor = Depends(panel_actor), db: Session = Depends(get_db)) -> dict:
    data = compliance.build_dossier(db, actor, lot_code)
    db.commit()
    return data


class CaseIn(BaseModel):
    legality_evidence: str | None = None
    observations: str | None = None


@router.patch("/due-diligence/{lot_code}")
def update_dossier(lot_code: str, body: CaseIn, actor: Actor = Depends(panel_actor),
                   db: Session = Depends(get_db)) -> dict:
    compliance.update_case(db, actor, lot_code, body.legality_evidence, body.observations)
    db.commit()
    return compliance.build_dossier(db, actor, lot_code)


class ReviewIn(BaseModel):
    decision: str
    notes: str


@router.post("/due-diligence/{lot_code}/review")
def review(lot_code: str, body: ReviewIn, actor: Actor = Depends(panel_actor), db: Session = Depends(get_db)) -> dict:
    data = compliance.review_case(db, actor, lot_code, body.decision, body.notes)
    db.commit()
    return data


# ---------------------------------------------------------------- indicators, audit, metrics

@router.get("/indicators")
def indicators(actor: Actor = Depends(panel_actor), db: Session = Depends(get_db)) -> dict:
    purchased = {s: str(v) for s, v in db.execute(scope(
        select(Purchase.coffee_state, func.sum(Purchase.net_weight_kg)), Purchase.exporter_org_id, actor, db)
        .group_by(Purchase.coffee_state)).all()}
    legs = []
    for s in db.scalars(scope(select(Shipment), Shipment.exporter_org_id, actor, db).order_by(Shipment.dispatched_at)):
        legs.append({"code": s.code, "origin": _org(db, s.origin_org_id), "destination": _org(db, s.destination_org_id),
                     "coffee_state": s.coffee_state_out, "dispatched_kg": str(s.dispatched_kg),
                     "received_kg": str(s.received_kg) if s.received_kg is not None else None,
                     "difference_kg": str(s.dispatched_kg - s.received_kg) if s.received_kg is not None
                     and s.coffee_state_in == s.coffee_state_out else None, "status": s.status})
    dispatched_by_state: dict[str, Decimal] = {}
    received_by_state: dict[str, Decimal] = {}
    for leg in legs:
        dispatched_by_state[leg["coffee_state"]] = dispatched_by_state.get(leg["coffee_state"], Decimal("0")) + \
            Decimal(leg["dispatched_kg"])
        if leg["received_kg"] is not None:
            received_by_state[leg["coffee_state"]] = received_by_state.get(leg["coffee_state"], Decimal("0")) + \
                Decimal(leg["received_kg"])
    lots = list(db.scalars(scope(select(CoffeeLot), CoffeeLot.exporter_org_id, actor, db)))
    roots = [x for x in lots if x.parent_lot_id is None]
    complete = 0
    for r in roots:
        total = sum((c.contributed_kg for c in r.compositions), Decimal("0"))
        complete += int(total == r.initial_weight_kg and bool(r.compositions))
    transformations = []
    for e in db.scalars(scope(select(CustodyEvent).where(CustodyEvent.event_type == "transformacion"),
                              CustodyEvent.exporter_org_id, actor, db)):
        if e.details.get("output_lot") and e.coffee_state == CoffeeState.GREEN.value:
            transformations.append({"source_lot": e.details["source_lot"], "output_lot": e.details["output_lot"],
                                    "input_kg": e.details["input_kg"], "output_kg": e.details["output_kg"],
                                    "transformation_yield_pct": e.details["transformation_yield_pct"]})
    farm_stmt = scope(select(Farm).join(Producer, Producer.id == Farm.producer_id), Producer.exporter_org_id, actor,
                      db)
    farms = list(db.scalars(farm_stmt))
    open_alerts = db.scalar(scope(select(func.count()).select_from(ReconciliationAlert).where(
        ReconciliationAlert.status != AlertStatus.RESOLVED.value), ReconciliationAlert.exporter_org_id, actor, db))
    return {
        "purchased_kg_by_state": purchased,
        "dispatched_kg_by_state": {k: str(v) for k, v in dispatched_by_state.items()},
        "received_kg_by_state": {k: str(v) for k, v in received_by_state.items()},
        "legs": legs,
        "transformations": transformations,
        "open_alerts": open_alerts,
        "lots_total": len(roots),
        "lots_with_complete_origin": complete,
        "farms_registered": len(farms),
        "farms_reviewed": len([f for f in farms if f.location_status == LocationStatus.REVIEWED.value]),
        "notes": ["Los pesos se agrupan por estado del café; no se suman estados distintos.",
                  "Las transformaciones se reportan aparte y no se contabilizan como pérdidas."],
    }


@router.get("/audit")
def audit_log(resource_id: str | None = None, limit: int = 100, actor: Actor = Depends(panel_actor),
              db: Session = Depends(get_db)) -> list[dict]:
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 500))
    allowed = accessible_exporters(db, actor)
    if allowed is not None:
        orgs = set().union(*[chain_members(db, e) for e in allowed]) if allowed else set()
        stmt = stmt.where(AuditLog.organization_id.in_(orgs or [uuid.uuid4()]))
    if resource_id:
        stmt = stmt.where(AuditLog.resource_id == resource_id)
    return [{"id": a.id, "operation": a.operation, "resource_type": a.resource_type, "resource_id": a.resource_id,
             "result": a.result, "correlation_id": a.correlation_id, "previous_audit_id": a.previous_audit_id,
             "created_at": a.created_at.isoformat(), "details": a.details} for a in db.scalars(stmt)]


@router.get("/metrics/usage")
def usage(actor: Actor = Depends(panel_actor), db: Session = Depends(get_db)) -> dict:
    messages = {s: c for s, c in db.execute(select(IncomingMessage.status, func.count())
                                             .group_by(IncomingMessage.status)).all()}
    notifications = db.scalar(select(func.count()).select_from(Notification))
    return {**usage_summary(db), "messages_by_status": messages, "notifications": notifications}
