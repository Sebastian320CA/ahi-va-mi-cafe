import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.security import meta_signature
from app.integrations.media_markers import build_wav_with_transcript
from app.integrations.storage.client import get_storage
from app.modules.notifications.models import IncomingMessage, OutgoingMessage
from app.synthetic_docs import generate

DOC_DIR = Path("/tmp/cafe-test-docs")


def today_docs() -> dict[str, Path]:
    day = datetime.now(ZoneInfo("America/Bogota")).date()
    return {p.name: p for p in generate(DOC_DIR, day)}


def payload(phone: str, message: dict) -> bytes:
    body = {"object": "whatsapp_business_account", "entry": [{"id": "T", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp", "metadata": {"phone_number_id": "T"}, "messages": [message]}}]}]}
    return json.dumps(body).encode()


def post(client, phone: str, message: dict, secret: str | None = None):
    raw = payload(phone, message)
    sig = meta_signature(raw, secret or get_settings().meta_app_secret)
    return client.post("/webhooks/whatsapp", content=raw, headers={"x-hub-signature-256": sig,
                                                                   "content-type": "application/json"})


def base(phone: str, mtype: str, ts: int | None = None, mid: str | None = None) -> dict:
    return {"from": phone, "id": mid or f"wamid.T.{uuid.uuid4().hex}", "timestamp": str(ts or int(time.time())),
            "type": mtype}


def replies_for(mid: str) -> list[str]:
    with SessionLocal() as db:
        inc = db.scalar(select(IncomingMessage).where(IncomingMessage.provider_message_id == mid))
        assert inc is not None, mid
        return [o.body for o in db.scalars(select(OutgoingMessage).where(OutgoingMessage.in_reply_to_id == inc.id)
                                           .order_by(OutgoingMessage.created_at))]


def say(client, phone: str, text_value: str, ts: int | None = None, mid: str | None = None) -> str:
    m = base(phone, "text", ts, mid)
    m["text"] = {"body": text_value}
    r = post(client, phone, m)
    assert r.status_code == 200, r.text
    return " | ".join(replies_for(m["id"]))


def voice(client, phone: str, transcript: str) -> str:
    key = get_storage().put(build_wav_with_transcript(transcript), "audio/wav", "tests")
    m = base(phone, "audio")
    m["audio"] = {"id": f"sim:{key}|audio/wav", "mime_type": "audio/wav"}
    assert post(client, phone, m).status_code == 200
    return " | ".join(replies_for(m["id"]))


def photo(client, phone: str, path: Path) -> str:
    key = get_storage().put(path.read_bytes(), "image/png", "tests")
    m = base(phone, "image")
    m["image"] = {"id": f"sim:{key}|image/png", "mime_type": "image/png"}
    assert post(client, phone, m).status_code == 200
    return " | ".join(replies_for(m["id"]))


def location(client, phone: str, lat: float, lon: float) -> str:
    m = base(phone, "location")
    m["location"] = {"latitude": lat, "longitude": lon}
    assert post(client, phone, m).status_code == 200
    return " | ".join(replies_for(m["id"]))


def login(client, email: str) -> dict:
    r = client.post("/api/auth/login", json={"email": email, "password": "Cafe2026!"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
