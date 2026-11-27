"""Generates synthetic receipt and sheet photos for the demo.

Each PNG is rendered with real text so that Azure AI Document Intelligence can read it when credentials exist.
It also embeds a ground-truth marker that only the SIMULATED document adapter reads (see media_markers.py).
One receipt has an illegible weight and another has a wrong weight written on paper, to exercise
clarification and natural-language correction.
"""

import io
import json
import random
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from PIL.PngImagePlugin import PngInfo

from app.integrations.media_markers import PNG_KEY

FONT_CANDIDATES = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf"]
MONO_CANDIDATES = ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", "/usr/share/fonts/dejavu/DejaVuSansMono.ttf"]


def _font(size: int, mono: bool = False):
    for path in MONO_CANDIDATES if mono else FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def documents_for(day: date) -> list[dict]:
    d = day.isoformat()
    shown = day.strftime("%d/%m/%Y")
    center = "Centro de Acopio Pitalito (sintético)"
    return [
        {"file": "01_recibo_compra_rosa.png", "org": center, "title": "RECIBO DE COMPRA",
         "fields": [("No. recibo", "R-1001", None), ("Fecha", shown, d), ("Productor", "Rosa Méndez", None),
                    ("Finca", "La Esperanza", None), ("Estado", "Pergamino seco", None), ("Sacos", "8", None),
                    ("Peso bruto", "383 kg", None), ("Tara", "3 kg", None), ("Peso neto", "380 kg", None),
                    ("Humedad", "11,2 %", None), ("Factor de rendimiento", "92", None)],
         "keys": {"No. recibo": "document_number", "Fecha": "date", "Productor": "producer", "Finca": "farm",
                  "Estado": "coffee_state", "Sacos": "sacks", "Peso bruto": "gross_weight_kg", "Tara": "tare_kg",
                  "Peso neto": "net_weight_kg", "Humedad": "moisture_pct", "Factor de rendimiento": "yield_factor"},
         "type": "purchase_receipt"},
        {"file": "02_recibo_compra_pedro_ilegible.png", "org": center, "title": "RECIBO DE COMPRA",
         "fields": [("No. recibo", "R-1002", None), ("Fecha", shown, d), ("Productor", "Pedro Ramírez", None),
                    ("Finca", "El Paraíso", None), ("Estado", "Pergamino seco", None), ("Sacos", "7", None),
                    ("Peso bruto", "353 kg", None), ("Tara", "3 kg", None), ("Peso neto", "3?0 kg", "SMUDGE"),
                    ("Humedad", "11,5 %", None)],
         "keys": {"No. recibo": "document_number", "Fecha": "date", "Productor": "producer", "Finca": "farm",
                  "Estado": "coffee_state", "Sacos": "sacks", "Peso bruto": "gross_weight_kg", "Tara": "tare_kg",
                  "Peso neto": "net_weight_kg", "Humedad": "moisture_pct"},
         "low_confidence": {"net_weight_kg": 0.31}, "type": "purchase_receipt"},
        {"file": "03_recibo_compra_luis_error.png", "org": center, "title": "RECIBO DE COMPRA",
         "fields": [("No. recibo", "R-1003", None), ("Fecha", shown, d), ("Productor", "Luis Cárdenas", None),
                    ("Finca", "Los Andes", None), ("Estado", "Pergamino seco", None), ("Sacos", "6", None),
                    ("Peso bruto", "273 kg", None), ("Tara", "3 kg", None), ("Peso neto", "207 kg", None),
                    ("Humedad", "11,0 %", None)],
         "keys": {"No. recibo": "document_number", "Fecha": "date", "Productor": "producer", "Finca": "farm",
                  "Estado": "coffee_state", "Sacos": "sacks", "Peso bruto": "gross_weight_kg", "Tara": "tare_kg",
                  "Peso neto": "net_weight_kg", "Humedad": "moisture_pct"},
         "type": "purchase_receipt"},
        {"file": "04_planilla_despacho_caf001.png", "org": center, "title": "PLANILLA DE DESPACHO",
         "fields": [("No. planilla", "D-501", None), ("Fecha", shown, d), ("Lote", "CAF-001", None),
                    ("Estado", "Pergamino seco", None), ("Sacos", "20", None), ("Peso neto", "1.000 kg", None),
                    ("Sello", "4471", None), ("Placa", "SXT123", None), ("Origen", center, None),
                    ("Destino", "Trilladora Neiva", None), ("Entrega", "Transportes del Sur", None)],
         "keys": {"No. planilla": "document_number", "Fecha": "date", "Lote": "lot_code", "Estado": "coffee_state",
                  "Sacos": "sacks", "Peso neto": "net_weight_kg", "Sello": "seal", "Placa": "vehicle_plate",
                  "Origen": "origin", "Destino": "destination", "Entrega": "delivered_by"},
         "type": "dispatch_sheet"},
        {"file": "05_planilla_recepcion_caf001.png", "org": "Trilladora Neiva (sintética)",
         "title": "PLANILLA DE RECEPCIÓN",
         "fields": [("No. planilla", "RC-301", None), ("Fecha", shown, d), ("Lote", "CAF-001", None),
                    ("Estado", "Pergamino seco", None), ("Sacos", "19", None), ("Peso recibido", "952 kg", None),
                    ("Sello", "4471", None), ("Recibe", "Andrés Trilladora", None)],
         "keys": {"No. planilla": "document_number", "Fecha": "date", "Lote": "lot_code", "Estado": "coffee_state",
                  "Sacos": "sacks", "Peso recibido": "net_weight_kg", "Sello": "seal", "Recibe": "received_by"},
         "type": "reception_sheet"},
        {"file": "06_registro_trilla_caf001.png", "org": "Trilladora Neiva (sintética)", "title": "REGISTRO DE TRILLA",
         "fields": [("Fecha", shown, d), ("Lote", "CAF-001", None), ("Estado", "Pergamino seco", None),
                    ("Peso de entrada", "952 kg", None), ("Estado de salida", "Café verde", None),
                    ("Peso de salida", "714 kg", None)],
         "keys": {"Fecha": "date", "Lote": "lot_code", "Estado": "coffee_state", "Peso de entrada": "input_kg",
                  "Estado de salida": "output_state", "Peso de salida": "output_kg"},
         "type": "transformation_record"},
        {"file": "07_planilla_despacho_caf001v.png", "org": "Trilladora Neiva (sintética)",
         "title": "PLANILLA DE DESPACHO",
         "fields": [("No. planilla", "D-777", None), ("Fecha", shown, d), ("Lote", "CAF-001-V", None),
                    ("Estado", "Café verde", None), ("Sacos", "10", None), ("Peso neto", "714 kg", None),
                    ("Sello", "9001", None), ("Placa", "TPK482", None), ("Origen", "Trilladora Neiva", None),
                    ("Destino", "Bodega Puerto Buenaventura", None), ("Entrega", "Transportes del Sur", None)],
         "keys": {"No. planilla": "document_number", "Fecha": "date", "Lote": "lot_code", "Estado": "coffee_state",
                  "Sacos": "sacks", "Peso neto": "net_weight_kg", "Sello": "seal", "Placa": "vehicle_plate",
                  "Origen": "origin", "Destino": "destination", "Entrega": "delivered_by"},
         "type": "dispatch_sheet"},
        {"file": "08_planilla_recepcion_caf001v.png", "org": "Bodega Puerto Buenaventura (sintética)",
         "title": "PLANILLA DE RECEPCIÓN",
         "fields": [("No. planilla", "RC-902", None), ("Fecha", shown, d), ("Lote", "CAF-001-V", None),
                    ("Estado", "Café verde", None), ("Sacos", "10", None), ("Peso recibido", "714 kg", None),
                    ("Sello", "9001", None), ("Recibe", "Sofía Puerto", None)],
         "keys": {"No. planilla": "document_number", "Fecha": "date", "Lote": "lot_code", "Estado": "coffee_state",
                  "Sacos": "sacks", "Peso recibido": "net_weight_kg", "Sello": "seal", "Recibe": "received_by"},
         "type": "reception_sheet"},
    ]


def render(doc: dict, seed: int = 7) -> bytes:
    rng = random.Random(seed + len(doc["file"]))
    w, h = 900, 140 + 64 * len(doc["fields"]) + 120
    img = Image.new("RGB", (w, h), (247, 243, 233))
    draw = ImageDraw.Draw(img)
    draw.rectangle([18, 18, w - 18, h - 18], outline=(120, 110, 95), width=2)
    draw.text((40, 34), doc["org"], font=_font(24), fill=(60, 50, 40))
    draw.text((40, 72), doc["title"], font=_font(34), fill=(30, 30, 30))
    draw.text((w - 330, 40), "DOCUMENTO SINTÉTICO", font=_font(18), fill=(150, 40, 40))
    y = 140
    for label, value, extra in doc["fields"]:
        draw.text((48, y), f"{label}:", font=_font(26), fill=(40, 40, 40))
        draw.text((390, y), value, font=_font(28, mono=True), fill=(20, 30, 90))
        if extra == "SMUDGE":
            for _ in range(90):
                x0, y0 = 385 + rng.randint(0, 110), y + rng.randint(-6, 30)
                draw.ellipse([x0, y0, x0 + rng.randint(8, 22), y0 + rng.randint(6, 16)], fill=(95, 85, 75))
        draw.line([(380, y + 38), (w - 60, y + 38)], fill=(200, 190, 175), width=1)
        y += 64
    draw.text((48, h - 80), "Firma entrega: ______________    Firma recibe: ______________", font=_font(20),
              fill=(70, 70, 70))
    img = img.rotate(rng.uniform(-1.2, 1.2), expand=False, fillcolor=(235, 230, 220)).filter(
        ImageFilter.GaussianBlur(0.4))
    fields = {"document_type": doc["type"]}
    confidence: dict[str, float] = {"document_type": 0.99}
    for label, value, extra in doc["fields"]:
        key = doc["keys"][label]
        is_date = extra not in (None, "SMUDGE")
        fields[key] = extra if is_date else value
        confidence[key] = doc.get("low_confidence", {}).get(key, round(rng.uniform(0.9, 0.99), 2))
    meta = PngInfo()
    meta.add_text(PNG_KEY, json.dumps({"fields": fields, "confidence": confidence, "synthetic": True},
                                      ensure_ascii=False))
    out = io.BytesIO()
    img.save(out, format="PNG", pnginfo=meta)
    return out.getvalue()


def generate(target_dir: Path, day: date) -> list[Path]:
    target_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for doc in documents_for(day):
        path = target_dir / doc["file"]
        path.write_bytes(render(doc))
        paths.append(path)
    return paths
