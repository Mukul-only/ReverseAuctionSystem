"""Application configuration loaded from environment variables.

The app deliberately refuses to start when ``SECRET_KEY`` is missing, short,
or a well-known placeholder. This turns a common deployment mistake into a
hard boot failure instead of silently weak cryptography.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Values that look like secrets but are not. Kept lowercase for comparison.
_WEAK_SECRETS = {
    "changeme",
    "change-me",
    "secret",
    "secret-key",
    "dev",
    "development",
    "test",
    "testing",
    "password",
    "supersecret",
    "your-secret-key",
    "replace-me",
    "replaceme",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Works when the process is started from either the repo root or backend/.
        env_file=(".env", "backend/.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Reverse Auction System"
    env: str = "development"
    debug: bool = False

    # Required: no safe default exists.
    secret_key: str = ""

    database_url: str = "sqlite:///./data/app.db"
    frontend_origin: str = "http://localhost:5173"

    # Session policy (used from Milestone 3 onward).
    session_cookie_name: str = "__Host-ra_session"
    session_idle_minutes: int = 30
    session_absolute_hours: int = 12
    cookie_secure: bool = True

    @field_validator("secret_key")
    @classmethod
    def _reject_weak_secret(cls, value: str) -> str:
        if not value or len(value) < 32 or value.strip().lower() in _WEAK_SECRETS:
            raise ValueError(
                "SECRET_KEY must be a random value of at least 32 characters. "
                'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()