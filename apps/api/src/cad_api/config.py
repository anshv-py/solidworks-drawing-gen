"""Runtime configuration (environment variables prefixed ``CADAI_``)."""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CADAI_", env_file=".env", extra="ignore")

    environment: str = "development"
    storage_dir: Path = Path("var/storage")
    database_url: str = "sqlite:///var/cadai.db"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    max_upload_mb: int = Field(default=100, ge=1, le=2048)
    analysis_timeout_s: int = Field(default=300, ge=5)
    analysis_memory_mb: int = Field(default=6144, ge=512)
    analysis_python: str = sys.executable
    job_workers: int = Field(default=2, ge=1, le=32)

    # later milestones
    qa_max_retries: int = Field(default=3, ge=0, le=10)
    openai_model: str = "gpt-5.6-sol"
    openai_api_key: SecretStr | None = None
    solidworks_mode: str = Field(default="mock", pattern="^(mock|worker)$")

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
