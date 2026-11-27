from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.enums import AlertClassification, AlertStatus, LotStatus, ShipmentStatus
from app.core.errors import Conflict, Forbidden, ValidationFailed
from app.modules.identity.service import find_org_by_code
from app.modules.notifications.models import Notification
from app.modules.producers import service as producers
from app.modules.producers.models import Producer
from app.modules.reconciliation import service as recon
from app.modules.reconciliation.models import ReconciliationAlert
from app.modules.traceability import service as tr
from app.modules.traceability.models import LotComposition
from app.seed import PHONES
from tests.conftest import actor_by

NOW = datetime(2026, 11, 20, 14, 0, tzinfo=UTC)
LATER = datetime(2026, 11, 21, 9, 0, tzinfo=UTC)


def register_rosa(db):
    p = producers.register_producer(db, phone=PHONES["rosa"], name="Rosa Méndez", farm_name="La Esperanza",
                                    consent_accepted=True, consent_response="SI", source_message_id="t1")
    db.commit()
    return p


def producer(db, name):
    return db.scalar(select(Producer).where(Producer.name.ilike(f"{name}%")))


def buy_three(db):
    register_rosa(db)
    op = actor_by(db, phone=PHONES["acopio"])
    out = []
    for name, kg in (("Rosa", "380"), ("Pedro", "350"), ("Luis", "270")):
        p = producer(db, name)
        out.append(tr.register_purchase(db, op, tr.PurchaseInput(
            producer_id=p.id, farm_id=p.farms[0].id, net_weight_kg=Decimal(kg), coffee_state="pergamino_seco",
            occurred_at=NOW, sacks=None), idempotency_key=f"buy-{name}"))
    db.commit()
    return op, out


def build_to_mill(db):
    op, purchases = buy_three(db)
    lot = tr.create_lot(db, op, [p.id for p in purchases], idempotency_key="lot-1", occurred_at=NOW)
    db.commit()
    mill = find_org_by_code(db, "TRILLA-NEIVA")
    trans = find_org_by_code(db, "TRANS-SUR")
    shp = tr.register_dispatch(db, op, tr.DispatchInput(
        lot_code=lot.code, destination_org_id=mill.id, dispatched_kg=Decimal("1000"),
        coffee_state="pergamino_seco", occurred_at=NOW, sacks=20, seal="4471", transporter_org_id=trans.id),
        idempotency_key="disp-1")
    db.commit()
    mill_op = actor_by(db, phone=PHONES["trilladora"])
    shp = tr.register_reception(db, mill_op, tr.ReceptionInput(
        lot_code=lot.code, received_kg=Decimal("952"), coffee_state="pergamino_seco", occurred_at=NOW,
        sacks=19, seal="4471"), idempotency_key="rec-1")
    db.commit()
    return op, mill_op, lot, shp


def test_register_producer_and_purchase_notifies(db):
    op, purchases = buy_three(db)
    assert sum(p.net_weight_kg for p in purchases) == Decimal("1000.00")
    notes = list(db.scalars(select(Notification).where(Notification.kind == "purchase_registered")))
    assert len(notes) == 3
    rosa = next(n for n in notes if n.phone == PHONES["rosa"])
    assert "380 kilos de café pergamino seco" in rosa.body


def test_purchase_idempotent(db):
    op, purchases = buy_three(db)
    p = producer(db, "Rosa")
    again = tr.register_purchase(db, op, tr.PurchaseInput(
        producer_id=p.id, farm_id=p.farms[0].id, net_weight_kg=Decimal("380"), coffee_state="pergamino_seco",
        occurred_at=NOW), idempotency_key="buy-Rosa")
    assert again.id == purchases[0].id


def test_consolidation_preserves_genealogy(db):
    op, purchases = buy_three(db)
    lot = tr.create_lot(db, op, [p.id for p in purchases], idempotency_key="lot-1", occurred_at=NOW)
    db.commit()
    assert lot.code == "CAF-001"
    assert lot.initial_weight_kg == Decimal("1000.00")
    comps = list(db.scalars(select(LotComposition).where(LotComposition.lot_id == lot.id)))
    assert sorted(c.contributed_kg for c in comps) == [Decimal("270.00"), Decimal("350.00"), Decimal("380.00")]
    assert len({c.farm_id for c in comps}) == 3
    assert all(p.available_kg == 0 for p in purchases)


def test_duplicate_assignment_rejected(db):
    op, purchases = buy_three(db)
    tr.create_lot(db, op, [p.id for p in purchases], idempotency_key="lot-1", occurred_at=NOW)
    db.commit()
    with pytest.raises(Conflict):
        tr.create_lot(db, op, [purchases[0].id], idempotency_key="lot-2")
    db.rollback()
    with pytest.raises(ValidationFailed):
        tr.create_lot(db, op, [purchases[0].id, purchases[0].id], idempotency_key="lot-3")


def test_negative_inventory_blocked_by_database(db):
    op, purchases = buy_three(db)
    with pytest.raises(DBAPIError):
        db.execute(text("UPDATE purchases SET available_kg = -1 WHERE id = :i"), {"i": purchases[0].id})
        db.flush()
    db.rollback()


def test_composition_is_append_only(db):
    op, purchases = buy_three(db)
    lot = tr.create_lot(db, op, [p.id for p in purchases], idempotency_key="lot-1", occurred_at=NOW)
    db.commit()
    with pytest.raises(DBAPIError):
        db.execute(text("DELETE FROM lot_compositions WHERE lot_id = :i"), {"i": lot.id})
    db.rollback()


def test_dispatch_reception_discrepancy(db):
    op, mill_op, lot, shp = build_to_mill(db)
    assert shp.status == ShipmentStatus.DISCREPANCY.value
    alert = db.scalar(select(ReconciliationAlert).where(ReconciliationAlert.shipment_id == shp.id))
    assert alert.weight_diff_kg == Decimal("48.00")
    assert alert.discrepancy_pct == Decimal("4.800")
    assert alert.sacks_diff == 1
    assert alert.seal_match is True
    assert alert.status == AlertStatus.JUSTIFICATION_REQUESTED.value
    db.refresh(lot)
    assert lot.current_weight_kg == Decimal("952.00") and lot.initial_weight_kg == Decimal("1000.00")


def test_reconcile_pure_function():
    r = recon.reconcile(dispatched_kg=Decimal("1000"), received_kg=Decimal("952"), sacks_out=20, sacks_in=19,
                        seal_out="4471", seal_in="4471", state_out="pergamino_seco", state_in="pergamino_seco",
                        pct_threshold=Decimal("0.5"), sack_tolerance=0)
    assert r.weight_diff_kg == Decimal("48.00") and r.discrepancy_pct == Decimal("4.800")
    assert r.sacks_diff == 1 and set(r.reasons) == {"faltante_peso", "diferencia_sacos"}
    surplus = recon.reconcile(dispatched_kg=Decimal("100"), received_kg=Decimal("110"), sacks_out=None,
                              sacks_in=None, seal_out=None, seal_in=None, state_out="verde", state_in="verde",
                              pct_threshold=Decimal("0.5"), sack_tolerance=0)
    assert surplus.weight_diff_kg == Decimal("-10.00") and "excedente_peso" in surplus.reasons
    mixed = recon.reconcile(dispatched_kg=Decimal("100"), received_kg=Decimal("75"), sacks_out=None,
                            sacks_in=None, seal_out=None, seal_in=None, state_out="pergamino_seco",
                            state_in="verde", pct_threshold=Decimal("0.5"), sack_tolerance=0)
    assert mixed.weight_diff_kg is None and mixed.reasons == ["estado_distinto"]
    with pytest.raises(ValidationFailed):
        recon.reconcile(dispatched_kg=Decimal("0"), received_kg=Decimal("1"), sacks_out=None, sacks_in=None,
                        seal_out=None, seal_in=None, state_out="verde", state_in="verde",
                        pct_threshold=Decimal("0.5"), sack_tolerance=0)


def test_dispatch_from_wrong_location_rejected(db):
    op, mill_op, lot, shp = build_to_mill(db)
    port = find_org_by_code(db, "PUERTO-BUN")
    with pytest.raises(Forbidden):
        tr.register_dispatch(db, op, tr.DispatchInput(lot_code=lot.code, destination_org_id=port.id,
                                                      dispatched_kg=Decimal("900"), coffee_state="pergamino_seco",
                                                      occurred_at=NOW), idempotency_key="disp-x")


def test_alert_resolution_requires_authorized_human(db):
    op, mill_op, lot, shp = build_to_mill(db)
    alert = db.scalar(select(ReconciliationAlert))
    recon.register_justification(db, mill_op, alert.code, "Un saco llegó roto y se derramó café")
    db.commit()
    assert alert.status == AlertStatus.IN_REVIEW.value
    assert alert.suggested_classification == AlertClassification.JUSTIFIED_SHORTAGE.value
    with pytest.raises(Forbidden):
        recon.resolve_alert(db, op, alert.id, "faltante_justificado", "Intento no autorizado")
    exporter = actor_by(db, email="exportador@demo.cafe")
    recon.resolve_alert(db, exporter, alert.id, "faltante_justificado", "Saco roto documentado con foto.")
    db.commit()
    assert alert.status == AlertStatus.RESOLVED.value
    with pytest.raises(Conflict):
        recon.resolve_alert(db, exporter, alert.id, "faltante_justificado", "Otra vez")


def test_transformation_and_port_without_loss_alert(db):
    op, mill_op, lot, shp = build_to_mill(db)
    green = tr.register_transformation(db, mill_op, tr.TransformationInput(
        lot_code=lot.code, input_kg=Decimal("952"), output_kg=Decimal("714"), output_state="verde",
        occurred_at=NOW), idempotency_key="tf-1")
    db.commit()
    assert green.code == "CAF-001-V" and green.initial_weight_kg == Decimal("714.00")
    db.refresh(lot)
    assert lot.status == LotStatus.TRANSFORMED.value
    assert db.scalar(select(text("count(*)")).select_from(ReconciliationAlert)) == 1
    origins = tr.origin_compositions(db, green)
    assert {c.contributed_kg for c in origins} == {Decimal("380.00"), Decimal("350.00"), Decimal("270.00")}
    port = find_org_by_code(db, "PUERTO-BUN")
    shp2 = tr.register_dispatch(db, mill_op, tr.DispatchInput(
        lot_code=green.code, destination_org_id=port.id, dispatched_kg=Decimal("714"), coffee_state="verde",
        occurred_at=NOW, sacks=10, seal="9001"), idempotency_key="disp-2")
    db.commit()
    port_op = actor_by(db, phone=PHONES["puerto"])
    shp2 = tr.register_reception(db, port_op, tr.ReceptionInput(
        lot_code=green.code, received_kg=Decimal("714"), coffee_state="verde", occurred_at=NOW, sacks=10,
        seal="9001"), idempotency_key="rec-2")
    db.commit()
    assert shp2.status == ShipmentStatus.RECONCILED.value
    assert db.scalar(select(text("count(*)")).select_from(ReconciliationAlert)) == 1
    rosa = producer(db, "Rosa")
    status = tr.producer_coffee_status(db, rosa)
    assert status[0]["location"].code == "PUERTO-BUN"
    kinds = {n.kind for n in db.scalars(select(Notification).where(Notification.phone == PHONES["rosa"]))}
    assert {"purchase_registered", "lot_departed", "lot_arrived", "lot_arrived_port"} <= kinds


def test_transformation_rejects_wrong_input(db):
    op, mill_op, lot, shp = build_to_mill(db)
    with pytest.raises(ValidationFailed):
        tr.register_transformation(db, mill_op, tr.TransformationInput(
            lot_code=lot.code, input_kg=Decimal("1000"), output_kg=Decimal("714"), output_state="verde",
            occurred_at=NOW), idempotency_key="tf-bad")


def test_reception_must_be_by_destination(db):
    op, purchases = buy_three(db)
    lot = tr.create_lot(db, op, [p.id for p in purchases], idempotency_key="lot-1", occurred_at=NOW)
    mill = find_org_by_code(db, "TRILLA-NEIVA")
    tr.register_dispatch(db, op, tr.DispatchInput(lot_code=lot.code, destination_org_id=mill.id,
                                                  dispatched_kg=Decimal("1000"), coffee_state="pergamino_seco",
                                                  occurred_at=NOW), idempotency_key="d")
    db.commit()
    port_op = actor_by(db, phone=PHONES["puerto"])
    with pytest.raises(Forbidden):
        tr.register_reception(db, port_op, tr.ReceptionInput(lot_code=lot.code, received_kg=Decimal("1000"),
                                                             coffee_state="pergamino_seco", occurred_at=NOW),
                              idempotency_key="r")


def test_purchase_correction_keeps_history(db):
    op, purchases = buy_three(db)
    p = tr.correct_purchase_weight(db, op, purchases[2].id, Decimal("275"), "Error de digitación")
    db.commit()
    from app.modules.traceability.models import CustodyEvent
    ev = db.scalar(select(CustodyEvent).where(CustodyEvent.event_type == "correccion"))
    assert ev.details["old"] == "270.00" and ev.details["new"] == "275.00" and ev.corrects_event_id
    assert p.net_weight_kg == Decimal("275.00")
