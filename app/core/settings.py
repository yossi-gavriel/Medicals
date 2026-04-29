from __future__ import annotations

from functools import lru_cache
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)

    app_name: str = "Drug Safety Engine"
    app_env: str = "dev"
    app_debug: bool = False
    app_log_level: str = "INFO"

    # Auth & networking
    api_keys: list[str] = Field(default_factory=list)
    internal_api_keys: list[str] = Field(default_factory=list)
    cors_allow_origins: list[str] = Field(default_factory=lambda: ["*"])
    trusted_proxy_headers: bool = True

    # Storage
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/drug_safety"
    redis_url: str = "redis://localhost:6379/0"
    queue_redis_url: str = "redis://localhost:6379/1"

    # Document storage
    document_storage_backend: str = "local"
    document_storage_local_path: str = "./local_storage/documents"
    document_storage_s3_bucket: str = ""
    document_storage_s3_prefix: str = "documents/"
    document_storage_s3_region: str = "eu-central-1"

    # Drug interaction providers
    enabled_providers: list[str] = Field(
        default_factory=lambda: ["lexicomp", "micromedex", "drugbank"]
    )
    provider_priority: list[str] = Field(
        default_factory=lambda: ["lexicomp", "micromedex", "drugbank", "first_databank", "uptodate", "dynamed"]
    )

    uptodate_api_url: str = ""
    uptodate_api_key: str = ""
    dynamed_api_url: str = ""
    dynamed_api_key: str = ""
    lexicomp_api_url: str = ""
    lexicomp_api_key: str = ""
    micromedex_api_url: str = ""
    micromedex_api_key: str = ""
    drugbank_api_url: str = ""
    drugbank_api_key: str = ""
    first_databank_api_url: str = ""
    first_databank_api_key: str = ""

    rxnorm_api_url: str = "https://rxnav.nlm.nih.gov/REST"
    israel_basket_api_url: str = ""
    israel_basket_api_key: str = ""
    israel_basket_dataset_path: str = "data/israel_drug_basket.json"

    # Medical classifier
    medical_classifier_procedure_definitions_path: str = "data/procedure_definitions"
    medical_classifier_mask_pii_before_llm: bool = True
    medical_classifier_llm_provider: str = "disabled"
    medical_classifier_llm_model: str = ""
    medical_classifier_llm_api_key_env_name: str = "OPENAI_API_KEY"
    medical_classifier_llm_api_key: str = ""
    medical_classifier_llm_timeout_seconds: float = 15.0

    # Async pipeline
    classification_queue_name: str = "medical_classification"
    classification_max_retries: int = 3
    classification_job_timeout_seconds: int = 120
    worker_concurrency: int = 8
    outbox_poll_interval_seconds: float = 5.0
    outbox_batch_size: int = 50
    webhook_signing_secret: str = ""

    # Rate limiting
    rate_limit_enabled: bool = False
    rate_limit_per_minute: int = 600
    rate_limit_window_seconds: int = 60
    rate_limit_anonymous_per_minute: int = 60
    rate_limit_excluded_paths: list[str] = Field(
        default_factory=lambda: [
            "/health",
            "/ready",
            "/metrics",
            "/docs",
            "/redoc",
            "/openapi.json",
        ]
    )

    # Bulk classification
    classification_batch_max_items: int = 500

    # External calls
    request_timeout_seconds: float = 2.0
    external_retry_attempts: int = 3
    external_retry_backoff_seconds: float = 0.2

    # Caches
    interaction_cache_ttl_seconds: int = 60 * 60 * 24
    basket_cache_ttl_seconds: int = 60 * 60 * 6

    # DB pool
    db_pool_size: int = 20
    db_max_overflow: int = 40

    @staticmethod
    def _parse_string_list(value: Any) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []

    @staticmethod
    def _parse_lower_list(value: Any) -> list[str]:
        return [item.lower() for item in Settings._parse_string_list(value)]

    @field_validator("enabled_providers", "provider_priority", mode="before")
    @classmethod
    def _parse_providers(cls, value: Any) -> list[str]:
        return cls._parse_lower_list(value)

    @field_validator(
        "api_keys",
        "internal_api_keys",
        "cors_allow_origins",
        "rate_limit_excluded_paths",
        mode="before",
    )
    @classmethod
    def _parse_string_list_field(cls, value: Any) -> list[str]:
        return cls._parse_string_list(value)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
