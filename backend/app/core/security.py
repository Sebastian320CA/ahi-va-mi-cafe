"""Password hashing, access tokens, webhook signatures and basic rate limiting."""

import hashlib
import hmac
import time
import uuid
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.core.config import get_settings

JWT_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user_id: uuid.UUID) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_minutes)).timestamp()),
        "typ": "access",
    }
    return jwt.encode(payload, settings.secret_key, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> uuid.UUID | None:
    try:
        payload = jwt.decode(token, get_settings().secret_key, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != "access":
        return None
    try:
        return uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        return None


def meta_signature(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def verify_meta_signature(body: bytes, header_value: str | None, secret: str) -> bool:
    """Validates X-Hub-Signature-256 as sent by Meta webhooks."""
    if not header_value or not secret:
        return False
    return hmac.compare_digest(meta_signature(body, secret), header_value.strip())


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class RateLimiter:
    """Sliding window limiter. Uses Redis when available, otherwise process memory."""

    def __init__(self) -> None:
        self._memory: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: int, window_seconds: int = 60) -> bool:
        try:
            from app.core.queue import get_redis

            redis = get_redis()
            bucket = f"rl:{key}:{int(time.time() // window_seconds)}"
            count = redis.incr(bucket)
            if count == 1:
                redis.expire(bucket, window_seconds)
            return int(count) <= limit
        except Exception:
            now = time.monotonic()
            q = self._memory[key]
            while q and now - q[0] > window_seconds:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True


rate_limiter = RateLimiter()
