from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    model: str = Field(default="claude-sonnet-4-6", alias="AGENT_MODEL")
    max_iterations: int = Field(default=16, alias="AGENT_MAX_ITERATIONS")

    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    chroma_dir: str = Field(default="./data/chroma", alias="CHROMA_DIR")
    workspace_root: str = Field(default="./data/workspaces", alias="WORKSPACE_ROOT")

    cors_origins: str = Field(default="*", alias="CORS_ORIGINS")

    smtp_host: str = Field(default="", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_username: str = Field(default="", alias="SMTP_USERNAME")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
    smtp_from: str = Field(default="", alias="SMTP_FROM")

    auto_confirm: bool = Field(default=False, alias="AGENT_AUTO_CONFIRM")

    @property
    def smtp_enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_username)

    def ensure_dirs(self) -> None:
        Path(self.chroma_dir).mkdir(parents=True, exist_ok=True)
        Path(self.workspace_root).mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()
