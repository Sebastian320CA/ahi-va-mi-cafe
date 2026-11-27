import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.observability import correlation_id_var
from app.modules.audit.models import AuditLog


def record(
    db: Session,
    *,
    operation: str,
    resource_type: str,
    resource_id: Any = None,
    actor_user_id: uuid.UUID | None = None,
    organization_id: uuid.UUID | None = None,
    result: str = "success",
    details: dict | None = None,
) -> AuditLog:
    previous = None
    if resource_id is not None:
        previous = db.scalar(
            select(AuditLog.id)
            .where(AuditLog.resource_type == resource_type, AuditLog.resource_id == str(resource_id))
            .order_by(AuditLog.id.desc())
            .limit(1)
        )
    entry = AuditLog(
        actor_user_id=actor_user_id,
        organization_id=organization_id,
        operation=operation,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        result=result,
        correlation_id=correlation_id_var.get(),
        previous_audit_id=previous,
        details=details or {},
    )
    db.add(entry)
    db.flush()
    return entry
