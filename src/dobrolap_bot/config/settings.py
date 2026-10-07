from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str = ""
    owner_chat_id: int | None = None

    database_path: Path = Path("data/app.db")
    config_dir: Path = Path("config")
    assets_dir: Path = Path("assets")

    google_sheets_spreadsheet_id: str = ""
    google_service_account_file: Path | None = None
    google_sheets_enabled: bool = False

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
