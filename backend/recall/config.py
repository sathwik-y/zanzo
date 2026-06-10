"""Application settings, loaded from environment / .env file."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root .env (one level above backend/)
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE), env_file_encoding="utf-8", extra="ignore"
    )

    # Database
    database_url: str = "postgresql+psycopg://recall:recall@localhost:5433/recall"

    # Redis queue
    redis_url: str = "redis://localhost:6380/0"
    queue_name: str = "recall:jobs"

    # Media storage (S3-compatible; MinIO locally, real S3 on AWS)
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "recall"
    s3_secret_key: str = "recall-secret"
    s3_bucket: str = "recall-media"
    s3_region: str = "us-east-1"
    s3_public_endpoint_url: str = ""  # browser-reachable endpoint for presigned URLs; defaults to s3_endpoint_url

    # Instagram
    ig_username: str = ""
    ig_password: str = ""
    ig_sessionid: str = ""
    instagrapi_session_path: str = "data/ig.session.json"
    poll_interval_seconds: int = 300
    poll_jitter_seconds: int = 30
    max_items_per_poll: int = 50

    # Gemini
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    # tried in order when the primary model returns 5xx (capacity issues)
    gemini_fallback_models: str = "gemini-2.5-flash-lite,gemini-2.0-flash"
    gemini_embedding_model: str = "gemini-embedding-001"
    embedding_dimensions: int = 1536
    # USD per 1M tokens, for the cost dashboard (gemini-2.5-flash pricing)
    gemini_input_price_per_mtok: float = 0.30
    gemini_output_price_per_mtok: float = 2.50

    # Whisper
    whisper_model_size: str = "small"
    whisper_compute_type: str = "int8"

    # API
    api_key: str = "change-me"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Fixture mode (no external calls; used by tests and credential-less demo)
    recall_fake_instagram: bool = False
    recall_fake_gemini: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
