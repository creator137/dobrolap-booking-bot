from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str = ""
    owner_chat_id: int | None = None

    @field_validator("owner_chat_id", mode="before")
    @classmethod
    def _empty_owner_chat(cls, value: Any) -> Any:
        if value == "" or value is None:
            return None
        return value

    database_path: Path = Path("data/app.db")
    config_dir: Path = Path("config")
    assets_dir: Path = Path("assets")

    google_sheets_spreadsheet_id: str = ""
    google_service_account_file: Path | None = None
    google_sheets_enabled: bool = False
    # Keep true against prod calendar until write path is explicitly approved.
    google_sheets_readonly: bool = True

    # Preferred Sheets bridge: Google Apps Script Web App
    gas_webapp_url: str = ""
    gas_webapp_token: str = ""

    payment_instructions: str = ""

    llm_enabled: bool = False
    llm_api_key: str = ""
    llm_model: str = ""

    project_root: Path = Field(default_factory=lambda: Path.cwd())


@lru_cache
def get_settings() -> Settings:
    return Settings()
