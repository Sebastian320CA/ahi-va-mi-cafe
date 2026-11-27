"""WhatsApp Cloud API (Meta) adapter and a clearly identified local simulator adapter."""

import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import httpx

from app.core.config import get_settings


@dataclass
class Media:
    data: bytes
    mime_type: str


class WhatsAppClient(Protocol):
    name: str
    requires_service_window: bool

    def send_text(self, to: str, body: str) -> str: ...

    def send_template(self, to: str, template: str, params: list[str]) -> str: ...

    def download_media(self, media_id: str) -> Media: ...


class MetaWhatsAppClient:
    """Official WhatsApp Cloud API through the Graph API."""

    name = "meta"
    requires_service_window = True

    def __init__(self) -> None:
        s = get_settings()
        self.base = f"https://graph.facebook.com/{s.meta_graph_api_version}"
        self.phone_number_id = s.whatsapp_phone_number_id
        self.headers = {"Authorization": f"Bearer {s.whatsapp_access_token}"}
        self.max_bytes = s.max_upload_bytes

    def _post(self, payload: dict) -> str:
        resp = httpx.post(f"{self.base}/{self.phone_number_id}/messages", json=payload, headers=self.headers,
                          timeout=20)
        resp.raise_for_status()
        return resp.json()["messages"][0]["id"]

    def send_text(self, to: str, body: str) -> str:
        return self._post({"messaging_product": "whatsapp", "recipient_type": "individual", "to": to,
                           "type": "text", "text": {"preview_url": False, "body": body[:4096]}})

    def send_template(self, to: str, template: str, params: list[str]) -> str:
        return self._post({
            "messaging_product": "whatsapp", "to": to, "type": "template",
            "template": {"name": template, "language": {"code": "es"},
                         "components": [{"type": "body",
                                         "parameters": [{"type": "text", "text": p[:1024]} for p in params]}]},
        })

    def download_media(self, media_id: str) -> Media:
        meta = httpx.get(f"{self.base}/{media_id}", headers=self.headers, timeout=20)
        meta.raise_for_status()
        info = meta.json()
        if int(info.get("file_size", 0)) > self.max_bytes:
            raise ValueError("El archivo supera el tamaño permitido.")
        with httpx.stream("GET", info["url"], headers=self.headers, timeout=60) as resp:
            resp.raise_for_status()
            chunks, total = [], 0
            for chunk in resp.iter_bytes():
                total += len(chunk)
                if total > self.max_bytes:
                    raise ValueError("El archivo supera el tamaño permitido.")
                chunks.append(chunk)
        return Media(data=b"".join(chunks), mime_type=info.get("mime_type", "application/octet-stream"))


class SimulatedWhatsAppClient:
    """Local simulator. Outgoing messages are only stored in the outgoing_messages table.

    Media uploaded through the simulator is saved in storage and referenced as 'sim:<storage key>'.
    """

    name = "simulated"
    requires_service_window = True

    def send_text(self, to: str, body: str) -> str:
        return f"simulated-{uuid.uuid4().hex}"

    def send_template(self, to: str, template: str, params: list[str]) -> str:
        return f"simulated-template-{uuid.uuid4().hex}"

    def download_media(self, media_id: str) -> Media:
        from app.integrations.storage.client import get_storage

        if not media_id.startswith("sim:"):
            raise ValueError("Identificador de archivo simulado inválido.")
        key, _, mime = media_id[4:].partition("|")
        return Media(data=get_storage().get(key), mime_type=mime or "application/octet-stream")


@lru_cache
def get_whatsapp_client() -> WhatsAppClient:
    if get_settings().whatsapp_provider == "meta":
        return MetaWhatsAppClient()
    return SimulatedWhatsAppClient()
