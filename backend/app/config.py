from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    rp_id: str = "localhost"
    rp_name: str = "PassKey"
    expected_origin: str = "http://localhost:5173"

    db_url: str = "sqlite+aiosqlite:///./passkey.db"

    vault_key: str  # base64-encoded 32 bytes
    session_secret: str
    session_ttl_seconds: int = 86400

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
