"""Domain enumerations. Stored as plain strings with CHECK constraints for portability."""

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    EXPORTER = "exporter"
    COMPLIANCE = "compliance_officer"
    COLLECTION_OPERATOR = "collection_center_operator"
    TRANSPORTER = "transporter"
    MILL_OPERATOR = "mill_operator"
    PORT_OPERATOR = "port_operator"
    PRODUCER = "producer"


class OrgKind(StrEnum):
    EXPORTER = "exporter"
    COOPERATIVE = "cooperative"
    COLLECTION_CENTER = "collection_center"
    TRANSPORTER = "transporter"
    MILL = "mill"
    PORT = "port"


class CoffeeState(StrEnum):
    CHERRY = "cereza"
    WET_PARCHMENT = "pergamino_humedo"
    DRY_PARCHMENT = "pergamino_seco"
    GREEN = "verde"


COFFEE_STATE_LABELS = {
    CoffeeState.CHERRY: "café cereza",
    CoffeeState.WET_PARCHMENT: "café pergamino húmedo",
    CoffeeState.DRY_PARCHMENT: "café pergamino seco",
    CoffeeState.GREEN: "café verde",
}


class LocationStatus(StrEnum):
    DECLARED = "declared"
    PENDING_VERIFICATION = "pending_verification"
    REVIEWED = "reviewed"


class LotStatus(StrEnum):
    IN_STORAGE = "in_storage"
    IN_TRANSIT = "in_transit"
    TRANSFORMED = "transformed"


class ShipmentStatus(StrEnum):
    IN_TRANSIT = "in_transit"
    RECONCILED = "reconciled"
    DISCREPANCY = "discrepancy"
    RESOLVED = "resolved"


class EventType(StrEnum):
    PURCHASE = "compra_en_acopio"
    LOT_CREATION = "creacion_lote"
    CONSOLIDATION = "consolidacion"
    DISPATCH = "despacho"
    RECEPTION = "recepcion"
    TRANSFORMATION = "transformacion"
    CORRECTION = "correccion"


class AlertStatus(StrEnum):
    OPEN = "open"
    JUSTIFICATION_REQUESTED = "justification_requested"
    IN_REVIEW = "in_review"
    RESOLVED = "resolved"


class AlertClassification(StrEnum):
    RECORDING_ERROR = "error_registro"
    MOISTURE_VARIATION = "variacion_humedad"
    NATURAL_SHRINKAGE = "merma_natural"
    TRANSFORMATION = "transformacion"
    JUSTIFIED_SHORTAGE = "faltante_justificado"
    UNJUSTIFIED_SHORTAGE = "faltante_sin_justificar"
    SURPLUS_PENDING = "excedente_pendiente"


class AssessmentResult(StrEnum):
    NO_INDICATIONS = "no_indications"
    RISK_IDENTIFIED = "risk_identified"
    INSUFFICIENT_INFORMATION = "insufficient_information"


class CaseStatus(StrEnum):
    INCOMPLETE = "incomplete"
    PENDING_REVIEW = "pending_review"
    RISK_IDENTIFIED = "risk_identified"
    REVIEWED = "reviewed"
    APPROVED_INTERNAL = "approved_internal"
    NOT_APPROVED = "not_approved"


class MessageStatus(StrEnum):
    RECEIVED = "received"
    QUEUED = "queued"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"


class PendingStatus(StrEnum):
    PENDING = "pending"
    EXECUTED = "executed"
    CANCELLED = "cancelled"
    FAILED = "failed"


def check_in(column: str, enum_cls: type[StrEnum]) -> str:
    values = ", ".join(f"'{v.value}'" for v in enum_cls)
    return f"{column} IN ({values})"
