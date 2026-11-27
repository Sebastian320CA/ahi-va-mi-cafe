"""Deterministic parsing used before (or instead of) the LLM: confirmations, codes, units and fields."""

import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.core.enums import CoffeeState

BOGOTA = ZoneInfo("America/Bogota")

YES = {"si", "sí", "correcto", "confirmo", "confirmado", "asi es", "así es", "ok", "dale", "listo", "de acuerdo",
       "acepto", "si acepto", "sí acepto", "si señor", "si senor", "esta bien", "está bien", "si correcto"}
NO = {"no", "incorrecto", "no es correcto", "esta mal", "está mal", "no acepto"}
CANCEL = {"cancelar", "cancela", "cancelalo", "anular", "olvidalo", "olvídalo"}

LOT_RE = re.compile(r"\bCAF-\d{3}(?:-V)?\b", re.IGNORECASE)
PURCHASE_RE = re.compile(r"\bCOM-\d{4}\b", re.IGNORECASE)
ALERT_RE = re.compile(r"\bALR-\d{3}\b", re.IGNORECASE)
PENDING_RE = re.compile(r"\bOP-\d{3,}\b", re.IGNORECASE)


def strip_accents(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def norm(text: str) -> str:
    t = strip_accents(text or "").lower().strip()
    t = re.sub(r"[¡!¿?.,;:]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def is_yes(text: str) -> bool:
    n = norm(PENDING_RE.sub("", text))
    return n in {norm(y) for y in YES}


def is_no(text: str) -> bool:
    return norm(text) in {norm(x) for x in NO}


def is_cancel(text: str) -> bool:
    return norm(text) in {norm(x) for x in CANCEL}


def pending_code(text: str) -> str | None:
    m = PENDING_RE.search(text or "")
    return m.group(0).upper() if m else None


def lot_code(text: str) -> str | None:
    m = LOT_RE.search(text or "")
    return m.group(0).upper() if m else None


def alert_code(text: str) -> str | None:
    m = ALERT_RE.search(text or "")
    return m.group(0).upper() if m else None


def purchase_codes(text: str) -> list[str]:
    return [m.upper() for m in PURCHASE_RE.findall(text or "")]


def to_decimal(raw: str | None) -> Decimal | None:
    if raw is None:
        return None
    s = str(raw).strip().lower().replace("kg", "").replace("%", "").strip()
    if not s:
        return None
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", s):
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d+,\d+", s):
        s = s.replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", s):
        s = s.replace(",", "")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def to_int(raw) -> int | None:
    d = to_decimal(str(raw)) if raw is not None else None
    if d is None or d != d.to_integral_value():
        return None
    return int(d)


NUM = r"(\d{1,3}(?:[.,]\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)"
WEIGHT_RE = re.compile(NUM + r"\s*(kilogramos?|kilos?|kgs?|arrobas?|@|cargas?)\b", re.IGNORECASE)
SACKS_RE = re.compile(r"(\d+)\s*(sacos?|bultos?|costales?)\b", re.IGNORECASE)
SEAL_RE = re.compile(r"\bsello\s*(?:n(?:u|ú)mero|no\.?|#)?\s*([A-Z0-9-]{2,})", re.IGNORECASE)
PLATE_RE = re.compile(r"\bplaca\s*([A-Z]{3}\s?-?\d{3})", re.IGNORECASE)
MOISTURE_RE = re.compile(r"humedad\s*(?:de|del)?\s*" + NUM, re.IGNORECASE)


def weight_kg(text: str) -> Decimal | None:
    """Converts kg, arrobas and cargas using configurable factors. Sacks are never converted to weight."""
    m = WEIGHT_RE.search(text or "")
    if not m:
        return None
    value = to_decimal(m.group(1))
    if value is None:
        return None
    unit = strip_accents(m.group(2).lower())
    s = get_settings()
    if unit.startswith("arroba") or unit == "@":
        value = value * s.arroba_kg
    elif unit.startswith("carga"):
        value = value * s.carga_kg
    return value.quantize(Decimal("0.01"))


def sacks(text: str) -> int | None:
    m = SACKS_RE.search(text or "")
    return int(m.group(1)) if m else None


def seal(text: str) -> str | None:
    m = SEAL_RE.search(text or "")
    return m.group(1).upper() if m else None


def plate(text: str) -> str | None:
    m = PLATE_RE.search(text or "")
    return m.group(1).upper().replace(" ", "").replace("-", "") if m else None


def moisture(text: str) -> Decimal | None:
    m = MOISTURE_RE.search(text or "")
    return to_decimal(m.group(1)) if m else None


STATE_PATTERNS = [
    (r"pergamino\s+humedo|cafe\s+humedo", CoffeeState.WET_PARCHMENT),
    (r"pergamino\s+seco|pergamino|cps\b", CoffeeState.DRY_PARCHMENT),
    (r"\bverde\b|excelso|almendra", CoffeeState.GREEN),
    (r"cereza", CoffeeState.CHERRY),
]


def coffee_state(text: str) -> str | None:
    n = norm(text)
    for pattern, state in STATE_PATTERNS:
        if re.search(pattern, n):
            return state.value
    return None


INTRO_RE = re.compile(r"\b(?:soy|me llamo|mi nombre es)\s+([A-Za-zÁÉÍÓÚÑáéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)?)")
FARM_RE = re.compile(
    r"\bfinca\s+(?:se\s+llama\s+|llamada\s+|es\s+|de\s+nombre\s+)?([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ]*"
    r"(?:\s+(?:[A-ZÁÉÍÓÚÑ][\wáéíóúñ]*|de|del|la|las|los|el))*)")
VEREDA_RE = re.compile(r"\bvereda\s+([A-ZÁÉÍÓÚÑ][\wáéíóúñ]*(?:\s+[A-ZÁÉÍÓÚÑ][\wáéíóúñ]*)*)")
MUNICIPALITY_RE = re.compile(r"\b(?:municipio de|en el municipio de|de)\s+(Pitalito|Neiva|Garzón|Garzon|La Plata|"
                             r"Acevedo|Timaná|Timana|Gigante|Suaza|Isnos|San Agustín|San Agustin)\b")
NAME_STOPWORDS = {"y", "de", "la", "el", "del"}


def introduction(text: str) -> str | None:
    m = INTRO_RE.search(text or "")
    if not m:
        return None
    parts = [p for p in m.group(1).split() if p.lower() not in NAME_STOPWORDS]
    return " ".join(p.capitalize() for p in parts) if parts else None


def farm_name(text: str) -> str | None:
    m = FARM_RE.search(text or "")
    if not m:
        return None
    words = m.group(1).split()
    while words and words[-1].lower() in {"de", "del", "la", "las", "los", "el", "en", "y"}:
        words.pop()
    return " ".join(words) or None


def vereda(text: str) -> str | None:
    m = VEREDA_RE.search(text or "")
    if not m:
        return None
    words = m.group(1).split()
    while words and words[-1].lower() in {"de", "del", "en"}:
        words.pop()
    return " ".join(words) or None


def municipality(text: str) -> str | None:
    m = MUNICIPALITY_RE.search(text or "")
    return m.group(1) if m else None


def parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    raw = raw.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def occurred_at_from(doc_date: date | None, message_ts: datetime) -> tuple[datetime, str]:
    """Activity time: the message time when the document is from the same day, otherwise noon of that day.

    The reception time of the message is never used as the activity time.
    """
    local_msg = message_ts.astimezone(BOGOTA)
    if doc_date is None:
        return message_ts, "message_timestamp"
    if doc_date == local_msg.date():
        return message_ts, "document_date_same_day_message_timestamp"
    return datetime(doc_date.year, doc_date.month, doc_date.day, 12, tzinfo=BOGOTA), "document_date"


def is_today(ts: datetime, reference: datetime) -> bool:
    return ts.astimezone(BOGOTA).date() == reference.astimezone(BOGOTA).date()


def fmt_local(ts: datetime | None) -> str:
    if ts is None:
        return "sin fecha"
    return ts.astimezone(BOGOTA).strftime("%d/%m/%Y %H:%M")
