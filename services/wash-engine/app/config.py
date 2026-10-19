from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WASH_ENGINE_")

    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "rtu_wash"
    postgres_user: str = "rtu_wash"
    postgres_password: str = "rtu_wash"
    jwt_secret: str = "change-me"
    jwt_issuer: str = "rtu-wash-edge"
    jwt_access_minutes: int = 720
    default_owner_login: str = "owner"
    default_owner_password: str
    default_admin_login: str = "admin"
    default_admin_password: str
    device_type: Literal["wash","dry_fog"] = "wash"
    simulation_enabled: bool = False
    io_helper_url: str = "http://io-helper:8080"
    click_gateway_url: str = "https://gateway.example.com"
    click_site_code: str = ""
    click_site_token: str = ""
    click_post_no: int = 1
    click_enabled: bool = False
    click_min_amount_sum: int = 1000
    click_max_amount_sum: int = 10_000_000
    license_enabled: bool = False
    license_gateway_url: str = ""
    license_site_code: str = ""
    license_site_token: str = ""
    license_post_no: int = 1
    license_sync_interval_seconds: int = 43_200
    license_grace_seconds: int = 604_800
    kiosk_assets_dir: str = "/var/lib/rtu-wash/kiosk-assets"
    commissioning_signing_public_key: str = ""

    @property
    def database_url(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
