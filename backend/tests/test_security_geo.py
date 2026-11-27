import json
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.agent.tools import TOOLS, tools_for
from app.core.enums import OrgKind, Role
from app.core.errors import ValidationFailed
from app.core.security import hash_password, meta_signature
from app.integrations.geo.assessment import assess_farm
from app.integrations.storage.client import get_storage
from app.main import app
from app.modules.compliance import service as compliance
from app.modules.identity.models import Membership, Organization, User
from app.modules.producers import service as producers
from app.modules.producers.models import Farm
from app.modules.traceability.models import Purchase
from app.seed import PHONES
from tests import helpers as h
from tests.conftest import actor_by
from tests.test_traceability import buy_three


@pytest.fixture()
def client(db):
    return TestClient(app)


def other_exporter(db) -> None:
    org = Organization(code="EXP-OTRA", name="Otra Exportadora (sintética)", kind=OrgKind.EXPORTER.value)
    db.add(org)
    db.flush()
    user = User(full_name="Otro Exportador", email="otro@demo.cafe", password_hash=hash_password("Cafe2026!"))
    db.add(user)
    db.flush()
    db.add(Membership(user_id=user.id, organization_id=org.id, role=Role.EXPORTER.value))
    db.commit()


def test_login_and_roles(client, db):
    assert client.post("/api/auth/login", json={"email": "exportador@demo.cafe", "password": "x"}).status_code == 401
    assert client.get("/api/lots").status_code == 401
    r = client.post("/api/auth/login", json={"email": "acopio@demo.cafe", "password": "Cafe2026!"})
    assert r.status_code == 403  # operators work through WhatsApp, not the panel
    headers = h.login(client, "exportador@demo.cafe")
    assert client.get("/api/auth/me", headers=headers).json()["roles"][0]["role"] == "exporter"
    bad = {"Authorization": "Bearer not-a-token"}
    assert client.get("/api/lots", headers=bad).status_code == 401


def test_organization_isolation(client, db):
    op, purchases = buy_three(db)
    from app.modules.traceability import service as tr

    tr.create_lot(db, op, [p.id for p in purchases], idempotency_key="iso")
    db.commit()
    other_exporter(db)
    mine = h.login(client, "exportador@demo.cafe")
    theirs = h.login(client, "otro@demo.cafe")
    assert len(client.get("/api/lots", headers=mine).json()) == 1
    assert client.get("/api/lots", headers=theirs).json() == []
    assert client.get("/api/lots/CAF-001", headers=theirs).status_code == 404
    assert client.get("/api/due-diligence/CAF-001", headers=theirs).status_code == 404
    assert client.get("/api/farms", headers=theirs).json()["features"] == []
    assert client.get("/api/indicators", headers=theirs).json()["purchased_kg_by_state"] == {}


def test_audit_log_is_append_only(db):
    buy_three(db)
    with pytest.raises(DBAPIError):
        db.execute(text("UPDATE audit_logs SET result = 'tampered'"))
    db.rollback()
    with pytest.raises(DBAPIError):
        db.execute(text("DELETE FROM audit_logs"))
    db.rollback()


def test_tool_restrictions_by_role(db):
    rosa = producers.register_producer(db, phone=PHONES["rosa"], name="Rosa", farm_name="La Esperanza",
                                       consent_accepted=True, consent_response="SI", source_message_id=None)
    db.commit()
    producer_tools = {t.name for t in tools_for(actor_by(db, phone=PHONES["rosa"]))}
    assert producer_tools == {"register_farm_location", "query_my_coffee", "request_human_review"}
    operator_tools = {t.name for t in tools_for(actor_by(db, phone=PHONES["acopio"]))}
    assert "create_lot" in operator_tools and "register_transformation" not in operator_tools
    assert {t.name for t in tools_for(None)} == {"register_producer"}
    assert rosa.consent_given
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        TOOLS["query_lot_status"].validate({"lot_code": None, "sql": "DROP TABLE x"})


def test_out_of_order_messages_processed_in_timestamp_order(client, db):
    docs = h.today_docs()
    now = int(time.time())
    key = get_storage().put(docs["03_recibo_compra_luis_error.png"].read_bytes(), "image/png", "tests")
    first = {"from": PHONES["acopio"], "id": "wamid.OOO.A", "timestamp": str(now - 10), "type": "image",
             "image": {"id": f"sim:{key}|image/png", "mime_type": "image/png"}}
    second = {"from": PHONES["acopio"], "id": "wamid.OOO.B", "timestamp": str(now - 5), "type": "text",
              "text": {"body": "No, ese peso está mal. Fueron 270 kilos"}}
    body = {"entry": [{"changes": [{"value": {"messages": [second, first]}}]}]}
    raw = json.dumps(body).encode()
    from app.core.config import get_settings

    r = client.post("/webhooks/whatsapp", content=raw,
                    headers={"x-hub-signature-256": meta_signature(raw, get_settings().meta_app_secret)})
    assert r.json()["accepted"] == 2
    assert "270 kilos" in " ".join(h.replies_for("wamid.OOO.B"))
    assert "207 kilos" in " ".join(h.replies_for("wamid.OOO.A"))


def test_geospatial_validation_and_assessment(db):
    with pytest.raises(ValidationFailed):
        producers.validate_coordinates(40.4, -3.7)  # outside Colombia
    with pytest.raises(ValidationFailed):
        producers.validate_coordinates(95, 0)
    rosa = producers.register_producer(db, phone=PHONES["rosa"], name="Rosa", farm_name="La Esperanza",
                                       consent_accepted=True, consent_response="SI", source_message_id=None)
    db.commit()
    farm = rosa.farms[0]
    assert assess_farm(db, farm).result == "insufficient_information"
    producers.register_farm_location(db, actor_by(db, phone=PHONES["rosa"]), farm.id, 1.8521, -76.0512)
    a = assess_farm(db, farm)
    assert a.result == "insufficient_information" and "punto" in a.reasons[0]
    farm.declared_area_ha = 1
    a = assess_farm(db, farm)
    assert a.geometry_basis == "point_buffer_declared_area" and a.result == "no_indications"
    assert 0.95 < float(a.assessed_area_ha) < 1.05
    paraiso = db.scalar(select(Farm).where(Farm.name == "El Paraíso"))
    risk = assess_farm(db, paraiso)
    assert risk.result == "risk_identified" and risk.uses_synthetic_layers
    assert float(risk.loss_after_cutoff_ha) > 0 and float(risk.forest_2020_overlap_ha) > 0
    assert any("SINTÉTICAS" in x for x in risk.limitations)
    andes = db.scalar(select(Farm).where(Farm.name == "Los Andes"))
    clean = assess_farm(db, andes)
    assert clean.result == "no_indications" and float(clean.forest_2020_overlap_ha) > 0
    assert any("no demuestra deforestación" in r for r in clean.reasons)


def test_dossier_cannot_be_approved_automatically(db):
    op, purchases = buy_three(db)
    from app.modules.traceability import service as tr

    tr.create_lot(db, op, [p.id for p in purchases], idempotency_key="dd")
    db.commit()
    exporter = actor_by(db, email="exportador@demo.cafe")
    data = compliance.build_dossier(db, exporter, "CAF-001")
    assert data["case"]["status"] == "incomplete" and data["missing"]
    with pytest.raises(Exception) as exc:
        compliance.review_case(db, exporter, "CAF-001", "approved_internal", "Aprobación sin evidencias")
    assert getattr(exc.value, "status_code", None) == 409
    operator = actor_by(db, phone=PHONES["acopio"])
    from app.core.errors import Forbidden

    with pytest.raises(Forbidden):
        compliance.review_case(db, operator, "CAF-001", "reviewed", "Operador intentando revisar")
    assert "No constituye una certificación" in data["disclaimer"]


def test_purchase_requires_consent(db):
    from app.modules.producers.models import Producer
    from app.modules.traceability import service as tr

    pedro = db.scalar(select(Producer).where(Producer.name.like("Pedro%")))
    pedro.consent_given = False
    db.commit()
    with pytest.raises(ValidationFailed):
        tr.register_purchase(db, actor_by(db, phone=PHONES["acopio"]), tr.PurchaseInput(
            producer_id=pedro.id, farm_id=pedro.farms[0].id, net_weight_kg=100, coffee_state="pergamino_seco",
            occurred_at=__import__("datetime").datetime.now(__import__("datetime").UTC)), idempotency_key=str(
            uuid.uuid4()))
    assert db.scalar(select(Purchase).limit(1)) is None
