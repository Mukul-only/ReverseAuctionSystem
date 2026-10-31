from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from ..models import Role

# A short blocklist catches the worst offenders. Length is the primary control.
_COMMON_PASSWORDS = {
    "password",
    "password123",
    "password1234",
    "123456789012",
    "qwertyuiop12",
    "letmein12345",
    "adminadmin12",
    "welcome12345",
    "changeme1234",
    "iloveyou1234",
}


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    # Self-service registration can never mint an admin.
    role: Literal["buyer", "seller"]

    @field_validator("password")
    @classmethod
    def _password_policy(cls, value: str) -> str:
        if value.lower() in _COMMON_PASSWORDS:
            raise ValueError("Choose a less common password.")
        if len(set(value)) < 5:
            raise ValueError("Password is too repetitive.")
        return value


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    role: Role
    created_at: datetime


class AuthResponse(BaseModel):
    user: UserOut
    csrf_token: str