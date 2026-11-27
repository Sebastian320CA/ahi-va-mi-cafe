"""Document field extraction. Real adapter: Azure AI Document Intelligence (prebuilt-layout with key-value
pairs, REST API v4.0). Simulated adapter: reads the marker embedded in synthetic PNG documents.

Unknown or low-confidence values are returned as None. Values are never invented.
"""

import re
import time
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Protocol

import httpx

from app.core.config import get_settings
from app.integrations.media_markers import read_png_marker

TARGET_FIELDS = [
    "document_type", "document_number", "producer", "farm", "date", "lot_code", "coffee_state", "sacks",
    "gross_weight_kg", "tare_kg", "net_weight_kg", "moisture_pct", "yield_factor", "seal", "vehicle_plate",
    "origin", "destination", "delivered_by", "received_by", "input_kg", "output_kg", "output_state",
]

KEY_ALIASES = {
    "no recibo": "document_number", "n recibo": "document_number", "numero de recibo": "document_number",
    "no planilla": "document_number", "numero de planilla": "document_number", "documento": "document_number",
    "productor": "producer", "caficultor": "producer", "finca": "farm", "fecha": "date",
    "lote": "lot_code", "codigo de lote": "lot_code", "estado": "coffee_state", "estado del cafe": "coffee_state",
    "sacos": "sacks", "cantidad de sacos": "sacks", "bultos": "sacks", "peso bruto": "gross_weight_kg",
    "tara": "tare_kg", "peso neto": "net_weight_kg", "peso recibido": "net_weight_kg",
    "peso despachado": "net_weight_kg", "humedad": "moisture_pct", "factor de rendimiento": "yield_factor",
    "sello": "seal", "numero de sello": "seal", "placa": "vehicle_plate", "origen": "origin",
    "destino": "destination", "entrega": "delivered_by", "responsable de entrega": "delivered_by",
    "recibe": "received_by", "responsable de recepcion": "received_by", "peso de entrada": "input_kg",
    "peso de salida": "output_kg", "estado de salida": "output_state",
}

DOC_TYPES = {
    "recibo de compra": "purchase_receipt",
    "planilla de despacho": "dispatch_sheet",
    "planilla de recepcion": "reception_sheet",
    "registro de trilla": "transformation_record",
}

MIN_CONFIDENCE = 0.6


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", t)).strip()


@dataclass
class Extraction:
    provider: str
    fields: dict[str, str | None] = field(default_factory=dict)
    confidence: dict[str, float | None] = field(default_factory=dict)
    pages: int = 1
    raw_text: str | None = None


class DocumentClient(Protocol):
    name: str

    def extract(self, data: bytes, mime_type: str) -> Extraction: ...


def detect_doc_type(text: str) -> str | None:
    n = normalize(text)
    for label, kind in DOC_TYPES.items():
        if label in n:
            return kind
    return None


class AzureDocumentIntelligenceClient:
    name = "azure_document_intelligence"

    def __init__(self) -> None:
        s = get_settings()
        self.endpoint = s.azure_document_intelligence_endpoint.rstrip("/")
        self.key = s.azure_document_intelligence_key
        self.version = s.azure_document_intelligence_api_version

    def extract(self, data: bytes, mime_type: str) -> Extraction:
        url = f"{self.endpoint}/documentintelligence/documentModels/prebuilt-layout:analyze"
        headers = {"Ocp-Apim-Subscription-Key": self.key, "Content-Type": mime_type}
        resp = httpx.post(url, params={"api-version": self.version, "features": "keyValuePairs"}, content=data,
                          headers=headers, timeout=60)
        resp.raise_for_status()
        op_url = resp.headers["Operation-Location"]
        result = None
        for _ in range(60):
            poll = httpx.get(op_url, headers={"Ocp-Apim-Subscription-Key": self.key}, timeout=30)
            poll.raise_for_status()
            body = poll.json()
            if body.get("status") == "succeeded":
                result = body["analyzeResult"]
                break
            if body.get("status") == "failed":
                raise RuntimeError("Document Intelligence no pudo analizar el documento.")
            time.sleep(1)
        if result is None:
            raise TimeoutError("Document Intelligence no respondió a tiempo.")
        out = Extraction(provider=self.name, pages=len(result.get("pages", [])) or 1,
                         raw_text=result.get("content"))
        out.fields = {k: None for k in TARGET_FIELDS}
        out.fields["document_type"] = detect_doc_type(result.get("content", ""))
        for kv in result.get("keyValuePairs", []):
            key = normalize((kv.get("key") or {}).get("content", ""))
            target = KEY_ALIASES.get(key)
            if not target:
                continue
            value = (kv.get("value") or {}).get("content")
            conf = kv.get("confidence")
            out.confidence[target] = conf
            out.fields[target] = value.strip() if value and (conf is None or conf >= MIN_CONFIDENCE) else None
        return out


class SimulatedDocumentClient:
    name = "simulated"

    def extract(self, data: bytes, mime_type: str) -> Extraction:
        marker = read_png_marker(data)
        if marker is None:
            raise ValueError("El lector simulado solo procesa documentos sintéticos generados por "
                             "scripts/generate_documents.py.")
        out = Extraction(provider=self.name, pages=1)
        out.fields = {k: None for k in TARGET_FIELDS}
        for k, v in marker.get("fields", {}).items():
            conf = marker.get("confidence", {}).get(k)
            out.confidence[k] = conf
            out.fields[k] = None if (v is None or (conf is not None and conf < MIN_CONFIDENCE)) else str(v)
        return out


@lru_cache
def get_document_client() -> DocumentClient:
    if get_settings().document_provider == "azure":
        return AzureDocumentIntelligenceClient()
    return SimulatedDocumentClient()
