"""Runs the 10-step demo scenario against a running API through the WhatsApp simulator endpoints.

Usage: python scripts/demo_scenario.py [--api http://localhost:8000] [--wait 2]
Requires APP_ENV=development, the worker running (or QUEUE_MODE=sync) and fresh seed data.
The simulator uses the same webhook ingestion and business services as the real WhatsApp integration.
"""

import argparse
import time

import httpx

PHONES = {"rosa": "573001110101", "acopio": "573001110001", "trilladora": "573001110003",
          "puerto": "573001110004"}


class Demo:
    def __init__(self, api: str, wait: float) -> None:
        self.http = httpx.Client(base_url=api, timeout=60)
        self.wait = wait
        token = self.http.post("/api/auth/login", json={"email": "exportador@demo.cafe",
                                                        "password": "Cafe2026!"}).json()["access_token"]
        self.http.headers["Authorization"] = f"Bearer {token}"

    def send(self, who: str, label: str, **data) -> None:
        phone = PHONES[who]
        before = len(self.conversation(phone))
        r = self.http.post("/api/dev/simulator/messages", data={"phone": phone, **data})
        r.raise_for_status()
        print(f"\n[{who}] {label}")
        for _ in range(int(30 / max(self.wait, 0.1))):
            conv = self.conversation(phone)
            out = [c for c in conv[before:] if c["direction"] == "out" and c["type"] == "reply"]
            if out:
                for c in out:
                    print(f"[asistente] {c['text']}")
                return
            time.sleep(self.wait)
        print("[asistente] (sin respuesta: revisa que el worker esté corriendo)")

    def conversation(self, phone: str) -> list[dict]:
        return self.http.get("/api/dev/simulator/conversation", params={"phone": phone}).json()

    def run(self) -> None:
        nota = ("Buenos días, soy Rosa Méndez y mi finca se llama La Esperanza, en la vereda El Cedro de Pitalito")
        self.send("rosa", f"(nota de voz) {nota}", type="audio", transcript=nota)
        self.send("rosa", "Sí acepto", type="text", text="Sí acepto")
        self.send("rosa", "(ubicación)", type="location", latitude="1.8521", longitude="-76.0512")
        self.send("rosa", "si", type="text", text="si")
        self.send("acopio", "(foto) recibo R-1001", type="image", sample_document="01_recibo_compra_rosa.png")
        self.send("acopio", "si", type="text", text="si")
        self.send("acopio", "(foto) recibo R-1002", type="image",
                  sample_document="02_recibo_compra_pedro_ilegible.png")
        self.send("acopio", "Fueron 350 kilos", type="text", text="Fueron 350 kilos")
        self.send("acopio", "si", type="text", text="si")
        self.send("acopio", "(foto) recibo R-1003", type="image", sample_document="03_recibo_compra_luis_error.png")
        self.send("acopio", "No, ese peso está mal. Fueron 270 kilos", type="text",
                  text="No, ese peso está mal. Fueron 270 kilos")
        self.send("acopio", "si", type="text", text="si")
        self.send("acopio", "Arma el lote con las tres compras de hoy", type="text",
                  text="Arma el lote con las tres compras de hoy")
        self.send("acopio", "si", type="text", text="si")
        self.send("acopio", "(foto) planilla de despacho", type="image",
                  sample_document="04_planilla_despacho_caf001.png")
        self.send("acopio", "si", type="text", text="si")
        self.send("trilladora", "(foto) planilla de recepción", type="image",
                  sample_document="05_planilla_recepcion_caf001.png")
        self.send("trilladora", "si", type="text", text="si")
        self.send("trilladora", "ALR-001 Un saco se rompió en el cargue", type="text",
                  text="ALR-001 Un saco se rompió en el cargue y se derramó café")
        self.send("trilladora", "si", type="text", text="si")
        print("\n>>> Resuelve la alerta ALR-001 desde el panel (Alertas) para continuar el guion en vivo.")
        self.send("trilladora", "(foto) registro de trilla", type="image",
                  sample_document="06_registro_trilla_caf001.png")
        self.send("trilladora", "si", type="text", text="si")
        self.send("trilladora", "(foto) planilla de despacho a puerto", type="image",
                  sample_document="07_planilla_despacho_caf001v.png")
        self.send("trilladora", "si", type="text", text="si")
        self.send("puerto", "(foto) planilla de recepción en puerto", type="image",
                  sample_document="08_planilla_recepcion_caf001v.png")
        self.send("puerto", "si", type="text", text="si")
        assess = self.http.post("/api/farms/assess").json()
        print(f"\n[panel] Evaluación ambiental: {assess['results']}")
        self.send("rosa", "¿Dónde va mi café?", type="text", text="¿Dónde va mi café?")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--wait", type=float, default=0.5)
    args = parser.parse_args()
    Demo(args.api, args.wait).run()
