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
    tandoor_token_valid_date: str | None = Field(
        default=None,
        validation_alias="TANDOOR_TOKEN_VALID_DATE",
    )
    google_llm_api_key: str = Field(
        default="",
        validation_alias="GOOGLE_LLM_API_KEY",
    )
    google_llm_model: str = Field(
        default="gemini-2.5-flash",
        validation_alias="GOOGLE_LLM_MODEL",
    )
    google_llm_timeout_seconds: float = Field(default=30.0)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
