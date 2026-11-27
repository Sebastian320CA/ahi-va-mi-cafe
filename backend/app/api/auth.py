from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import COOKIE_NAME, PANEL_ROLES, current_actor, get_db, rate_limit
from app.core.config import get_settings
from app.core.security import create_access_token
from app.modules.audit import service as audit
from app.modules.identity.service import Actor, authenticate, build_actor

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: str
    password: str


def actor_out(actor: Actor) -> dict:
    return {"id": str(actor.id), "full_name": actor.user.full_name, "email": actor.user.email,
            "roles": [{"role": g.role.value, "organization": g.organization_name,
                       "organization_id": str(g.organization_id)} for g in actor.grants]}


@router.post("/login", dependencies=[Depends(rate_limit)])
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)) -> dict:
    user = authenticate(db, body.email, body.password)
    if user is None:
        audit.record(db, operation="auth.login", resource_type="user", resource_id=body.email[:80], result="failed")
        db.commit()
        raise HTTPException(status_code=401, detail="Correo o contraseña incorrectos.")
    actor = build_actor(db, user)
    if not actor.has_role(*PANEL_ROLES):
        raise HTTPException(status_code=403, detail="Tu rol no tiene acceso al panel.")
    token = create_access_token(user.id)
    response.set_cookie(COOKIE_NAME, token, httponly=True, samesite="lax", secure=not get_settings().is_dev,
                        max_age=get_settings().access_token_minutes * 60, path="/")
    audit.record(db, operation="auth.login", resource_type="user", resource_id=user.id, actor_user_id=user.id)
    db.commit()
    return {"access_token": token, "token_type": "bearer", "user": actor_out(actor)}


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
def me(actor: Actor = Depends(current_actor)) -> dict:
    return actor_out(actor)
