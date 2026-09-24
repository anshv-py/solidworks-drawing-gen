"""Runtime configuration (environment variables prefixed ``CADAI_``)."""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
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
    # Optional planning LLM. Drawing generation is fully deterministic and does NOT use it
    # (llm_backend="none"). If ever enabled it runs in a dedicated GPU worker, never in the API.
    llm_backend: str = Field(default="none", pattern="^(none|transformers|openai_compatible)$")
    llm_model: str = "deepseek-ai/DeepSeek-V4-Pro"
    llm_revision: str | None = None  # pin a Hub commit sha for reproducible plans
    llm_endpoint_url: str | None = None  # openai_compatible: vLLM / SGLang / `transformers serve`
    llm_trust_remote_code: bool = False  # executes code from the model repo: only with a pinned revision
    hf_token: SecretStr | None = None
    solidworks_mode: str = Field(default="mock", pattern="^(mock|worker)$")

    # hosted single-service deployments (e.g. Render): the API also serves the built UI, and an
    # optional shared password puts HTTP Basic auth in front of everything except /api/health
    frontend_dir: Path | None = None
    access_user: str = "cadai"
    access_password: SecretStr | None = None

    @field_validator("database_url")
    @classmethod
    def _psycopg_driver(cls, v: str) -> str:
        """Hosted Postgres hands out ``postgres://`` / ``postgresql://`` URLs; use psycopg 3."""
        for scheme in ("postgres://", "postgresql://"):
            if v.startswith(scheme):
                return "postgresql+psycopg://" + v.removeprefix(scheme)
        return v

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
