from typing import Any

from pydantic import BaseModel, Field


class UsernameRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)


class CeremonyResponse(BaseModel):
    """Raw WebAuthn options JSON (base64url-encoded fields), passed straight to the browser."""

    options: dict[str, Any]


class RegisterCompleteRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    attestation: dict[str, Any]


class LoginCompleteRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    assertion: dict[str, Any]


class WhoAmIResponse(BaseModel):
    username: str


class VaultEntryCreate(BaseModel):
    label: str = Field(min_length=1, max_length=255)
    username: str = Field(min_length=0, max_length=255)
    password: str = Field(min_length=1)


class VaultEntryOut(BaseModel):
    id: str
    label: str
    username: str
    password: str
    created_at: str
