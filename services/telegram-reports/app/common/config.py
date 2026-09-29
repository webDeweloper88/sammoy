from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_ENV_FILE = os.getenv("RTU_WASH_REPORTS_ENV") or os.getenv("SAMMOY_REPORTS_ENV")
if not DEFAULT_ENV_FILE:
    production_env = Path("/opt/rtu-wash/secrets/reports.env")
    DEFAULT_ENV_FILE = str(production_env if production_env.exists() else Path(".env"))


class PostConfig(BaseModel):
    id: str
    name: str
    host: str
    port: int = 8091
    api_key_env: str
    enabled: bool = True

    @property
    def api_key(self) -> str:
        value = os.getenv(self.api_key_env, "")
        if not value:
            raise ValueError(f"Missing API key environment variable: {self.api_key_env}")
        return value


class SiteConfig(BaseModel):
    id: str
    name: str
    timezone: str = "Asia/Tashkent"


class HubConfig(BaseModel):
    site: SiteConfig
    posts: list[PostConfig] = Field(default_factory=list)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=DEFAULT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    site_id: str = "RTU-WASH-DEMO"
    site_name: str = "RTU WASH Demo"
    post_id: str = "POST-01"
    post_name: str = "Post 1"
    timezone: str = "Asia/Tashkent"
    repository_mode: str = "demo"
    postgres_dsn: str = ""
    local_report_api_key: str = "change-me"
    posts_config: Path = Path("config/posts.yaml")
    report_request_timeout_seconds: float = 3.0
    report_cache_seconds: int = 45
    hub_database_path: Path = Path("data/hub.sqlite3")
    telegram_bot_token: str = ""
    telegram_bot_username: str = ""
    unauthorized_behavior: str = "silent"
    pairing_token_ttl_minutes: int = 10
    automatic_daily_report_enabled: bool = True
    automatic_daily_report_time: str = "21:00"
    automatic_report_poll_seconds: int = 30
    health_alerts_enabled: bool = True
    health_poll_seconds: int = 60
    health_failure_threshold: int = 3
    wash_engine_url: str = "http://127.0.0.1:8080"


def load_hub_config(path: Path) -> HubConfig:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return HubConfig.model_validate(payload)


settings = Settings()
