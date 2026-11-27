from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db, rate_limit
from app.core.config import get_settings
from app.integrations.whatsapp.webhook import InvalidSignature, ingest, schedule_processing

router = APIRouter(tags=["whatsapp"])


@router.get("/webhooks/whatsapp", response_class=PlainTextResponse)
def verify(hub_mode: str = Query(None, alias="hub.mode"), hub_token: str = Query(None, alias="hub.verify_token"),
           hub_challenge: str = Query(None, alias="hub.challenge")) -> str:
    if hub_mode == "subscribe" and hub_token and hub_token == get_settings().whatsapp_verify_token:
        return hub_challenge or ""
    raise HTTPException(status_code=403, detail="Verificación rechazada.")


async def receive_webhook(request: Request, db: Session, provider: str) -> dict:
    raw = await request.body()
    if len(raw) > 1_000_000:
        raise HTTPException(status_code=413, detail="Carga demasiado grande.")
    try:
        result = ingest(db, raw, request.headers.get("x-hub-signature-256"), provider)
    except InvalidSignature as exc:
        raise HTTPException(status_code=401, detail="Firma inválida.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Cuerpo inválido.") from exc
    schedule_processing(result.accepted)
    return {"status": "ok", "accepted": len(result.accepted), "duplicates": result.duplicates,
            "ignored": result.ignored}


@router.post("/webhooks/whatsapp", dependencies=[Depends(rate_limit)])
async def webhook(request: Request, db: Session = Depends(get_db)) -> dict:
    return await receive_webhook(request, db, provider=get_settings().whatsapp_provider)
