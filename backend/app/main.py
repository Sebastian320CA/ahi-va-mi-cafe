"""FastAPI application: modular monolith entrypoint."""

import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import models as _models  # noqa: F401  (register all models)
from app.api import auth, dashboard, simulator, whatsapp
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.errors import DomainError
from app.core.observability import configure_logging, correlation_id_var, new_correlation_id

settings = get_settings()
configure_logging(settings.log_level)

app = FastAPI(title="Ahí va mi café API", version="0.1.0",
              description="MVP de trazabilidad logística, documental y ambiental del café colombiano.")
app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_url], allow_credentials=True,
                   allow_methods=["GET", "POST", "PATCH"], allow_headers=["*"])


@app.middleware("http")
async def correlation(request: Request, call_next):
    cid = request.headers.get("x-correlation-id") or new_correlation_id()
    correlation_id_var.set(cid[:64])
    started = time.monotonic()
    response = await call_next(request)
    response.headers["x-correlation-id"] = cid[:64]
    response.headers["x-response-time-ms"] = str(int((time.monotonic() - started) * 1000))
    response.headers["x-content-type-options"] = "nosniff"
    return response


@app.exception_handler(DomainError)
async def domain_error(_: Request, exc: DomainError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message, "code": exc.code})


app.include_router(auth.router)
app.include_router(whatsapp.router)
app.include_router(dashboard.router)
if settings.is_dev:
    app.include_router(simulator.router)


@app.get("/health", tags=["health"])
def health() -> dict:
    status = {"app": "ok", "environment": settings.app_env,
              "providers": {"whatsapp": settings.whatsapp_provider, "llm": settings.llm_provider,
                            "speech": settings.speech_provider, "documents": settings.document_provider,
                            "storage": settings.storage_provider, "geo": settings.geo_provider}}
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        status["database"] = "ok"
    except Exception:
        status["database"] = "error"
    try:
        from app.core.queue import get_redis

        get_redis().ping()
        status["redis"] = "ok"
    except Exception:
        status["redis"] = "unavailable"
    return status
