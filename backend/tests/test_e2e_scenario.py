"""Full demo scenario (steps 1 to 10) through the signed webhook, the assistant and the panel API."""

from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.modules.notifications.models import Notification
from app.modules.traceability.models import CoffeeLot
from app.seed import PHONES
from tests import helpers as h

ROSA, OP, MILL, PORT = PHONES["rosa"], PHONES["acopio"], PHONES["trilladora"], PHONES["puerto"]
TRANSCRIPT = Path("/tmp/cafe-e2e-transcript.txt")


def test_full_scenario(db):
    client = TestClient(app)
    docs = h.today_docs()
    log: list[str] = []

    def turn(who: str, sent: str, reply: str) -> str:
        log.append(f"[{who}] {sent}\n[Asistente] {reply}\n")
        return reply

    # 1. Registration by voice note, consent and location.
    turn("Rosa (nota de voz)", "Buenos días, soy Rosa Méndez y mi finca se llama La Esperanza, en la vereda El "
         "Cedro de Pitalito", h.voice(client, ROSA, "Buenos días, soy Rosa Méndez y mi finca se llama La Esperanza, "
                                     "en la vereda El Cedro de Pitalito"))
    assert "Tu registro quedó listo" in turn("Rosa", "Sí acepto", h.say(client, ROSA, "Sí acepto"))
    turn("Rosa (ubicación)", "1.8521, -76.0512", h.location(client, ROSA, 1.8521, -76.0512))
    turn("Rosa", "si", h.say(client, ROSA, "si"))

    # 2. Three receipts, one illegible field and one natural-language correction.
    turn("Acopio (foto)", "Recibo R-1001", h.photo(client, OP, docs["01_recibo_compra_rosa.png"]))
    assert "COM-0001" in turn("Acopio", "si", h.say(client, OP, "si"))
    turn("Acopio (foto)", "Recibo R-1002", h.photo(client, OP, docs["02_recibo_compra_pedro_ilegible.png"]))
    turn("Acopio", "Fueron 350 kilos", h.say(client, OP, "Fueron 350 kilos"))
    turn("Acopio", "si", h.say(client, OP, "si"))
    turn("Acopio (foto)", "Recibo R-1003", h.photo(client, OP, docs["03_recibo_compra_luis_error.png"]))
    turn("Acopio", "No, ese peso está mal. Fueron 270 kilos",
         h.say(client, OP, "No, ese peso está mal. Fueron 270 kilos"))
    turn("Acopio", "si", h.say(client, OP, "si"))

    # 3. Consolidation.
    r = turn("Acopio", "Arma el lote con las tres compras de hoy",
             h.say(client, OP, "Arma el lote con las tres compras de hoy"))
    assert "1.000 kilos" in r
    assert "CAF-001" in turn("Acopio", "si", h.say(client, OP, "si"))

    # 4. Dispatch. 5. Reception with discrepancy.
    turn("Acopio (foto)", "Planilla D-501", h.photo(client, OP, docs["04_planilla_despacho_caf001.png"]))
    turn("Acopio", "si", h.say(client, OP, "si"))
    turn("Trilladora (foto)", "Planilla RC-301", h.photo(client, MILL, docs["05_planilla_recepcion_caf001.png"]))
    r = turn("Trilladora", "si", h.say(client, MILL, "si"))
    assert "48 kg (4,8 %)" in r and "1 saco(s)" in r and "ALR-001" in r
    turn("Trilladora", "ALR-001 Un saco se rompió en el cargue y se derramó café",
         h.say(client, MILL, "ALR-001 Un saco se rompió en el cargue y se derramó café"))
    turn("Trilladora", "si", h.say(client, MILL, "si"))

    exporter = h.login(client, "exportador@demo.cafe")
    alerts = client.get("/api/alerts", headers=exporter).json()
    assert alerts[0]["weight_diff_kg"] == "48.00" and alerts[0]["discrepancy_pct"] == "4.800"
    detail = client.get(f"/api/alerts/{alerts[0]['id']}", headers=exporter).json()
    assert len(detail["documents"]) == 2 and detail["justification_text"]
    r = client.post(f"/api/alerts/{alerts[0]['id']}/resolve", headers=exporter,
                    json={"classification": "faltante_justificado",
                          "notes": "Saco roto en el cargue, confirmado con la trilladora."})
    assert r.status_code == 200 and r.json()["status"] == "resolved"

    # 6. Transformation. 7. Port.
    turn("Trilladora (foto)", "Registro de trilla", h.photo(client, MILL, docs["06_registro_trilla_caf001.png"]))
    r = turn("Trilladora", "si", h.say(client, MILL, "si"))
    assert "CAF-001-V" in r and "no se registra como pérdida logística" in r
    turn("Trilladora (foto)", "Planilla D-777", h.photo(client, MILL, docs["07_planilla_despacho_caf001v.png"]))
    turn("Trilladora", "si", h.say(client, MILL, "si"))
    turn("Puerto (foto)", "Planilla RC-902", h.photo(client, PORT, docs["08_planilla_recepcion_caf001v.png"]))
    r = turn("Puerto", "si", h.say(client, PORT, "si"))
    assert "coinciden" in r
    assert len(client.get("/api/alerts", headers=exporter).json()) == 1

    # 8. Environmental assessment on the map.
    results = client.post("/api/farms/assess", headers=exporter).json()["results"]
    assert results == {"La Esperanza": "insufficient_information", "El Paraíso": "risk_identified",
                       "Los Andes": "no_indications"}
    farms = client.get("/api/farms", headers=exporter).json()
    assert len({f["properties"]["name"] for f in farms["features"]}) == 3

    # 9. Dossier and human review without automatic approval.
    dossier = client.get("/api/due-diligence/CAF-001", headers=exporter).json()
    assert dossier["case"]["status"] == "incomplete" and dossier["risk_identified"] is True
    assert {f["name"] for f in dossier["farms"]} == {"La Esperanza", "El Paraíso", "Los Andes"}
    assert any(m["rule"] == "GEO-3" for m in dossier["missing"])
    assert any(e["event_type"] == "transformacion" for e in dossier["events"])
    blocked = client.post("/api/due-diligence/CAF-001/review", headers=exporter,
                          json={"decision": "approved_internal", "notes": "Intento de aprobación"})
    assert blocked.status_code == 409
    ok = client.post("/api/due-diligence/CAF-001/review", headers=h.login(client, "cumplimiento@demo.cafe"),
                     json={"decision": "reviewed", "notes": "Revisado: riesgo en El Paraíso, falta verificar "
                                                             "La Esperanza y evidencia de legalidad."})
    assert ok.status_code == 200 and ok.json()["case"]["status"] == "reviewed"

    # 10. Farmer query answered from stored state.
    r = turn("Rosa", "¿Dónde va mi café?", h.say(client, ROSA, "¿Dónde va mi café?"))
    assert "El lote que contiene tu café ya llegó al puerto" in r

    green = db.scalar(select(CoffeeLot).where(CoffeeLot.code == "CAF-001-V"))
    assert green.current_weight_kg == Decimal("714.00")
    kinds = [n.kind for n in db.scalars(select(Notification).where(Notification.phone == ROSA))]
    assert kinds.count("lot_arrived_port") == 1 and "purchase_registered" in kinds
    indicators = client.get("/api/indicators", headers=exporter).json()
    assert indicators["purchased_kg_by_state"] == {"pergamino_seco": "1000.00"}
    assert indicators["lots_with_complete_origin"] == 1 and indicators["transformations"][0]["output_kg"] == "714.00"
    TRANSCRIPT.write_text("\n".join(log), encoding="utf-8")
