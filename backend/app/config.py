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

    # Abuse controls
    login_rate_limit: int = 10
    login_rate_window_seconds: int = 300
    register_rate_limit: int = 5
    register_rate_window_seconds: int = 3600
    lockout_threshold: int = 5
    lockout_minutes: int = 15

    @property
    def allowed_origins(self) -> list[str]:
        """Origins permitted to send state-changing requests.

        Vite dev, plus both loopback spellings of the built app. Keep this
        list explicit: the Origin check is the login-CSRF guard.
        """
        return list(
            dict.fromkeys(
                [
                    self.frontend_origin,
                    "http://localhost:5173",
                    "http://127.0.0.1:5173",
                    "http://localhost:8000",
                    "http://127.0.0.1:8000",
                ]
            )
        )

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