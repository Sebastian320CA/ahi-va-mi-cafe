"""Operational commands: python -m app.cli <command>

  seed            Reset the database with the synthetic scenario (development only).
  seed-if-empty   Seed only when no organization exists (used by docker compose).
  documents       Generate synthetic receipts and sheets dated today (Bogota time).
  load-layers     Load additional GeoJSON layers: load-layers <layer> <file> [--real]
  recover         Re-enqueue persisted messages that were not processed.
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from geoalchemy2.shape import from_shape
from shapely.geometry import MultiPolygon, shape

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.modules.producers.models import GeoLayerFeature
from app.seed import seed
from app.synthetic_docs import generate

ROOT = Path(__file__).resolve().parents[2]


def documents() -> None:
    day = datetime.now(ZoneInfo("America/Bogota")).date()
    paths = generate(ROOT / "data" / "documents", day)
    print(f"Documentos sintéticos generados para {day.isoformat()}: {len(paths)}")


def load_layer(layer: str, file: str, real: bool) -> None:
    data = json.loads(Path(file).read_text(encoding="utf-8"))
    meta = data.get("properties", {})
    with SessionLocal() as db:
        n = 0
        for feat in data["features"]:
            geom = shape(feat["geometry"])
            if geom.geom_type == "Polygon":
                geom = MultiPolygon([geom])
            db.add(GeoLayerFeature(layer=layer, source=meta.get("source", Path(file).name), is_synthetic=not real,
                                   reference_date=meta.get("reference_date"), resolution_m=meta.get("resolution_m"),
                                   properties=feat.get("properties", {}), geom=from_shape(geom, srid=4326)))
            n += 1
        db.commit()
    print(f"Capa {layer}: {n} elementos cargados ({'real' if real else 'sintética'}).")


def main(argv: list[str]) -> None:
    cmd = argv[1] if len(argv) > 1 else "help"
    if cmd in ("seed", "seed-if-empty"):
        if get_settings().app_env == "production":
            sys.exit("El seed sintético está deshabilitado en producción.")
        with SessionLocal() as db:
            print(seed(db, reset=cmd == "seed"))
        documents()
    elif cmd == "documents":
        documents()
    elif cmd == "load-layers":
        load_layer(argv[2], argv[3], "--real" in argv)
    elif cmd == "recover":
        from app.workers.tasks import recover_unprocessed_messages

        print(f"Mensajes re-encolados: {recover_unprocessed_messages(0)}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv)
