"""Typed tools available to the assistant.

Write tools have two phases: prepare() validates and resolves a pending operation that is shown to the user,
execute() runs the business service only after an explicit confirmation linked to that pending operation.
Each tool declares the roles allowed to use it; the business services re-check authorization.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent import parsing as p
from app.core.enums import COFFEE_STATE_LABELS, CoffeeState, EventType, OrgKind, Role
from app.core.errors import DomainError
from app.modules.audit import service as audit
from app.modules.identity.models import Organization
from app.modules.identity.service import Actor, chain_members, exporter_for_org, require_chain_access
from app.modules.notifications.models import IncomingMessage
from app.modules.producers import service as producers
from app.modules.producers.models import Farm, Producer
from app.modules.reconciliation import service as recon
from app.modules.reconciliation.models import ReconciliationAlert
from app.modules.reconciliation.service import fmt_kg, fmt_pct
from app.modules.traceability import service as tr
from app.modules.traceability.models import CoffeeLot, Purchase


def kilos(value) -> str:
    return fmt_kg(Decimal(str(value))).replace(" kg", " kilos")


def state_label(value: str | None) -> str:
    try:
        return COFFEE_STATE_LABELS[CoffeeState(value or "")]
    except (ValueError, KeyError):
        return "estado sin confirmar"


FIELD_LABELS = {
    "producer": "el nombre del productor",
    "farm": "el nombre de la finca",
    "weight_kg": "el peso neto en kilos",
    "coffee_state": "el estado del café (pergamino seco o café verde)",
    "lot_code": "el código del lote (por ejemplo CAF-001)",
    "destination": "el destino del despacho",
    "input_kg": "el peso de entrada en kilos",
    "output_kg": "el peso de salida en kilos",
    "purchases": "las compras que forman el lote",
    "purchase_code": "el código de la compra (por ejemplo COM-0001)",
    "new_weight_kg": "el peso correcto en kilos",
    "alert_code": "el código de la alerta (por ejemplo ALR-001)",
    "justification": "la explicación de lo ocurrido",
    "name": "tu nombre",
    "farm_name": "el nombre de tu finca",
    "location": "la ubicación",
}


@dataclass
class ToolContext:
    db: Session
    phone: str
    actor: Actor | None
    message: IncomingMessage
    document_id: uuid.UUID | None = None
    state: Any = None


@dataclass
class Prepared:
    raw: dict
    resolved: dict
    summary: str
    missing: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class Tool:
    name: str = ""
    description: str = ""
    kind: str = "write"
    roles: set[Role] | None = set()  # None means available to unregistered numbers
    args_model: type[BaseModel] = BaseModel

    def allowed(self, actor: Actor | None) -> bool:
        if self.roles is None:
            return actor is None
        return actor is not None and actor.has_role(*self.roles)

    def spec(self) -> dict:
        schema = self.args_model.model_json_schema()
        schema.pop("title", None)
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                 "parameters": schema}}

    def validate(self, args: dict) -> dict:
        model = self.args_model.model_validate({k: v for k, v in (args or {}).items() if v not in ("", None)})
        return model.model_dump(mode="json", exclude_none=True)

    def prepare(self, ctx: ToolContext, raw: dict) -> Prepared:
        raise NotImplementedError

    def execute(self, ctx: ToolContext, resolved: dict, idempotency_key: str) -> str:
        raise NotImplementedError

    def run(self, ctx: ToolContext, raw: dict) -> str:
        raise NotImplementedError


def _occurred(ctx: ToolContext, raw: dict) -> tuple[str, str]:
    when, source = p.occurred_at_from(p.parse_date(raw.get("date")), ctx.message.message_timestamp)
    return when.isoformat(), source


def _dec(raw: dict, key: str) -> Decimal | None:
    return p.to_decimal(raw.get(key)) if raw.get(key) is not None else None


def _state(raw: dict, key: str = "coffee_state") -> str | None:
    v = raw.get(key)
    if v is None:
        return None
    try:
        return CoffeeState(v).value
    except ValueError:
        return p.coffee_state(str(v))


def confirm_suffix(missing: list[str]) -> str:
    if missing:
        labels = [FIELD_LABELS.get(m, m) for m in missing]
        return " No pude identificar " + ", ".join(labels) + ". ¿Me lo indicas?"
    return " ¿Es correcto? Responde SI para confirmar o dime qué debo corregir."


# ---------------------------------------------------------------- producer registration

class RegisterProducerArgs(BaseModel):
    name: str | None = Field(None, description="Nombre de la persona caficultora")
    farm_name: str | None = Field(None, description="Nombre de la finca")
    vereda: str | None = None
    municipality: str | None = None


class RegisterProducerTool(Tool):
    name = "register_producer"
    description = "Prepara el registro de un caficultor nuevo con su finca. Requiere consentimiento."
    roles = None
    args_model = RegisterProducerArgs

    def prepare(self, ctx, raw):
        missing = [k for k in ("name", "farm_name") if not raw.get(k)]
        place = ", ".join(x for x in (f"vereda {raw['vereda']}" if raw.get("vereda") else None,
                                       raw.get("municipality")) if x)
        summary = (f"Entendí que te llamas {raw.get('name', '(sin nombre)')} y tu finca se llama "
                   f"{raw.get('farm_name', '(sin nombre)')}{f' ({place})' if place else ''}. "
                   f"{producers.CONSENT_TEXT} Si los datos son correctos y aceptas, responde SI ACEPTO. "
                   f"Si no aceptas, responde NO.")
        if missing:
            summary = confirm_suffix(missing).strip()
        return Prepared(raw, dict(raw), summary, missing)

    def execute(self, ctx, resolved, idempotency_key):
        producer = producers.register_producer(
            ctx.db, phone=ctx.phone, name=resolved["name"], farm_name=resolved["farm_name"],
            consent_accepted=True, consent_response=ctx.message.interpreted_text or "SI",
            source_message_id=ctx.message.provider_message_id, municipality=resolved.get("municipality"),
            vereda=resolved.get("vereda"))
        if ctx.state is not None:
            ctx.state.active_user_id = producer.user_id
        first = producer.name.split()[0]
        return (f"Listo, {first}. Tu registro quedó listo con la finca {resolved['farm_name']}. Cuando estés en la "
                f"finca, comparte la ubicación desde WhatsApp: toca el clip, elige Ubicación y envía tu ubicación "
                f"actual. Tu registro y el uso del servicio son gratuitos.")


class FarmLocationArgs(BaseModel):
    latitude: float
    longitude: float
    farm_name: str | None = None


class RegisterFarmLocationTool(Tool):
    name = "register_farm_location"
    description = "Prepara el registro de la ubicación compartida de la finca del caficultor."
    roles = {Role.PRODUCER}
    args_model = FarmLocationArgs

    def prepare(self, ctx, raw):
        producer = producers.producer_for_user(ctx.db, ctx.actor.id)
        if producer is None:
            raise DomainError("No encontré tu registro como caficultor.")
        farm = producers.find_farm(ctx.db, producer, raw.get("farm_name"))
        missing = [] if farm else ["farm"]
        producers.validate_coordinates(raw["latitude"], raw["longitude"])
        resolved = {**raw, "farm_id": str(farm.id) if farm else None}
        summary = (f"Recibí la ubicación ({raw['latitude']:.5f}, {raw['longitude']:.5f}) para la finca "
                   f"{farm.name if farm else '(sin identificar)'}. Quedará pendiente de verificación y no "
                   f"representa los linderos de la finca.") + confirm_suffix(missing)
        return Prepared(raw, resolved, summary, missing)

    def execute(self, ctx, resolved, idempotency_key):
        farm = producers.register_farm_location(ctx.db, ctx.actor, uuid.UUID(resolved["farm_id"]),
                                                resolved["latitude"], resolved["longitude"])
        return (f"Guardamos la ubicación de la finca {farm.name}. Queda pendiente de verificación por el equipo "
                f"de cumplimiento.")


# ---------------------------------------------------------------- purchases

class PurchaseArgs(BaseModel):
    producer_name: str | None = Field(None, description="Nombre del caficultor que vende")
    farm_name: str | None = None
    weight_kg: str | None = Field(None, description="Peso neto en kilogramos")
    coffee_state: str | None = Field(None, description="cereza, pergamino_humedo, pergamino_seco o verde")
    sacks: int | None = None
    moisture_pct: str | None = None
    yield_factor: str | None = None
    receipt_number: str | None = None
    date: str | None = Field(None, description="Fecha del documento AAAA-MM-DD")


class RegisterPurchaseTool(Tool):
    name = "register_purchase"
    description = "Prepara el registro de una compra de café en el centro de acopio."
    roles = {Role.COLLECTION_OPERATOR}
    args_model = PurchaseArgs

    def prepare(self, ctx, raw):
        db, missing = ctx.db, []
        exporter = exporter_for_org(db, ctx.actor.org_for(Role.COLLECTION_OPERATOR))
        producer = farm = None
        if raw.get("producer_name"):
            matches = producers.find_producer_by_name(db, exporter, raw["producer_name"])
            if not matches:
                matches = producers.find_producer_by_name(db, exporter, raw["producer_name"].split()[0])
            producer = matches[0] if len(matches) == 1 else None
        if producer is None:
            missing.append("producer")
        else:
            farm = producers.find_farm(db, producer, raw.get("farm_name"))
            if farm is None:
                missing.append("farm")
        weight = _dec(raw, "weight_kg")
        if weight is None or weight <= 0:
            missing.append("weight_kg")
        state = _state(raw)
        if state is None:
            missing.append("coffee_state")
        occurred, source = _occurred(ctx, raw)
        resolved = {"producer_id": str(producer.id) if producer else None, "farm_id": str(farm.id) if farm else None,
                    "net_weight_kg": str(weight) if weight else None, "coffee_state": state,
                    "sacks": raw.get("sacks"), "moisture_pct": raw.get("moisture_pct"),
                    "yield_factor": raw.get("yield_factor"), "receipt_number": raw.get("receipt_number"),
                    "occurred_at": occurred, "occurred_at_source": source}
        parts = [producer.name if producer else None, f"finca {farm.name}" if farm else None,
                 f"{kilos(weight)} de {state_label(state)}" if weight and state else None,
                 f"{raw['sacks']} sacos" if raw.get("sacks") else None,
                 f"humedad {str(raw['moisture_pct']).replace('.', ',')} %" if raw.get("moisture_pct") else None]
        head = f"Entendí la compra del recibo {raw['receipt_number']}: " if raw.get("receipt_number") else \
            "Entendí la compra: "
        summary = head + ", ".join(x for x in parts if x) + "." + confirm_suffix(missing)
        return Prepared(raw, resolved, summary, missing)

    def execute(self, ctx, resolved, idempotency_key):
        purchase = tr.register_purchase(ctx.db, ctx.actor, tr.PurchaseInput(
            producer_id=uuid.UUID(resolved["producer_id"]), farm_id=uuid.UUID(resolved["farm_id"]),
            net_weight_kg=Decimal(resolved["net_weight_kg"]), coffee_state=resolved["coffee_state"],
            occurred_at=datetime.fromisoformat(resolved["occurred_at"]), sacks=resolved.get("sacks"),
            moisture_pct=p.to_decimal(resolved.get("moisture_pct")),
            yield_factor=p.to_decimal(resolved.get("yield_factor")),
            receipt_number=resolved.get("receipt_number"), document_id=ctx.document_id), idempotency_key)
        return (f"Compra {purchase.code} registrada: {kilos(purchase.net_weight_kg)} de "
                f"{state_label(purchase.coffee_state)}. Le enviamos la confirmación al caficultor.")


class CorrectEventArgs(BaseModel):
    purchase_code: str | None = None
    new_weight_kg: str | None = None
    reason: str | None = None


class CorrectEventTool(Tool):
    name = "correct_event"
    description = "Prepara la corrección del peso de una compra ya registrada que aún no está en un lote."
    roles = {Role.COLLECTION_OPERATOR}
    args_model = CorrectEventArgs

    def prepare(self, ctx, raw):
        missing = [k for k in ("purchase_code", "new_weight_kg") if not raw.get(k)]
        purchase = None
        if raw.get("purchase_code"):
            purchase = ctx.db.scalar(select(Purchase).where(Purchase.code == raw["purchase_code"].upper()))
            if purchase is None or purchase.collection_center_org_id not in ctx.actor.orgs_for(
                    Role.COLLECTION_OPERATOR):
                if "purchase_code" not in missing:
                    missing.append("purchase_code")
                purchase = None
        resolved = {"purchase_id": str(purchase.id) if purchase else None,
                    "new_weight_kg": raw.get("new_weight_kg"), "reason": raw.get("reason") or "Corrección"}
        summary = (f"Voy a corregir la compra {raw.get('purchase_code')}: de "
                   f"{kilos(purchase.net_weight_kg) if purchase else '?'} a "
                   f"{kilos(raw['new_weight_kg']) if raw.get('new_weight_kg') else '?'}. Se conserva el registro "
                   f"original.") + confirm_suffix(missing)
        return Prepared(raw, resolved, summary, missing)

    def execute(self, ctx, resolved, idempotency_key):
        purchase = tr.correct_purchase_weight(ctx.db, ctx.actor, uuid.UUID(resolved["purchase_id"]),
                                              Decimal(resolved["new_weight_kg"]), resolved["reason"])
        return f"Corrección registrada. La compra {purchase.code} queda en {kilos(purchase.net_weight_kg)}."


# ---------------------------------------------------------------- lots

class CreateLotArgs(BaseModel):
    purchase_codes: list[str] | None = Field(None, description="Códigos COM-xxxx de las compras")
    selection: str | None = Field(None, description="'today' para usar las compras disponibles de hoy")
    expected_count: int | None = Field(None, description="Cantidad de compras que la persona mencionó")


class CreateLotTool(Tool):
    name = "create_lot"
    description = "Prepara la consolidación de compras completas del centro de acopio en un lote nuevo."
    roles = {Role.COLLECTION_OPERATOR}
    args_model = CreateLotArgs

    def prepare(self, ctx, raw):
        db = ctx.db
        center = ctx.actor.org_for(Role.COLLECTION_OPERATOR)
        stmt = select(Purchase).where(Purchase.collection_center_org_id == center, Purchase.available_kg > 0,
                                      Purchase.available_kg == Purchase.net_weight_kg).order_by(Purchase.code)
        if raw.get("purchase_codes"):
            stmt = stmt.where(Purchase.code.in_([c.upper() for c in raw["purchase_codes"]]))
            purchases = list(db.scalars(stmt))
        else:
            purchases = [x for x in db.scalars(stmt) if p.is_today(x.occurred_at, ctx.message.message_timestamp)]
        if not purchases:
            raise DomainError("No encontré compras disponibles para consolidar.")
        expected = raw.get("expected_count")
        if expected and expected != len(purchases):
            listed = ", ".join(x.code for x in purchases)
            raise DomainError(f"Mencionaste {expected} compras, pero encontré {len(purchases)} disponibles: "
                              f"{listed}. Indícame los códigos de las compras que debo usar.")
        states = {x.coffee_state for x in purchases}
        if len(states) > 1:
            raise DomainError("Las compras tienen estados del café distintos y no pueden consolidarse juntas.")
        total = sum((x.available_kg for x in purchases), Decimal("0"))
        lines = []
        for x in purchases:
            farm = db.get(Farm, x.farm_id)
            prod = db.get(Producer, x.producer_id)
            lines.append(f"{x.code} {prod.name if prod else ''}, finca {farm.name if farm else ''}: "
                         f"{kilos(x.available_kg)}")
        summary = (f"Voy a crear un lote de {state_label(states.pop())} con {len(purchases)} compras: "
                   + "; ".join(lines) + f". Total: {kilos(total)}." + confirm_suffix([]))
        resolved = {"purchase_ids": [str(x.id) for x in purchases],
                    "occurred_at": ctx.message.message_timestamp.isoformat()}
        return Prepared(raw, resolved, summary)

    def execute(self, ctx, resolved, idempotency_key):
        lot = tr.create_lot(ctx.db, ctx.actor, [uuid.UUID(i) for i in resolved["purchase_ids"]], idempotency_key,
                            occurred_at=datetime.fromisoformat(resolved["occurred_at"]))
        farms = len({c.farm_id for c in lot.compositions})
        return (f"Listo. Se creó el lote {lot.code} con {kilos(lot.initial_weight_kg)} de "
                f"{state_label(lot.coffee_state)}, con el origen de {farms} fincas.")


# ---------------------------------------------------------------- shipments

class DispatchArgs(BaseModel):
    lot_code: str | None = None
    weight_kg: str | None = Field(None, description="Peso neto despachado en kg")
    coffee_state: str | None = None
    sacks: int | None = None
    seal: str | None = None
    vehicle_plate: str | None = None
    destination: str | None = Field(None, description="Nombre o código de la organización de destino")
    transporter: str | None = None
    receipt_number: str | None = None
    date: str | None = None


def _resolve_org(db: Session, exporter_id: uuid.UUID, text_value: str | None,
                 kinds: tuple[str, ...] = ()) -> Organization | None:
    if not text_value:
        return None
    members = [db.get(Organization, i) for i in chain_members(db, exporter_id)]
    members = [m for m in members if m is not None and (not kinds or m.kind in kinds)]
    n = p.norm(text_value)
    exact = [m for m in members if p.norm(m.code) == n or p.norm(m.name) == n]
    if len(exact) == 1:
        return exact[0]
    partial = [m for m in members if n in p.norm(m.name) or p.norm(m.name.split(" (")[0]) in n]
    if len(partial) == 1:
        return partial[0]
    keyword = {"trilladora": OrgKind.MILL, "trilla": OrgKind.MILL, "puerto": OrgKind.PORT,
               "acopio": OrgKind.COLLECTION_CENTER, "transport": OrgKind.TRANSPORTER}
    for word, kind in keyword.items():
        if word in n:
            found = [m for m in members if m.kind == kind.value]
            if len(found) == 1:
                return found[0]
    return None


class RegisterDispatchTool(Tool):
    name = "register_dispatch"
    description = "Prepara el registro del despacho de un lote desde la organización del operador."
    roles = {Role.COLLECTION_OPERATOR, Role.MILL_OPERATOR}
    args_model = DispatchArgs

    def prepare(self, ctx, raw):
        db, missing = ctx.db, []
        lot = db.scalar(select(CoffeeLot).where(CoffeeLot.code == raw["lot_code"].upper())) \
            if raw.get("lot_code") else None
        if lot is None:
            missing.append("lot_code")
        exporter = lot.exporter_org_id if lot else exporter_for_org(
            db, ctx.actor.org_for(Role.COLLECTION_OPERATOR, Role.MILL_OPERATOR))
        dest = _resolve_org(db, exporter, raw.get("destination"))
        if dest is None:
            missing.append("destination")
        transporter = _resolve_org(db, exporter, raw.get("transporter"), (OrgKind.TRANSPORTER.value,))
        weight = _dec(raw, "weight_kg")
        if weight is None:
            missing.append("weight_kg")
        state = _state(raw)
        if state is None:
            missing.append("coffee_state")
        occurred, source = _occurred(ctx, raw)
        origin = db.get(Organization, lot.custodian_org_id) if lot else None
        resolved = {"lot_code": lot.code if lot else None, "destination_org_id": str(dest.id) if dest else None,
                    "transporter_org_id": str(transporter.id) if transporter else None,
                    "dispatched_kg": str(weight) if weight else None, "coffee_state": state,
                    "sacks": raw.get("sacks"), "seal": raw.get("seal"), "vehicle_plate": raw.get("vehicle_plate"),
                    "occurred_at": occurred, "occurred_at_source": source}
        parts = [f"{raw['sacks']} sacos" if raw.get("sacks") else None,
                 f"{kilos(weight)} de {state_label(state)}" if weight else None,
                 f"sello {raw['seal']}" if raw.get("seal") else None,
                 f"placa {raw['vehicle_plate']}" if raw.get("vehicle_plate") else None]
        route = f", desde {origin.name}" if origin else ""
        route += f" hacia {dest.name}" if dest else ""
        summary = (f"Entendí el despacho del lote {lot.code if lot else '(sin identificar)'}: "
                   + ", ".join(x for x in parts if x) + route + "." + confirm_suffix(missing))
        return Prepared(raw, resolved, summary, missing)

    def execute(self, ctx, resolved, idempotency_key):
        shp = tr.register_dispatch(ctx.db, ctx.actor, tr.DispatchInput(
            lot_code=resolved["lot_code"], destination_org_id=uuid.UUID(resolved["destination_org_id"]),
            dispatched_kg=Decimal(resolved["dispatched_kg"]), coffee_state=resolved["coffee_state"],
            occurred_at=datetime.fromisoformat(resolved["occurred_at"]), sacks=resolved.get("sacks"),
            seal=resolved.get("seal"), vehicle_plate=resolved.get("vehicle_plate"),
            transporter_org_id=uuid.UUID(resolved["transporter_org_id"]) if resolved.get("transporter_org_id")
            else None, document_id=ctx.document_id), idempotency_key)
        dest = ctx.db.get(Organization, shp.destination_org_id)
        return (f"Despacho {shp.code} registrado. El lote {resolved['lot_code']} queda en tránsito hacia "
                f"{dest.name if dest else 'el destino'}. La recepción la registra el destino de forma "
                f"independiente.")


class ReceptionArgs(BaseModel):
    lot_code: str | None = None
    weight_kg: str | None = Field(None, description="Peso neto recibido en kg")
    coffee_state: str | None = None
    sacks: int | None = None
    seal: str | None = None
    receipt_number: str | None = None
    date: str | None = None


class RegisterReceptionTool(Tool):
    name = "register_reception"
    description = "Prepara el registro de la recepción de un lote despachado hacia la organización del operador."
    roles = {Role.MILL_OPERATOR, Role.PORT_OPERATOR, Role.COLLECTION_OPERATOR}
    args_model = ReceptionArgs

    def prepare(self, ctx, raw):
        db, missing = ctx.db, []
        lot = db.scalar(select(CoffeeLot).where(CoffeeLot.code == raw["lot_code"].upper())) \
            if raw.get("lot_code") else None
        if lot is None:
            missing.append("lot_code")
        weight = _dec(raw, "weight_kg")
        if weight is None:
            missing.append("weight_kg")
        state = _state(raw)
        if state is None:
            missing.append("coffee_state")
        occurred, source = _occurred(ctx, raw)
        resolved = {"lot_code": lot.code if lot else None, "received_kg": str(weight) if weight is not None else None,
                    "coffee_state": state, "sacks": raw.get("sacks"), "seal": raw.get("seal"),
                    "occurred_at": occurred, "occurred_at_source": source}
        sacks_txt = f"{raw['sacks']} sacos de " if raw.get("sacks") else ""
        summary = (f"Entendí que recibiste {sacks_txt}{state_label(state)}, con un peso total de "
                   f"{kilos(weight) if weight is not None else '(sin dato)'}, del lote "
                   f"{lot.code if lot else '(sin identificar)'}"
                   + (f", sello {raw['seal']}" if raw.get("seal") else "") + "." + confirm_suffix(missing))
        return Prepared(raw, resolved, summary, missing)

    def execute(self, ctx, resolved, idempotency_key):
        shp = tr.register_reception(ctx.db, ctx.actor, tr.ReceptionInput(
            lot_code=resolved["lot_code"], received_kg=Decimal(resolved["received_kg"]),
            coffee_state=resolved["coffee_state"], occurred_at=datetime.fromisoformat(resolved["occurred_at"]),
            sacks=resolved.get("sacks"), seal=resolved.get("seal"), document_id=ctx.document_id),
            idempotency_key)
        alert = ctx.db.scalar(select(ReconciliationAlert).where(ReconciliationAlert.shipment_id == shp.id))
        if alert is None:
            return (f"Recepción registrada para el traslado {shp.code}. Las cantidades coinciden con el "
                    f"despacho.")
        parts = []
        if alert.weight_diff_kg is not None and alert.weight_diff_kg != 0:
            word = "faltan" if alert.weight_diff_kg > 0 else "sobran"
            parts.append(f"{word} {fmt_kg(abs(alert.weight_diff_kg))} ({fmt_pct(abs(alert.discrepancy_pct))})")
        if alert.sacks_diff:
            parts.append(f"{abs(alert.sacks_diff)} saco(s) de diferencia")
        if alert.seal_match is False:
            parts.append("el sello no coincide")
        if not alert.state_match:
            parts.append("el estado del café no coincide con el despacho")
        return (f"Recepción registrada para el traslado {shp.code}. Encontramos una diferencia con el despacho: "
                f"{', '.join(parts)}. Se abrió la alerta {alert.code}. La recepción quedó registrada y la "
                f"conciliación requiere la revisión de una persona autorizada.")


class TransformationArgs(BaseModel):
    lot_code: str | None = None
    input_kg: str | None = None
    output_kg: str | None = None
    output_state: str | None = None
    weights: list[str] | None = None
    date: str | None = None


class RegisterTransformationTool(Tool):
    name = "register_transformation"
    description = "Prepara el registro de la trilla de pergamino seco a café verde de un lote."
    roles = {Role.MILL_OPERATOR}
    args_model = TransformationArgs

    def prepare(self, ctx, raw):
        db, missing = ctx.db, []
        weights = raw.get("weights") or []
        if not raw.get("input_kg") and len(weights) >= 2:
            raw = {**raw, "input_kg": weights[0], "output_kg": weights[1]}
        if raw.get("weight_kg") and not raw.get("output_kg"):
            raw = {**raw, "output_kg": raw["weight_kg"]}
        raw.pop("weight_kg", None)
        lot = db.scalar(select(CoffeeLot).where(CoffeeLot.code == raw["lot_code"].upper())) \
            if raw.get("lot_code") else None
        if lot is None:
            missing.append("lot_code")
        inp, out = _dec(raw, "input_kg"), _dec(raw, "output_kg")
        if inp is None:
            missing.append("input_kg")
        if out is None:
            missing.append("output_kg")
        out_state = _state(raw, "output_state") or (CoffeeState.GREEN.value if out is not None else None)
        occurred, source = _occurred(ctx, raw)
        resolved = {"lot_code": lot.code if lot else None, "input_kg": str(inp) if inp else None,
                    "output_kg": str(out) if out else None, "output_state": out_state,
                    "occurred_at": occurred, "occurred_at_source": source}
        yield_txt = ""
        if inp and out:
            yield_txt = (f" Rendimiento de transformación: {fmt_pct(out / inp * 100)}. Es un dato de la planilla, "
                         f"no un estándar oficial.")
        summary = (f"Entendí la trilla del lote {lot.code if lot else '(sin identificar)'}: entrada "
                   f"{kilos(inp) if inp else '(sin dato)'} de café pergamino seco, salida "
                   f"{kilos(out) if out else '(sin dato)'} de {state_label(out_state)}.{yield_txt}"
                   + confirm_suffix(missing))
        return Prepared(raw, resolved, summary, missing)

    def execute(self, ctx, resolved, idempotency_key):
        child = tr.register_transformation(ctx.db, ctx.actor, tr.TransformationInput(
            lot_code=resolved["lot_code"], input_kg=Decimal(resolved["input_kg"]),
            output_kg=Decimal(resolved["output_kg"]), output_state=resolved["output_state"],
            occurred_at=datetime.fromisoformat(resolved["occurred_at"]), document_id=ctx.document_id),
            idempotency_key)
        reduction = Decimal(resolved["input_kg"]) - Decimal(resolved["output_kg"])
        farms = len({c.farm_id for c in tr.origin_compositions(ctx.db, child)})
        return (f"Trilla registrada. Se creó el lote {child.code} con {kilos(child.initial_weight_kg)} de café "
                f"verde. La reducción de {kilos(reduction)} corresponde a la transformación y no se registra como "
                f"pérdida logística. Se conserva el origen de {farms} fincas.")


# ---------------------------------------------------------------- alerts and review

class JustifyArgs(BaseModel):
    alert_code: str | None = None
    justification: str | None = None


class JustifyAlertTool(Tool):
    name = "justify_alert"
    description = "Prepara el registro de la justificación de una alerta de conciliación."
    roles = {Role.COLLECTION_OPERATOR, Role.TRANSPORTER, Role.MILL_OPERATOR, Role.PORT_OPERATOR}
    args_model = JustifyArgs

    def prepare(self, ctx, raw):
        missing = [k for k in ("alert_code", "justification") if not raw.get(k)]
        resolved = dict(raw)
        resolved["suggested"] = recon.suggest_classification(raw.get("justification") or "")
        summary = (f"Voy a registrar esta explicación para la alerta {raw.get('alert_code')}: "
                   f"\"{(raw.get('justification') or '')[:300]}\". La decisión final la toma una persona "
                   f"autorizada del exportador.") + confirm_suffix(missing)
        return Prepared(raw, resolved, summary, missing)

    def execute(self, ctx, resolved, idempotency_key):
        alert = recon.register_justification(ctx.db, ctx.actor, resolved["alert_code"], resolved["justification"],
                                             resolved.get("suggested"))
        return f"Registramos tu explicación para la alerta {alert.code}. Quedó en revisión."


class ReviewArgs(BaseModel):
    reason: str | None = None


class RequestHumanReviewTool(Tool):
    name = "request_human_review"
    description = "Registra una solicitud para que una persona del equipo revise el caso."
    kind = "read"
    roles = set(Role)
    args_model = ReviewArgs

    def run(self, ctx, raw):
        audit.record(ctx.db, operation="human_review.requested", resource_type="conversation",
                     resource_id=ctx.phone, actor_user_id=ctx.actor.id, details={"reason": raw.get("reason")})
        return "Registramos tu solicitud de revisión. Una persona del equipo te contactará por este medio."


# ---------------------------------------------------------------- queries

class EmptyArgs(BaseModel):
    pass


class QueryMyCoffeeTool(Tool):
    name = "query_my_coffee"
    description = "Consulta dónde va el café del caficultor según el último evento confirmado."
    kind = "read"
    roles = {Role.PRODUCER}
    args_model = EmptyArgs

    def run(self, ctx, raw):
        producer = producers.producer_for_user(ctx.db, ctx.actor.id)
        if producer is None:
            return "No encontré tu registro como caficultor."
        items = tr.producer_coffee_status(ctx.db, producer)
        if not items:
            return "Todavía no tenemos ventas registradas a tu nombre."
        item = items[0]
        purchase = item["purchase"]
        event = item["event"]
        when = p.fmt_local(event.occurred_at) if event else p.fmt_local(purchase.occurred_at)
        sale = f"Tu venta de {kilos(purchase.net_weight_kg)} del {p.fmt_local(purchase.occurred_at)[:10]}"
        if item["lot"] is None:
            center = ctx.db.get(Organization, purchase.collection_center_org_id)
            return f"{sale} está registrada en {center.name if center else 'el centro de acopio'} y aún no sale."
        loc = item.get("location")
        loc_name = loc.name if loc else "un punto de la cadena"
        if event.event_type == EventType.DISPATCH.value:
            dest = item.get("destination")
            text_value = (f"El lote que contiene tu café salió de {loc_name}"
                          f"{' rumbo a ' + dest.name if dest else ''} el {when}.")
        elif event.event_type == EventType.RECEPTION.value and loc and loc.kind == OrgKind.PORT.value:
            text_value = f"El lote que contiene tu café ya llegó al puerto ({loc_name}) el {when}."
        elif event.event_type == EventType.RECEPTION.value:
            text_value = f"El lote que contiene tu café llegó a {loc_name} el {when}."
        elif event.event_type == EventType.TRANSFORMATION.value:
            text_value = f"El lote que contiene tu café fue trillado en {loc_name} el {when} y ahora es café verde."
        else:
            text_value = f"Tu café está en el lote {item['lot'].code}, en {loc_name}."
        return text_value + " Esta es la última información confirmada; no corresponde a rastreo en tiempo real."


class LotStatusArgs(BaseModel):
    lot_code: str


class QueryLotStatusTool(Tool):
    name = "query_lot_status"
    description = "Consulta el estado actual confirmado de un lote de la cadena autorizada."
    kind = "read"
    roles = {Role.COLLECTION_OPERATOR, Role.TRANSPORTER, Role.MILL_OPERATOR, Role.PORT_OPERATOR, Role.EXPORTER,
             Role.COMPLIANCE, Role.ADMIN}
    args_model = LotStatusArgs

    def run(self, ctx, raw):
        lot = tr.get_lot_by_code(ctx.db, raw["lot_code"])
        require_chain_access(ctx.db, ctx.actor, lot.exporter_org_id)
        custodian = ctx.db.get(Organization, lot.custodian_org_id)
        event = tr.last_confirmed_event(ctx.db, [lot])
        open_alerts = len([a for a in ctx.db.scalars(select(ReconciliationAlert).where(
            ReconciliationAlert.lot_id == lot.id)) if a.status != "resolved"])
        return (f"Lote {lot.code}: {kilos(lot.current_weight_kg)} de {state_label(lot.coffee_state)} "
                f"(peso inicial {kilos(lot.initial_weight_kg)}). Custodio: {custodian.name if custodian else '-'}. "
                f"Último evento confirmado: {event.event_type if event else 'ninguno'} el "
                f"{p.fmt_local(event.occurred_at) if event else '-'}. Alertas abiertas: {open_alerts}.")


class UpdatePendingArgs(BaseModel):
    weight_kg: str | None = None
    sacks: int | None = None
    seal: str | None = None
    vehicle_plate: str | None = None
    moisture_pct: str | None = None
    coffee_state: str | None = None
    lot_code: str | None = None
    producer_name: str | None = None
    farm_name: str | None = None
    destination: str | None = None


UPDATE_PENDING_SPEC = {
    "type": "function",
    "function": {"name": "update_pending_operation",
                 "description": "Corrige o completa datos de la operación pendiente de confirmación.",
                 "parameters": {k: v for k, v in UpdatePendingArgs.model_json_schema().items() if k != "title"}},
}

TOOLS: dict[str, Tool] = {t.name: t for t in (
    RegisterProducerTool(), RegisterFarmLocationTool(), RegisterPurchaseTool(), CreateLotTool(),
    RegisterDispatchTool(), RegisterReceptionTool(), RegisterTransformationTool(), CorrectEventTool(),
    JustifyAlertTool(), QueryMyCoffeeTool(), QueryLotStatusTool(), RequestHumanReviewTool(),
)}


def tools_for(actor: Actor | None) -> list[Tool]:
    return [t for t in TOOLS.values() if t.allowed(actor)]


def merge_update(raw: dict, update: dict) -> dict:
    merged = dict(raw)
    for k, v in update.items():
        if v is None or v == "":
            continue
        merged[k] = v
    return merged
