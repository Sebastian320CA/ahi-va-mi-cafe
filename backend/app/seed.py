"""Reproducible synthetic scenario. Every person, farm and layer here is synthetic."""

import json
from pathlib import Path

from geoalchemy2.shape import from_shape
from shapely.geometry import MultiPolygon, Point, shape
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import Base
from app.core.enums import LocationStatus, OrgKind, Role
from app.core.security import hash_password
from app.modules.identity.models import Membership, Organization, SupplyChainLink, User
from app.modules.producers.models import ConsentRecord, Farm, GeoLayerFeature, Plot, Producer

DEMO_PASSWORD = "Cafe2026!"

ORGS = [
    ("EXP-ANDINO", "Exportadora Andina (sintética)", OrgKind.EXPORTER, "Bogotá", "Cundinamarca"),
    ("COOP-HUILA", "Cooperativa Cafetera del Sur (sintética)", OrgKind.COOPERATIVE, "Pitalito", "Huila"),
    ("ACOPIO-PITALITO", "Centro de Acopio Pitalito (sintético)", OrgKind.COLLECTION_CENTER, "Pitalito", "Huila"),
    ("TRANS-SUR", "Transportes del Sur (sintético)", OrgKind.TRANSPORTER, "Neiva", "Huila"),
    ("TRILLA-NEIVA", "Trilladora Neiva (sintética)", OrgKind.MILL, "Neiva", "Huila"),
    ("PUERTO-BUN", "Bodega Puerto Buenaventura (sintética)", OrgKind.PORT, "Buenaventura", "Valle del Cauca"),
]

PHONES = {
    "acopio": "573001110001",
    "transportador": "573001110002",
    "trilladora": "573001110003",
    "puerto": "573001110004",
    "rosa": "573001110101",
    "pedro": "573001110102",
    "luis": "573001110103",
}

STAFF = [
    ("Administración Demo", "admin@demo.cafe", None, [(Role.ADMIN, "EXP-ANDINO")]),
    ("Laura Exportadora", "exportador@demo.cafe", None, [(Role.EXPORTER, "EXP-ANDINO")]),
    ("Camilo Cumplimiento", "cumplimiento@demo.cafe", None, [(Role.COMPLIANCE, "EXP-ANDINO")]),
    ("Marta Acopio", "acopio@demo.cafe", PHONES["acopio"], [(Role.COLLECTION_OPERATOR, "ACOPIO-PITALITO")]),
    ("Jorge Transportador", None, PHONES["transportador"], [(Role.TRANSPORTER, "TRANS-SUR")]),
    ("Andrés Trilladora", "trilladora@demo.cafe", PHONES["trilladora"], [(Role.MILL_OPERATOR, "TRILLA-NEIVA")]),
    ("Sofía Puerto", "puerto@demo.cafe", PHONES["puerto"], [(Role.PORT_OPERATOR, "PUERTO-BUN")]),
]

PRESEEDED_PRODUCERS = [
    ("Pedro Ramírez", PHONES["pedro"], "El Paraíso", "Pitalito", "Charguayaco", 9.2),
    ("Luis Cárdenas", PHONES["luis"], "Los Andes", "Pitalito", "Bruselas", 7.7),
]

LAYER_FILES = {
    "forest_2020": "synthetic_forest_2020.geojson",
    "forest_loss_after_2020": "synthetic_forest_loss_after_2020.geojson",
}


def geo_dir() -> Path:
    p = Path(get_settings().geospatial_data_path)
    if not p.is_absolute():
        p = (Path(__file__).resolve().parents[1] / p).resolve()
    return p


def truncate_all(db: Session) -> None:
    tables = [t.name for t in reversed(Base.metadata.sorted_tables)]
    db.execute(text("ALTER TABLE audit_logs DISABLE TRIGGER trg_audit_logs_append_only"))
    db.execute(text("ALTER TABLE custody_events DISABLE TRIGGER trg_custody_events_append_only"))
    db.execute(text("ALTER TABLE lot_compositions DISABLE TRIGGER trg_compositions_append_only"))
    db.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
    db.execute(text("ALTER TABLE audit_logs ENABLE TRIGGER trg_audit_logs_append_only"))
    db.execute(text("ALTER TABLE custody_events ENABLE TRIGGER trg_custody_events_append_only"))
    db.execute(text("ALTER TABLE lot_compositions ENABLE TRIGGER trg_compositions_append_only"))
    for seq in ("lot_code_seq", "shipment_code_seq", "purchase_code_seq", "alert_code_seq", "pending_code_seq"):
        db.execute(text(f"ALTER SEQUENCE {seq} RESTART WITH 1"))


def load_layers(db: Session) -> int:
    count = 0
    for layer, filename in LAYER_FILES.items():
        data = json.loads((geo_dir() / filename).read_text(encoding="utf-8"))
        meta = data.get("properties", {})
        for feat in data["features"]:
            geom = shape(feat["geometry"])
            if geom.geom_type == "Polygon":
                geom = MultiPolygon([geom])
            db.add(GeoLayerFeature(layer=layer, source=meta.get("source", filename),
                                   is_synthetic=bool(meta.get("is_synthetic", True)),
                                   reference_date=meta.get("reference_date"),
                                   resolution_m=meta.get("resolution_m"), properties=feat.get("properties", {}),
                                   geom=from_shape(geom, srid=4326)))
            count += 1
    return count


def seed(db: Session, *, reset: bool = True) -> dict:
    if reset:
        truncate_all(db)
    elif db.scalar(select(Organization).limit(1)) is not None:
        return {"skipped": True}
    orgs: dict[str, Organization] = {}
    for code, name, kind, municipality, dept in ORGS:
        org = Organization(code=code, name=name, kind=kind.value, municipality=municipality, department=dept)
        db.add(org)
        orgs[code] = org
    db.flush()
    exporter = orgs["EXP-ANDINO"]
    for code, org in orgs.items():
        if code != "EXP-ANDINO":
            db.add(SupplyChainLink(exporter_org_id=exporter.id, member_org_id=org.id))
    pw = hash_password(DEMO_PASSWORD)
    for full_name, email, phone, roles in STAFF:
        user = User(full_name=full_name, email=email, password_hash=pw if email else None,
                    whatsapp_phone=phone, is_synthetic=True)
        db.add(user)
        db.flush()
        for role, org_code in roles:
            db.add(Membership(user_id=user.id, organization_id=orgs[org_code].id, role=role.value))
    plots = json.loads((geo_dir() / "synthetic_plots.geojson").read_text(encoding="utf-8"))
    polygons = {f["properties"]["farm"]: shape(f["geometry"]) for f in plots["features"]}
    for name, phone, farm_name, municipality, vereda, area in PRESEEDED_PRODUCERS:
        user = User(full_name=name, whatsapp_phone=phone, is_synthetic=True)
        db.add(user)
        db.flush()
        db.add(Membership(user_id=user.id, organization_id=orgs["COOP-HUILA"].id, role=Role.PRODUCER.value))
        db.add(ConsentRecord(user_id=user.id, version=get_settings().consent_version, accepted=True,
                             response_text="SI (registro sintético precargado)", channel="seed"))
        producer = Producer(user_id=user.id, organization_id=orgs["COOP-HUILA"].id, exporter_org_id=exporter.id,
                            name=name, whatsapp_phone=phone, consent_given=True, is_synthetic=True)
        db.add(producer)
        db.flush()
        poly = polygons[farm_name]
        centroid = poly.centroid
        farm = Farm(producer_id=producer.id, name=farm_name, department="Huila", municipality=municipality,
                    vereda=vereda, location=from_shape(Point(centroid.x, centroid.y), srid=4326),
                    location_status=LocationStatus.REVIEWED.value, location_source="seed_synthetic",
                    declared_area_ha=area, is_synthetic=True)
        db.add(farm)
        db.flush()
        db.add(Plot(farm_id=farm.id, name=f"{farm_name} - parcela principal",
                    polygon=from_shape(poly, srid=4326), polygon_source="synthetic_plots.geojson"))
    layers = load_layers(db)
    db.commit()
    return {"organizations": len(orgs), "staff": len(STAFF), "producers": len(PRESEEDED_PRODUCERS),
            "layer_features": layers}
