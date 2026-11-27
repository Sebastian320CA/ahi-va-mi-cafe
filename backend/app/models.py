"""Import every model so SQLAlchemy metadata and Alembic see the full schema."""

from app.modules.audit.models import AuditLog
from app.modules.compliance.models import DueDiligenceCase, DueDiligenceReview
from app.modules.identity.models import Membership, Organization, SupplyChainLink, User
from app.modules.notifications.models import (
    ConversationState,
    IncomingMessage,
    Notification,
    OutgoingMessage,
    PendingOperation,
    UsageRecord,
)
from app.modules.producers.models import (
    ConsentRecord,
    Farm,
    FarmAssessment,
    GeoLayerFeature,
    Plot,
    Producer,
)
from app.modules.reconciliation.models import AlertResolution, ReconciliationAlert
from app.modules.traceability.models import (
    CoffeeLot,
    CustodyEvent,
    DocumentEvidence,
    LotComposition,
    Purchase,
    Shipment,
)

__all__ = [
    "AlertResolution",
    "AuditLog",
    "CoffeeLot",
    "ConsentRecord",
    "ConversationState",
    "CustodyEvent",
    "DocumentEvidence",
    "DueDiligenceCase",
    "DueDiligenceReview",
    "Farm",
    "FarmAssessment",
    "GeoLayerFeature",
    "IncomingMessage",
    "LotComposition",
    "Membership",
    "Notification",
    "Organization",
    "OutgoingMessage",
    "PendingOperation",
    "Plot",
    "Producer",
    "Purchase",
    "ReconciliationAlert",
    "Shipment",
    "SupplyChainLink",
    "UsageRecord",
    "User",
]
