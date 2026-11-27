"""Local WhatsApp simulator (development only). It builds Meta-format webhook payloads, signs them with the app
secret and sends them through exactly the same ingestion and processing code as the real webhook."""

import json
import time
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import dev_only, get_db, panel_actor
from app.core.config import get_settings
from app.core.security import meta_signature
from app.integrations.media_markers import build_wav_with_transcript
from app.integrations.storage.client import get_storage
from app.integrations.whatsapp.webhook import ingest, schedule_processing
from app.modules.identity.models import User
from app.modules.identity.service import build_actor
from app.modules.notifications.models import IncomingMessage, OutgoingMessage

router = APIRouter(prefix="/api/dev/simulator", tags=["simulator"], dependencies=[Depends(dev_only),
                                                                                    Depends(panel_actor)])

DOCS_DIR = Path(__file__).resolve().parents[3] / "data" / "documents"


def build_payload(phone: str, message: dict) -> dict:
    return {"object": "whatsapp_business_account", "entry": [{"id": "SIMULATED-WABA", "changes": [{
        "field": "messages", "value": {"messaging_product": "whatsapp",
                                       "metadata": {"display_phone_number": "SIMULADO", "phone_number_id": "SIMULATED"},
                                       "contacts": [{"wa_id": phone, "profile": {"name": "Simulador"}}],
                                       "messages": [message]}}]}]}


def send_simulated(db: Session, phone: str, message: dict) -> dict:
    raw = json.dumps(build_payload(phone, message)).encode()
    result = ingest(db, raw, meta_signature(raw, get_settings().meta_app_secret), provider="simulated")
    schedule_processing(result.accepted)
    return {"provider_message_id": message["id"], "accepted": len(result.accepted), "duplicates": result.duplicates}


@router.get("/contacts")
def contacts(db: Session = Depends(get_db)) -> list[dict]:
    out = []
    for u in db.scalars(select(User).where(User.whatsapp_phone.is_not(None)).order_by(User.whatsapp_phone)):
        actor = build_actor(db, u)
        out.append({"phone": u.whatsapp_phone, "name": u.full_name, "roles": actor.role_names()})
    return out


@router.get("/documents")
def sample_documents() -> list[str]:
    return sorted(p.name for p in DOCS_DIR.glob("*.png")) if DOCS_DIR.exists() else []


@router.post("/messages")
async def send(
    phone: str = Form(...),
    type: str = Form("text"),
    text: str | None = Form(None),
    transcript: str | None = Form(None),
    latitude: float | None = Form(None),
    longitude: float | None = Form(None),
    sample_document: str | None = Form(None),
    timestamp: str | None = Form(None),
    message_id: str | None = Form(None),
    file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
) -> dict:
    phone = "".join(ch for ch in phone if ch.isdigit())
    ts = int(time.time())
    if timestamp:
        ts = int(datetime.fromisoformat(timestamp).timestamp()) if not timestamp.isdigit() else int(timestamp)
    msg: dict = {"from": phone, "id": message_id or f"wamid.SIM.{uuid.uuid4().hex}", "timestamp": str(ts),
                 "type": type}
    storage = get_storage()
    if type == "text":
        if not text:
            raise HTTPException(422, "Falta el texto.")
        msg["text"] = {"body": text}
    elif type == "audio":
        if file is not None:
            data, mime = await file.read(), (file.content_type or "audio/ogg")
        elif transcript:
            data, mime = build_wav_with_transcript(transcript), "audio/wav"
        else:
            raise HTTPException(422, "Envía un archivo de audio o una transcripción simulada.")
        key = storage.put(data, mime, prefix="simulator")
        msg["audio"] = {"id": f"sim:{key}|{mime}", "mime_type": mime, "voice": True}
    elif type == "image":
        if sample_document:
            path = (DOCS_DIR / Path(sample_document).name)
            if not path.exists():
                raise HTTPException(404, "Documento de muestra no encontrado.")
            data, mime = path.read_bytes(), "image/png"
        elif file is not None:
            data, mime = await file.read(), (file.content_type or "image/jpeg")
        else:
            raise HTTPException(422, "Adjunta una imagen o elige un documento de muestra.")
        key = storage.put(data, mime, prefix="simulator")
        msg["image"] = {"id": f"sim:{key}|{mime}", "mime_type": mime, **({"caption": text} if text else {})}
    elif type == "location":
        if latitude is None or longitude is None:
            raise HTTPException(422, "Faltan coordenadas.")
        msg["location"] = {"latitude": latitude, "longitude": longitude}
    else:
        raise HTTPException(422, "Tipo de mensaje no soportado.")
    return send_simulated(db, phone, msg)


@router.post("/redeliver/{provider_message_id}")
def redeliver(provider_message_id: str, db: Session = Depends(get_db)) -> dict:
    """Re-sends an existing message payload to emulate a duplicate webhook delivery from Meta."""
    original = db.scalar(select(IncomingMessage).where(IncomingMessage.provider_message_id == provider_message_id))
    if original is None:
        raise HTTPException(404, "Mensaje no encontrado.")
    return send_simulated(db, original.phone, original.payload)


@router.get("/conversation")
def conversation(phone: str, db: Session = Depends(get_db)) -> list[dict]:
    phone = "".join(ch for ch in phone if ch.isdigit())
    items = []
    for m in db.scalars(select(IncomingMessage).where(IncomingMessage.phone == phone)):
        items.append({"direction": "in", "id": m.provider_message_id, "type": m.message_type,
                      "text": m.interpreted_text or (m.payload.get("text") or {}).get("body"),
                      "status": m.status, "is_late": m.is_late, "at": m.received_at.isoformat(),
                      "message_timestamp": m.message_timestamp.isoformat(), "error": m.error})
    for o in db.scalars(select(OutgoingMessage).where(OutgoingMessage.phone == phone)):
        items.append({"direction": "out", "id": str(o.id), "type": o.kind, "text": o.body, "status": o.status,
                      "at": o.created_at.isoformat(), "error": o.error, "provider": o.provider})
    return sorted(items, key=lambda x: x["at"])
