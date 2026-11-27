"""Identity, roles and organization-scoped authorization."""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import OrgKind, Role
from app.core.errors import Forbidden, NotFound
from app.core.security import verify_password
from app.modules.identity.models import Membership, Organization, SupplyChainLink, User


@dataclass(frozen=True)
class RoleGrant:
    role: Role
    organization_id: uuid.UUID
    organization_kind: str
    organization_name: str


@dataclass
class Actor:
    user: User
    grants: list[RoleGrant] = field(default_factory=list)

    @property
    def id(self) -> uuid.UUID:
        return self.user.id

    def has_role(self, *roles: Role) -> bool:
        return any(g.role in roles for g in self.grants)

    def orgs_for(self, *roles: Role) -> list[uuid.UUID]:
        return [g.organization_id for g in self.grants if g.role in roles]

    def org_for(self, *roles: Role) -> uuid.UUID:
        orgs = self.orgs_for(*roles)
        if not orgs:
            raise Forbidden("No tienes un rol autorizado para esta operación.", code="role_required")
        return orgs[0]

    def require(self, *roles: Role) -> None:
        if not self.has_role(*roles):
            raise Forbidden("No tienes un rol autorizado para esta operación.", code="role_required")

    @property
    def is_admin(self) -> bool:
        return self.has_role(Role.ADMIN)

    def role_names(self) -> list[str]:
        return sorted({g.role.value for g in self.grants})


def build_actor(db: Session, user: User) -> Actor:
    rows = db.execute(
        select(Membership, Organization)
        .join(Organization, Organization.id == Membership.organization_id)
        .where(Membership.user_id == user.id, Membership.is_active.is_(True))
    ).all()
    grants = [RoleGrant(Role(m.role), o.id, o.kind, o.name) for m, o in rows]
    return Actor(user=user, grants=grants)


def authenticate(db: Session, email: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.email == email.lower().strip(), User.is_active.is_(True)))
    if user and verify_password(password, user.password_hash):
        return user
    return None


def exporter_for_org(db: Session, org_id: uuid.UUID) -> uuid.UUID:
    org = db.get(Organization, org_id)
    if org is None:
        raise NotFound("Organización no encontrada.")
    if org.kind == OrgKind.EXPORTER.value:
        return org.id
    link = db.scalar(select(SupplyChainLink).where(SupplyChainLink.member_org_id == org_id).limit(1))
    if link is None:
        raise Forbidden("La organización no está vinculada a ninguna cadena autorizada.", code="no_chain")
    return link.exporter_org_id


def chain_members(db: Session, exporter_org_id: uuid.UUID) -> set[uuid.UUID]:
    ids = set(
        db.scalars(
            select(SupplyChainLink.member_org_id).where(SupplyChainLink.exporter_org_id == exporter_org_id)
        )
    )
    ids.add(exporter_org_id)
    return ids


def accessible_exporters(db: Session, actor: Actor) -> set[uuid.UUID] | None:
    """Returns the set of exporter chains the actor may read. None means unrestricted (admin)."""
    if actor.is_admin:
        return None
    result: set[uuid.UUID] = set()
    for grant in actor.grants:
        if grant.role == Role.PRODUCER:
            continue
        try:
            result.add(exporter_for_org(db, grant.organization_id))
        except (Forbidden, NotFound):
            continue
    return result


def require_chain_access(db: Session, actor: Actor, exporter_org_id: uuid.UUID) -> None:
    allowed = accessible_exporters(db, actor)
    if allowed is not None and exporter_org_id not in allowed:
        # Resources outside the authorized chain are reported as missing to avoid leaking existence.
        raise NotFound("Recurso no encontrado.")


def org_in_same_chain(db: Session, org_id: uuid.UUID, exporter_org_id: uuid.UUID) -> bool:
    return org_id in chain_members(db, exporter_org_id)


def find_org_by_code(db: Session, code: str) -> Organization | None:
    return db.scalar(select(Organization).where(Organization.code == code))


def users_for_phone(db: Session, phone: str) -> list[User]:
    return list(
        db.scalars(select(User).where(User.whatsapp_phone == phone, User.is_active.is_(True)).order_by(
            User.created_at
        ))
    )
