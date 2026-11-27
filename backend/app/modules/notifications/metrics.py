"""Usage metrics and cost estimation with configurable unit rates (no prices are assumed)."""

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.notifications.models import UsageRecord

RATE_BY_KIND = {
    "llm_tokens": ("cost_rate_llm_per_1k_tokens", Decimal("1000")),
    "speech_seconds": ("cost_rate_speech_per_minute", Decimal("60")),
    "document_pages": ("cost_rate_document_per_page", Decimal("1")),
    "whatsapp_message": ("cost_rate_whatsapp_per_message", Decimal("1")),
}


def record_usage(
    db: Session,
    *,
    kind: str,
    provider: str,
    quantity: int,
    unit: str,
    phone: str | None = None,
    lot_id: uuid.UUID | None = None,
    producer_id: uuid.UUID | None = None,
    details: dict | None = None,
) -> None:
    db.add(
        UsageRecord(
            kind=kind,
            provider=provider,
            quantity=quantity,
            unit=unit,
            phone=phone,
            lot_id=lot_id,
            producer_id=producer_id,
            details=details or {},
        )
    )


def usage_summary(db: Session) -> dict:
    settings = get_settings()
    rows = db.execute(
        select(UsageRecord.kind, UsageRecord.provider, UsageRecord.unit, func.sum(UsageRecord.quantity))
        .group_by(UsageRecord.kind, UsageRecord.provider, UsageRecord.unit)
    ).all()
    items = []
    total: Decimal | None = Decimal("0")
    for kind, provider, unit, qty in rows:
        rate_attr, divisor = RATE_BY_KIND.get(kind, (None, Decimal("1")))
        rate = getattr(settings, rate_attr) if rate_attr else None
        cost = (Decimal(qty) / divisor * rate).quantize(Decimal("0.0001")) if rate is not None else None
        if cost is None or provider == "simulated":
            cost = None
        elif total is not None:
            total += cost
        items.append({"kind": kind, "provider": provider, "unit": unit, "quantity": int(qty),
                      "estimated_cost": str(cost) if cost is not None else None})
    return {
        "items": items,
        "estimated_total": str(total) if total else None,
        "note": "Costos estimados solo con tarifas configuradas en variables de entorno. "
                "Los proveedores simulados no generan costo.",
    }
