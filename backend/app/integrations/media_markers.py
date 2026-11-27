"""Markers that let the SIMULATED speech and document adapters read synthetic files.

Synthetic receipts (PNG) carry a tEXt chunk and synthetic voice notes (WAV) carry a RIFF chunk with the
ground truth that a real provider would have to infer. Only simulated adapters read these markers; real
adapters ignore them and process the pixels or audio. This keeps simulated results explicit and honest.
"""

import io
import json
import struct

PNG_KEY = "ahivamicafe:simulated_ocr"
WAV_CHUNK = b"smtx"


def read_png_marker(data: bytes) -> dict | None:
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(data))
        raw = img.info.get(PNG_KEY)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def build_wav_with_transcript(transcript: str, seconds: float = 1.0, rate: int = 8000) -> bytes:
    frames = b"\x00\x00" * int(rate * seconds)
    fmt = struct.pack("<HHIIHH", 1, 1, rate, rate * 2, 2, 16)
    text = transcript.encode("utf-8")
    if len(text) % 2:
        text += b"\x00"
    chunks = b"fmt " + struct.pack("<I", len(fmt)) + fmt
    chunks += WAV_CHUNK + struct.pack("<I", len(text)) + text
    chunks += b"data" + struct.pack("<I", len(frames)) + frames
    return b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WAVE" + chunks


def read_wav_marker(data: bytes) -> tuple[str | None, float | None]:
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return None, None
    pos, transcript, duration, rate_bytes = 12, None, None, None
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        size = struct.unpack("<I", data[pos + 4:pos + 8])[0]
        body = data[pos + 8:pos + 8 + size]
        if cid == WAV_CHUNK:
            transcript = body.rstrip(b"\x00").decode("utf-8")
        elif cid == b"fmt " and len(body) >= 12:
            rate_bytes = struct.unpack("<I", body[8:12])[0]
        elif cid == b"data" and rate_bytes:
            duration = size / rate_bytes
        pos += 8 + size + (size % 2)
    return transcript, duration
