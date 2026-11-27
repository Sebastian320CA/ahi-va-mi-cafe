import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("TEST_DATABASE_URL", "postgresql+psycopg://cafe:cafe@localhost:5432/cafe_test")
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
os.environ["APP_ENV"] = "test"
os.environ["QUEUE_MODE"] = "sync"
os.environ["REDIS_URL"] = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15")
os.environ["WHATSAPP_PROVIDER"] = "simulated"
os.environ["LLM_PROVIDER"] = "simulated"
os.environ["SPEECH_PROVIDER"] = "simulated"
os.environ["DOCUMENT_PROVIDER"] = "simulated"
os.environ["STORAGE_PROVIDER"] = "local"
os.environ["META_APP_SECRET"] = "test-app-secret"
os.environ["WHATSAPP_VERIFY_TOKEN"] = "test-verify"
os.environ["SECRET_KEY"] = "test-secret-key-with-enough-length-1234"
os.environ.setdefault("LOCAL_STORAGE_PATH", "/tmp/cafe-test-storage")
os.environ["GEOSPATIAL_DATA_PATH"] = str(Path(__file__).resolve().parents[2] / "data" / "geospatial")

import pytest  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.database import SessionLocal, reset_engine  # noqa: E402
from app.modules.identity.models import User  # noqa: E402
from app.modules.identity.service import build_actor  # noqa: E402
from app.seed import seed  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session", autouse=True)
def _migrate():
    get_settings.cache_clear()
    reset_engine()
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, check=True,
                   env={**os.environ})
    yield


@pytest.fixture()
def db():
    session = SessionLocal()
    seed(session, reset=True)
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def actor_by(db, *, email=None, phone=None):
    stmt = select(User)
    stmt = stmt.where(User.email == email) if email else stmt.where(User.whatsapp_phone == phone)
    user = db.scalars(stmt).first()
    assert user is not None
    return build_actor(db, user)
