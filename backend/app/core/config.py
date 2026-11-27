"""Application settings loaded from environment variables."""

from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Ahí va mi café"
    app_env: Literal["development", "test", "production"] = "development"
    secret_key: str = Field(default="dev-only-change-me-please-32-bytes-min")
    database_url: str = "postgresql+psycopg://cafe:cafe@localhost:5432/cafe"
    redis_url: str = "redis://localhost:6379/0"
    frontend_url: str = "http://localhost:3000"
    api_base_url: str = "http://localhost:8000"
    queue_mode: Literal["rq", "sync"] = "rq"
    access_token_minutes: int = 480

    whatsapp_provider: Literal["meta", "simulated"] = "simulated"
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_business_account_id: str = ""
    whatsapp_verify_token: str = "dev-verify-token"
    meta_app_secret: str = "dev-app-secret"
    meta_graph_api_version: str = "v27.0"
    whatsapp_service_window_hours: int = 24
    whatsapp_notification_template: str = ""

    llm_provider: Literal["azure", "simulated"] = "simulated"
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = ""
    azure_openai_api_version: str = "2024-10-21"

    speech_provider: Literal["azure", "simulated"] = "simulated"
    azure_speech_key: str = ""
    azure_speech_region: str = ""
    speech_language: str = "es-CO"

    document_provider: Literal["azure", "simulated"] = "simulated"
    azure_document_intelligence_endpoint: str = ""
    azure_document_intelligence_key: str = ""
    azure_document_intelligence_api_version: str = "2024-11-30"

    storage_provider: Literal["local", "azure"] = "local"
    local_storage_path: str = "./storage"
    azure_storage_connection_string: str = ""
    azure_storage_container: str = "evidencias"
    max_upload_bytes: int = 10 * 1024 * 1024
    allowed_media_types: str = "image/jpeg,image/png,audio/ogg,audio/mpeg,audio/wav,audio/mp4,audio/aac"

    geo_provider: Literal["local"] = "local"
    azure_maps_key: str = ""
    geospatial_data_path: str = "../data/geospatial"
    climate_provider: Literal["disabled"] = "disabled"
    climate_api_key: str = ""

    log_level: str = "INFO"

    # Business rules (demo assumptions, not official standards).
    default_producer_org_code: str = "COOP-HUILA"
    alert_weight_pct_threshold: Decimal = Decimal("0.50")
    alert_sack_tolerance: int = 0
    arroba_kg: Decimal = Decimal("12.5")
    carga_kg: Decimal = Decimal("125")
    consent_version: str = "2026-1"
    due_diligence_rule_version: str = "demo-2026-11"
    eudr_cutoff_date: str = "2020-12-31"
    polygon_required_above_ha: Decimal = Decimal("4")
    max_conversation_turns: int = 8
    rate_limit_per_minute: int = 120

    # Configurable unit rates for cost estimation. Empty means unknown; no prices are assumed.
    cost_rate_llm_per_1k_tokens: Decimal | None = None
    cost_rate_speech_per_minute: Decimal | None = None
    cost_rate_document_per_page: Decimal | None = None
    cost_rate_whatsapp_per_message: Decimal | None = None

    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        # Managed Postgres providers (Render, Heroku, ...) hand out postgres:// or postgresql:// URLs.
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value[len(prefix):]
        return value

    @property
    def is_dev(self) -> bool:
        return self.app_env in ("development", "test")

    @property
    def allowed_media_set(self) -> set[str]:
        return {m.strip() for m in self.allowed_media_types.split(",") if m.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
