"""Preliminary environmental assessment with real PostGIS operations over prepared layers.

The layers loaded in geo_layer_features may be real (for example exported from Global Forest Watch) or
synthetic. Synthetic layers are flagged and every result carries that flag. Results are support signals,
not certifications. A match with a 2020 forest layer alone does not prove later deforestation.
"""

from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import AssessmentResult, LocationStatus
from app.modules.producers.models import Farm, FarmAssessment, GeoLayerFeature

FOREST_LAYER = "forest_2020"
LOSS_LAYER = "forest_loss_after_2020"
MIN_LOSS_HA = Decimal("0.0001")

BASE_LIMITATIONS = [
    "Resultado preliminar de apoyo; no constituye certificación ni declaración de diligencia debida.",
    "El café bajo sombra puede confundirse con cobertura forestal en imágenes satelitales.",
    "La imagen o capa no demuestra propiedad de la tierra ni exactitud de linderos.",
]

OVERLAP_SQL = text("""
    SELECT COALESCE(SUM(ST_Area(ST_Intersection(g.geom, t.geom)::geography)) / 10000.0, 0)
    FROM geo_layer_features g, (SELECT ST_GeomFromEWKB(:geom) AS geom) t
    WHERE g.layer = :layer AND ST_Intersects(g.geom, t.geom)
""")


def _layer_meta(db: Session, layer: str) -> dict | None:
    row = db.execute(
        select(GeoLayerFeature.source, GeoLayerFeature.is_synthetic, GeoLayerFeature.reference_date,
               GeoLayerFeature.resolution_m, func.count())
        .where(GeoLayerFeature.layer == layer)
        .group_by(GeoLayerFeature.source, GeoLayerFeature.is_synthetic, GeoLayerFeature.reference_date,
                  GeoLayerFeature.resolution_m)
    ).first()
    if row is None:
        return None
    return {"layer": layer, "source": row[0], "is_synthetic": row[1], "reference_date": row[2],
            "resolution_m": float(row[3]) if row[3] is not None else None, "features": row[4]}


def assess_farm(db: Session, farm: Farm) -> FarmAssessment:
    settings = get_settings()
    plot = next((pl for pl in farm.plots if pl.polygon is not None), None)
    limitations = list(BASE_LIMITATIONS)
    reasons: list[str] = []
    geom_ewkb = None
    basis = "none"
    if plot is not None:
        basis = "plot_polygon"
        geom_ewkb = db.execute(text("SELECT ST_AsEWKB(polygon) FROM plots WHERE id = :i"), {"i": plot.id}).scalar()
    elif farm.location is not None and farm.declared_area_ha is not None \
            and Decimal(farm.declared_area_ha) <= settings.polygon_required_above_ha:
        basis = "point_buffer_declared_area"
        radius_m = float((Decimal(farm.declared_area_ha) * 10000 / Decimal("3.14159")).sqrt())
        geom_ewkb = db.execute(text("SELECT ST_AsEWKB(ST_Buffer(location::geography, :r)::geometry) FROM farms "
                                    "WHERE id = :i"), {"r": radius_m, "i": farm.id}).scalar()
        limitations.append("Se evaluó un círculo equivalente al área declarada alrededor del punto compartido.")
    if farm.location_status == LocationStatus.PENDING_VERIFICATION.value:
        limitations.append("La ubicación está pendiente de verificación.")

    forest_meta, loss_meta = _layer_meta(db, FOREST_LAYER), _layer_meta(db, LOSS_LAYER)
    sources = [m for m in (forest_meta, loss_meta) if m]
    synthetic = any(m["is_synthetic"] for m in sources)
    if synthetic:
        limitations.append("Se utilizaron capas SINTÉTICAS de demostración; no representan cobertura real.")

    area = forest = loss = None
    if geom_ewkb is None:
        result = AssessmentResult.INSUFFICIENT_INFORMATION
        if farm.location is None:
            reasons.append("La finca no tiene ubicación registrada.")
        else:
            reasons.append("Solo hay un punto sin área declarada ni polígono de parcela; no es posible delimitar "
                           "el área a evaluar.")
    elif loss_meta is None:
        result = AssessmentResult.INSUFFICIENT_INFORMATION
        reasons.append("No hay una capa de pérdida de bosque posterior al 31/12/2020 cargada para la zona.")
    else:
        geom = bytes(geom_ewkb)
        area = Decimal(str(db.execute(text("SELECT ST_Area(ST_GeomFromEWKB(:g)::geography) / 10000.0"),
                                      {"g": geom}).scalar_one()))
        forest = Decimal(str(db.execute(OVERLAP_SQL, {"geom": geom, "layer": FOREST_LAYER}).scalar_one()))
        loss = Decimal(str(db.execute(OVERLAP_SQL, {"geom": geom, "layer": LOSS_LAYER}).scalar_one()))
        if loss > MIN_LOSS_HA:
            result = AssessmentResult.RISK_IDENTIFIED
            reasons.append(f"El área evaluada se superpone con {loss:.4f} ha de pérdida de bosque registrada "
                           f"después de la fecha de corte {settings.eudr_cutoff_date}.")
        else:
            result = AssessmentResult.NO_INDICATIONS
            reasons.append("No se detectó superposición con pérdida de bosque posterior a la fecha de corte en las "
                           "capas disponibles.")
        if forest and forest > 0:
            reasons.append(f"Hay {forest:.4f} ha de superposición con la capa de bosque 2020. Esto por sí solo no "
                           f"demuestra deforestación posterior.")
    assessment = FarmAssessment(
        farm_id=farm.id, plot_id=plot.id if plot else None, result=result.value, geometry_basis=basis,
        assessed_area_ha=area.quantize(Decimal("0.0001")) if area is not None else None,
        forest_2020_overlap_ha=forest.quantize(Decimal("0.0001")) if forest is not None else None,
        loss_after_cutoff_ha=loss.quantize(Decimal("0.0001")) if loss is not None else None,
        sources=sources, limitations=limitations, reasons=reasons, uses_synthetic_layers=synthetic,
        rule_version=settings.due_diligence_rule_version)
    db.add(assessment)
    db.flush()
    return assessment


def latest_assessment(db: Session, farm_id) -> FarmAssessment | None:
    return db.scalar(select(FarmAssessment).where(FarmAssessment.farm_id == farm_id)
                     .order_by(FarmAssessment.queried_at.desc()).limit(1))
