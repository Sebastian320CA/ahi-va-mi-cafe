"""Single conversational assistant: Interpretation, Validation, Summary, Confirmation, Execution.

The LLM (real or simulated) only proposes a tool and arguments. Confirmations, identifiers and
authorization are deterministic. Every write goes through a PendingOperation tied to a specific message.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.agent import parsing as p
from app.agent.prompts import SYSTEM_PROMPT
from app.agent.tools import TOOLS, UPDATE_PENDING_SPEC, Tool, ToolContext, merge_update, tools_for
from app.core.config import get_settings
from app.core.enums import PendingStatus, Role
from app.core.errors import DomainError
from app.core.security import sha256_hex
from app.integrations.documents.client import get_document_client
from app.integrations.llm.client import get_llm_client
from app.integrations.speech.client import get_speech_client
from app.integrations.storage.client import get_storage
from app.integrations.whatsapp.client import get_whatsapp_client
from app.modules.audit import service as audit
from app.modules.identity.models import User
from app.modules.identity.service import Actor, build_actor, exporter_for_org, users_for_phone
from app.modules.notifications.metrics import record_usage
from app.modules.notifications.models import ConversationState, IncomingMessage, PendingOperation
from app.modules.traceability.models import DocumentEvidence

logger = logging.getLogger(__name__)

DOC_TOOL = {
    "purchase_receipt": "register_purchase",
    "dispatch_sheet": "register_dispatch",
    "reception_sheet": "register_reception",
    "transformation_record": "register_transformation",
}

DOC_FIELD_MAP = {
    "register_purchase": {"producer": "producer_name", "farm": "farm_name", "net_weight_kg": "weight_kg",
                          "coffee_state": "coffee_state", "sacks": "sacks", "moisture_pct": "moisture_pct",
                          "yield_factor": "yield_factor", "document_number": "receipt_number", "date": "date"},
    "register_dispatch": {"lot_code": "lot_code", "net_weight_kg": "weight_kg", "coffee_state": "coffee_state",
                          "sacks": "sacks", "seal": "seal", "vehicle_plate": "vehicle_plate",
                          "destination": "destination", "delivered_by": "transporter",
                          "document_number": "receipt_number", "date": "date"},
    "register_reception": {"lot_code": "lot_code", "net_weight_kg": "weight_kg", "coffee_state": "coffee_state",
                           "sacks": "sacks", "seal": "seal", "document_number": "receipt_number", "date": "date"},
    "register_transformation": {"lot_code": "lot_code", "input_kg": "input_kg", "output_kg": "output_kg",
                                "output_state": "output_state", "date": "date"},
}


class Reply(Exception):
    """Short-circuits processing with a message to the user."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def help_text(actor: Actor | None) -> str:
    if actor is None:
        return ("Hola. Soy el asistente de Ahí va mi café. Para registrarte gratis, cuéntame tu nombre y el nombre "
                "de tu finca. Por ejemplo: Soy Rosa y mi finca se llama La Esperanza.")
    if actor.has_role(Role.PRODUCER) and len(actor.grants) == 1:
        return ("Hola. Puedes preguntarme: ¿Dónde va mi café? También puedes compartir la ubicación de tu finca "
                "desde WhatsApp.")
    return ("Hola. Puedes enviarme la foto de un recibo o planilla, una nota de voz, o escribir por ejemplo: "
            "Arma el lote con las tres compras de hoy, o Estado del lote CAF-001.")


# ---------------------------------------------------------------- state helpers

def get_state(db: Session, phone: str) -> ConversationState:
    state = db.scalar(select(ConversationState).where(ConversationState.phone == phone).with_for_update())
    if state is None:
        state = ConversationState(phone=phone, turns=[], context={})
        db.add(state)
        db.flush()
    return state


def remember(state: ConversationState, role: str, content: str) -> None:
    turns = list(state.turns or [])
    turns.append({"role": role, "content": content[:600]})
    state.turns = turns[-get_settings().max_conversation_turns:]


def open_pendings(db: Session, phone: str, user_id) -> list[PendingOperation]:
    stmt = select(PendingOperation).where(PendingOperation.phone == phone,
                                          PendingOperation.status == PendingStatus.PENDING.value)
    stmt = stmt.where(PendingOperation.user_id == user_id) if user_id else stmt.where(
        PendingOperation.user_id.is_(None))
    return list(db.scalars(stmt.order_by(PendingOperation.created_at)))


def new_pending(db: Session, ctx: ToolContext, tool: Tool, prep, document_id=None) -> PendingOperation:
    seq: int = db.execute(text("SELECT nextval('pending_code_seq')")).scalar_one()
    pend = PendingOperation(
        code=f"OP-{seq:03d}", phone=ctx.phone, user_id=ctx.actor.id if ctx.actor else None, tool_name=tool.name,
        params={"raw": prep.raw, "resolved": prep.resolved}, missing_fields=prep.missing, summary=prep.summary,
        document_id=document_id, source_message_id=ctx.message.id,
        source_message_ts=ctx.message.message_timestamp,
        history=[{"revision": 1, "summary": prep.summary, "message_id": str(ctx.message.id),
                  "at": datetime.now(UTC).isoformat()}])
    db.add(pend)
    db.flush()
    return pend


def with_code(pend: PendingOperation) -> str:
    return f"{pend.summary} (Operación {pend.code})"


# ---------------------------------------------------------------- media

def _store_media(db: Session, msg: IncomingMessage, media_id: str, kind: str) -> tuple[DocumentEvidence, bytes]:
    settings = get_settings()
    media = get_whatsapp_client().download_media(media_id)
    mime = media.mime_type.split(";")[0].strip()
    if mime not in settings.allowed_media_set:
        raise Reply("Ese tipo de archivo no es compatible. Envía una foto (JPG o PNG) o una nota de voz.")
    if len(media.data) > settings.max_upload_bytes:
        raise Reply("El archivo es demasiado grande. Envía una foto o audio más liviano.")
    key = get_storage().put(media.data, mime, prefix=f"whatsapp/{kind}")
    doc = DocumentEvidence(kind=kind, storage_key=key, mime_type=mime, size_bytes=len(media.data),
                           sha256=sha256_hex(media.data), incoming_message_id=msg.id, status="received")
    db.add(doc)
    db.flush()
    return doc, media.data


def transcribe(db: Session, msg: IncomingMessage, actor: Actor | None) -> str:
    audio = msg.payload.get("audio") or msg.payload.get("voice") or {}
    doc, data = _store_media(db, msg, audio.get("id", ""), "voice_note")
    doc.uploaded_by_user_id = actor.id if actor else None
    client = get_speech_client()
    result = client.transcribe(data, doc.mime_type)
    doc.provider = client.name
    doc.processed_at = datetime.now(UTC)
    doc.transcript = result.text
    doc.status = "extracted" if result.text else "failed"
    record_usage(db, kind="speech_seconds", provider=client.name, quantity=int(round(result.duration_seconds or 0)),
                 unit="second", phone=msg.phone)
    if not result.text:
        raise Reply("No pude entender la nota de voz. ¿Puedes repetirla o escribir el mensaje?")
    return result.text


def extract_document(db: Session, msg: IncomingMessage, actor: Actor | None) -> DocumentEvidence:
    image = msg.payload.get("image") or {}
    doc, data = _store_media(db, msg, image.get("id", ""), "document_photo")
    doc.uploaded_by_user_id = actor.id if actor else None
    staff = [g for g in (actor.grants if actor else []) if g.role != Role.PRODUCER]
    if staff:
        doc.organization_id = staff[0].organization_id
        try:
            doc.exporter_org_id = exporter_for_org(db, staff[0].organization_id)
        except DomainError:
            doc.exporter_org_id = None
    client = get_document_client()
    try:
        extraction = client.extract(data, doc.mime_type)
    except ValueError as exc:
        doc.status = "failed"
        doc.error = str(exc)
        raise Reply("No pude leer el documento. Envía una foto nítida, de frente y con buena luz.") from exc
    doc.provider = extraction.provider
    doc.extracted_fields = extraction.fields
    doc.confidence = extraction.confidence
    doc.processed_at = datetime.now(UTC)
    doc.status = "extracted"
    record_usage(db, kind="document_pages", provider=client.name, quantity=extraction.pages, unit="page",
                 phone=msg.phone)
    return doc


# ---------------------------------------------------------------- identity

def resolve_actor(db: Session, state: ConversationState, phone: str, message_text: str | None) -> Actor | None:
    users = users_for_phone(db, phone)
    intro = p.introduction(message_text or "")
    registering = bool(intro and p.farm_name(message_text or ""))

    def matches(u: User) -> bool:
        return bool(intro) and p.norm(u.full_name).split()[0] == p.norm(intro or "").split()[0]

    if not users:
        return None
    if intro:
        found = [u for u in users if matches(u)]
        if len(found) == 1:
            state.active_user_id = found[0].id
            return build_actor(db, found[0])
        if registering:
            return None  # a different person on a shared family phone
    if len(users) == 1:
        state.active_user_id = users[0].id
        return build_actor(db, users[0])
    active = next((u for u in users if u.id == state.active_user_id), None)
    if active is not None:
        return build_actor(db, active)
    names = ", ".join(u.full_name.split()[0] for u in users)
    raise Reply(f"Este número está asociado a varias personas registradas: {names}. ¿Con quién hablo? "
                f"Responde por ejemplo: Soy {users[0].full_name.split()[0]}.")


# ---------------------------------------------------------------- main entry

def handle_message(db: Session, msg: IncomingMessage) -> list[str]:
    state = get_state(db, msg.phone)
    replies: list[str] = []
    if state.last_processed_message_ts and msg.message_timestamp < state.last_processed_message_ts:
        msg.is_late = True
        replies.append(f"Recibí con retraso un mensaje enviado el {p.fmt_local(msg.message_timestamp)}.")
    now = datetime.now(UTC)
    state.last_inbound_at = now
    try:
        replies.append(_route(db, state, msg))
    except Reply as stop:
        replies.append(stop.message)
    except DomainError as e:
        replies.append(e.message)
    if not msg.is_late:
        state.last_processed_message_ts = msg.message_timestamp
    for r in replies:
        remember(state, "assistant", r)
    return replies


def _route(db: Session, state: ConversationState, msg: IncomingMessage) -> str:
    body = None
    if msg.message_type == "text":
        body = (msg.payload.get("text") or {}).get("body", "")
    elif msg.message_type == "image":
        body = (msg.payload.get("image") or {}).get("caption")
    actor_hint = None if msg.message_type == "audio" else body
    if msg.message_type == "audio":
        # Identify the channel first (without text) to attribute the evidence, then transcribe.
        users = users_for_phone(db, msg.phone)
        pre_actor = build_actor(db, users[0]) if len(users) == 1 else None
        body = transcribe(db, msg, pre_actor)
        actor_hint = body
    msg.interpreted_text = body
    if body:
        remember(state, "user", body)
    actor = resolve_actor(db, state, msg.phone, actor_hint)
    ctx = ToolContext(db=db, phone=msg.phone, actor=actor, message=msg, state=state)
    pendings = open_pendings(db, msg.phone, actor.id if actor else None)

    if body and (p.is_yes(body) or p.is_no(body) or p.is_cancel(body)):
        if not pendings and actor is not None:
            onboarding = open_pendings(db, msg.phone, None)
            if onboarding:
                ctx.actor, pendings = None, onboarding
        return _confirmation(db, ctx, pendings, body)

    if msg.message_type == "location":
        loc = msg.payload.get("location") or {}
        if actor is None or not actor.has_role(Role.PRODUCER):
            return "Para guardar la ubicación de una finca primero debes registrarte. " + help_text(None)
        return _prepare(db, ctx, TOOLS["register_farm_location"],
                        {"latitude": loc.get("latitude"), "longitude": loc.get("longitude")})

    if msg.message_type == "image":
        doc = extract_document(db, msg, actor)
        return _document(db, ctx, doc)

    if not body:
        return help_text(actor)

    tools = tools_for(actor)
    specs = [t.spec() for t in tools]
    if pendings:
        specs = [UPDATE_PENDING_SPEC, *specs]
    llm = get_llm_client()
    history = [t for t in (state.turns or [])[:-1] if t.get("role") in ("user", "assistant")]
    interp = llm.interpret(system=SYSTEM_PROMPT, history=history, user_text=body, tools=specs)
    if interp.tokens:
        record_usage(db, kind="llm_tokens", provider=llm.name, quantity=interp.tokens, unit="token", phone=msg.phone)
    else:
        record_usage(db, kind="llm_calls", provider=llm.name, quantity=1, unit="call", phone=msg.phone)
    if interp.tool_call is None:
        return sanitize_reply(interp.reply) if interp.reply else help_text(actor)
    name, args = interp.tool_call.name, interp.tool_call.arguments
    if name == "update_pending_operation":
        return _correction(db, ctx, pendings, args)
    tool = TOOLS.get(name)
    if tool is None or not tool.allowed(actor):
        audit.record(db, operation="tool.denied", resource_type="tool", resource_id=name,
                     actor_user_id=actor.id if actor else None, result="denied")
        return "No tienes autorización para realizar esa operación desde este número."
    try:
        clean = tool.validate(args)
    except Exception:
        return "No pude interpretar los datos de la operación. ¿Puedes escribirlos de nuevo?"
    if tool.kind == "read":
        return tool.run(ctx, clean)
    return _prepare(db, ctx, tool, clean)


def sanitize_reply(text_value: str) -> str:
    from app.modules.notifications.service import strip_decorative

    return strip_decorative(text_value)[:1500]


def _prepare(db: Session, ctx: ToolContext, tool: Tool, raw: dict, document_id=None) -> str:
    raw = tool.validate(raw)
    ctx.document_id = document_id
    prep = tool.prepare(ctx, raw)
    pend = new_pending(db, ctx, tool, prep, document_id)
    return with_code(pend)


def _document(db: Session, ctx: ToolContext, doc: DocumentEvidence) -> str:
    doc_type = doc.extracted_fields.get("document_type")
    tool_name = DOC_TOOL.get(doc_type or "")
    if tool_name is None:
        return ("Recibí la foto, pero no pude identificar si es un recibo de compra, una planilla de despacho, de "
                "recepción o un registro de trilla. ¿Puedes enviar una foto donde se vea el título del documento?")
    tool = TOOLS[tool_name]
    if not tool.allowed(ctx.actor):
        audit.record(db, operation="tool.denied", resource_type="tool", resource_id=tool_name,
                     actor_user_id=ctx.actor.id if ctx.actor else None, result="denied")
        return "Recibí el documento, pero tu rol no permite registrar ese tipo de operación."
    raw = {}
    for src, dst in DOC_FIELD_MAP[tool_name].items():
        value = doc.extracted_fields.get(src)
        if value is None:
            continue
        if dst in ("weight_kg", "input_kg", "output_kg", "moisture_pct", "yield_factor"):
            dec = p.to_decimal(str(value))
            value = str(dec) if dec is not None else None
        elif dst == "sacks":
            value = p.to_int(value)
        elif dst in ("coffee_state", "output_state"):
            value = p.coffee_state(str(value))
        elif dst == "lot_code":
            value = p.lot_code(str(value)) or str(value)
        if value is not None:
            raw[dst] = value
    return _prepare(db, ctx, tool, raw, document_id=doc.id)


def _pick(pendings: list[PendingOperation], code: str | None) -> PendingOperation:
    candidates = [x for x in pendings if code is None or x.code == code]
    if not candidates:
        raise Reply("No tengo operaciones pendientes por confirmar." if not code
                    else f"No encontré la operación pendiente {code}.")
    if len(candidates) > 1:
        listed = "; ".join(f"{x.code}: {x.summary[:80]}" for x in candidates)
        raise Reply(f"Tienes varias operaciones pendientes. Indica cuál, por ejemplo SI {candidates[-1].code}. "
                    f"{listed}")
    return candidates[0]


def _confirmation(db: Session, ctx: ToolContext, pendings: list[PendingOperation], body: str) -> str:
    pend = _pick(pendings, p.pending_code(body))
    if ctx.message.message_timestamp < pend.updated_at.replace(microsecond=0):
        return ("Recibí una respuesta enviada antes del último resumen de esta operación. Para evitar errores, "
                "revisa los datos actuales y responde de nuevo. " + with_code(pend))
    tool = TOOLS[pend.tool_name]
    if p.is_cancel(body) or (p.is_no(body) and tool.name == "register_producer"):
        pend.status = PendingStatus.CANCELLED.value
        audit.record(db, operation="pending.cancelled", resource_type="pending_operation", resource_id=pend.id,
                     actor_user_id=ctx.actor.id if ctx.actor else None)
        if tool.name == "register_producer":
            return "Entendido. No registramos tus datos. Si cambias de opinión, escríbenos de nuevo."
        return f"Operación {pend.code} cancelada. No se registró nada."
    if p.is_no(body):
        return "¿Qué dato debo corregir? Escríbelo, por ejemplo: eran 20 sacos. También puedes responder CANCELAR."
    if pend.missing_fields:
        return with_code(pend)
    ctx.document_id = pend.document_id
    try:
        with db.begin_nested():
            result = tool.execute(ctx, pend.params["resolved"], idempotency_key=f"pending:{pend.id}")
    except DomainError as e:
        pend.status = PendingStatus.FAILED.value
        pend.result = {"error": e.message}
        return f"No pude registrar la operación {pend.code}: {e.message}"
    pend.status = PendingStatus.EXECUTED.value
    pend.executed_at = datetime.now(UTC)
    pend.result = {"message": result}
    audit.record(db, operation="pending.executed", resource_type="pending_operation", resource_id=pend.id,
                 actor_user_id=ctx.actor.id if ctx.actor else None,
                 details={"tool": tool.name, "confirmation_message": ctx.message.provider_message_id})
    return result


def _correction(db: Session, ctx: ToolContext, pendings: list[PendingOperation], update: dict) -> str:
    pend = _pick(pendings, None)
    tool = TOOLS[pend.tool_name]
    update = {k: v for k, v in (update or {}).items() if v not in (None, "")}
    raw_before = dict(pend.params.get("raw", {}))
    if tool.name == "register_transformation" and "weight_kg" in update:
        update["output_kg"] = update.pop("weight_kg")
    raw = merge_update(raw_before, update)
    ctx.document_id = pend.document_id
    prep = tool.prepare(ctx, tool.validate(raw))
    if pend.document_id:
        doc = db.get(DocumentEvidence, pend.document_id)
        if doc is not None:
            doc.corrections = [*doc.corrections, *[
                {"field": k, "from": raw_before.get(k), "to": v, "by": str(ctx.actor.id) if ctx.actor else None,
                 "message_id": str(ctx.message.id), "at": datetime.now(UTC).isoformat()} for k, v in update.items()]]
    pend.params = {"raw": prep.raw, "resolved": prep.resolved}
    pend.missing_fields = prep.missing
    pend.summary = prep.summary
    pend.revision += 1
    pend.history = [*pend.history, {"revision": pend.revision, "update": update, "summary": prep.summary,
                                    "message_id": str(ctx.message.id), "at": datetime.now(UTC).isoformat()}]
    pend.updated_at = datetime.now(UTC)
    return with_code(pend)
