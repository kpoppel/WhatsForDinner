from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "WhatsForDinner"
    api_v1_prefix: str = "/api/v1"
    tandoor_base_url: str = "http://localhost:8080"
    tandoor_api_token: str = ""
    tandoor_auth_scheme: str = "Bearer"
    tandoor_timeout_seconds: float = 15.0
    tandoor_write_enabled: bool = True
    stage2_data_dir: str = Field(
        default="data",
        validation_alias="DATA_DIR",
    )
    stage2_sync_event_max_count: int = Field(default=2000, ge=1)
    stage2_sync_event_max_age_days: int = Field(default=30, ge=1)
    tandoor_token_valid_date: str | None = Field(
        default=None,
        validation_alias="TANDOOR_TOKEN_VALID_DATE",
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
