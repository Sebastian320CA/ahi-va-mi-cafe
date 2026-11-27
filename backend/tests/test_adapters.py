"""Real adapters exercised against controlled HTTP responses (no commercial credentials needed)."""

import json
from types import SimpleNamespace

import httpx
import pytest

from app.agent.prompts import SYSTEM_PROMPT
from app.agent.tools import TOOLS
from app.integrations.documents.client import AzureDocumentIntelligenceClient
from app.integrations.llm.client import AzureOpenAIClient
from app.integrations.speech.client import AzureSpeechClient
from app.integrations.whatsapp.client import MetaWhatsAppClient
from app.modules.notifications.service import strip_decorative


class FakeResponse:
    def __init__(self, data=None, headers=None, status=200, content=b""):
        self._data, self.headers, self.status_code, self.content = data, headers or {}, status, content

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)


def test_document_intelligence_mapping(monkeypatch):
    result = {"status": "succeeded", "analyzeResult": {
        "content": "Centro de Acopio\nRECIBO DE COMPRA\nPeso neto: 3?0 kg", "pages": [{}],
        "keyValuePairs": [
            {"key": {"content": "Productor:"}, "value": {"content": "Pedro Ramírez"}, "confidence": 0.95},
            {"key": {"content": "Peso neto"}, "value": {"content": "3?0 kg"}, "confidence": 0.32},
            {"key": {"content": "No. recibo"}, "value": {"content": "R-1002"}, "confidence": 0.9},
            {"key": {"content": "Campo desconocido"}, "value": {"content": "x"}, "confidence": 0.9}]}}
    calls = []
    monkeypatch.setattr(httpx, "post", lambda url, **kw: calls.append(url) or FakeResponse(
        headers={"Operation-Location": "https://example/op"}, status=202))
    monkeypatch.setattr(httpx, "get", lambda url, **kw: FakeResponse(result))
    out = AzureDocumentIntelligenceClient().extract(b"img", "image/png")
    assert "prebuilt-layout:analyze" in calls[0]
    assert out.fields["document_type"] == "purchase_receipt"
    assert out.fields["producer"] == "Pedro Ramírez" and out.fields["document_number"] == "R-1002"
    assert out.fields["net_weight_kg"] is None and out.confidence["net_weight_kg"] == 0.32


def test_azure_openai_tool_call_parsing():
    client = AzureOpenAIClient.__new__(AzureOpenAIClient)
    client.deployment = "demo"
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        call = SimpleNamespace(function=SimpleNamespace(name="create_lot",
                                                        arguments=json.dumps({"selection": "today"})))
        msg = SimpleNamespace(tool_calls=[call], content=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=SimpleNamespace(total_tokens=321))

    client.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    out = client.interpret(system=SYSTEM_PROMPT, history=[], user_text="Arma el lote",
                           tools=[TOOLS["create_lot"].spec()])
    assert out.tool_call.name == "create_lot" and out.tokens == 321
    assert "prohibido usar emojis" in captured["messages"][0]["content"]
    assert captured["messages"][-1]["content"].startswith("<mensaje_usuario>")


def test_speech_rest_parsing(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda url, **kw: FakeResponse(
        {"RecognitionStatus": "Success", "DisplayText": "Soy Rosa.", "Duration": 25_000_000,
         "NBest": [{"Confidence": 0.91}]}))
    out = AzureSpeechClient().transcribe(b"ogg", "audio/ogg; codecs=opus")
    assert out.text == "Soy Rosa." and out.duration_seconds == 2.5 and out.confidence == 0.91
    with pytest.raises(ValueError):
        AzureSpeechClient().transcribe(b"x", "video/mp4")


def test_meta_send_payload(monkeypatch):
    sent = {}
    monkeypatch.setattr(httpx, "post", lambda url, json=None, **kw: sent.update(url=url, body=json) or FakeResponse(
        {"messages": [{"id": "wamid.X"}]}))
    assert MetaWhatsAppClient().send_text("573001110101", "Hola") == "wamid.X"
    assert sent["url"].startswith("https://graph.facebook.com/v") and sent["body"]["type"] == "text"


def test_emoji_stripped_from_outgoing_text():
    assert strip_decorative("Listo \U0001F600 tu cafe \u2705 llego") == "Listo tu cafe llego"
