from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.enums import Role
from app.core.security import decode_access_token, rate_limiter
from app.modules.identity.models import User
from app.modules.identity.service import Actor, build_actor

COOKIE_NAME = "cafe_session"
PANEL_ROLES = (Role.ADMIN, Role.EXPORTER, Role.COMPLIANCE)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def rate_limit(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    if not rate_limiter.allow(f"{ip}:{request.url.path}", get_settings().rate_limit_per_minute):
        raise HTTPException(status_code=429, detail="Demasiadas solicitudes. Intenta en un minuto.")


def current_actor(request: Request, db: Session = Depends(get_db)) -> Actor:
    token = request.cookies.get(COOKIE_NAME)
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    user_id = decode_access_token(token) if token else None
    user = db.get(User, user_id) if user_id else None
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Sesión no válida.")
    return build_actor(db, user)


def panel_actor(actor: Actor = Depends(current_actor)) -> Actor:
    if not actor.has_role(*PANEL_ROLES):
        raise HTTPException(status_code=403, detail="Tu rol no tiene acceso al panel.")
    return actor


def dev_only() -> None:
    if not get_settings().is_dev:
        raise HTTPException(status_code=404, detail="No encontrado.")
