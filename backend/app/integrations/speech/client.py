"""Speech to text. Real adapter: Azure AI Speech REST API for short audio. Simulated: synthetic WAV marker."""

from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import httpx

from app.core.config import get_settings
from app.integrations.media_markers import read_wav_marker


@dataclass
class Transcription:
    text: str | None
    duration_seconds: float | None
    provider: str
    confidence: float | None = None


class SpeechClient(Protocol):
    name: str

    def transcribe(self, data: bytes, mime_type: str) -> Transcription: ...


CONTENT_TYPES = {
    "audio/ogg": "audio/ogg; codecs=opus",
    "audio/wav": "audio/wav; codecs=audio/pcm; samplerate=16000",
}


class AzureSpeechClient:
    """Uses the short-audio REST endpoint (up to 60 s), which accepts OGG/Opus as sent by WhatsApp."""

    name = "azure_speech"

    def __init__(self) -> None:
        s = get_settings()
        self.url = (f"https://{s.azure_speech_region}.stt.speech.microsoft.com/speech/recognition/"
                    f"conversation/cognitiveservices/v1")
        self.key = s.azure_speech_key
        self.language = s.speech_language

    def transcribe(self, data: bytes, mime_type: str) -> Transcription:
        base = mime_type.split(";")[0].strip()
        if base not in CONTENT_TYPES:
            raise ValueError(f"Formato de audio no soportado por el adaptador: {mime_type}")
        resp = httpx.post(self.url, params={"language": self.language, "format": "detailed"}, content=data,
                          headers={"Ocp-Apim-Subscription-Key": self.key, "Content-Type": CONTENT_TYPES[base],
                                   "Accept": "application/json"}, timeout=60)
        resp.raise_for_status()
        body = resp.json()
        if body.get("RecognitionStatus") != "Success":
            return Transcription(None, None, self.name)
        best = (body.get("NBest") or [{}])[0]
        duration = body.get("Duration")
        return Transcription(text=body.get("DisplayText"), duration_seconds=duration / 1e7 if duration else None,
                             provider=self.name, confidence=best.get("Confidence"))


class SimulatedSpeechClient:
    name = "simulated"

    def transcribe(self, data: bytes, mime_type: str) -> Transcription:
        text, duration = read_wav_marker(data)
        if text is None:
            raise ValueError("El transcriptor simulado solo procesa notas de voz sintéticas del simulador.")
        return Transcription(text=text, duration_seconds=duration, provider=self.name, confidence=None)


@lru_cache
def get_speech_client() -> SpeechClient:
    if get_settings().speech_provider == "azure":
        return AzureSpeechClient()
    return SimulatedSpeechClient()
