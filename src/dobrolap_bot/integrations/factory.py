from __future__ import annotations

import logging
from pathlib import Path

from dobrolap_bot.config.settings import Settings
from dobrolap_bot.integrations.google_sheets import (
    DisabledSheetsGateway,
    InMemorySheetsGateway,
    SheetsGateway,
)

logger = logging.getLogger(__name__)


def build_sheets_gateway(settings: Settings, config_dir: Path) -> SheetsGateway:
    """Prefer Apps Script Web App; fall back to service-account / stubs."""
    _ = config_dir

    if not settings.google_sheets_enabled:
        return DisabledSheetsGateway()

    # 1) Preferred: Google Apps Script cloud web app
    if settings.gas_webapp_url and settings.gas_webapp_token:
        try:
            from dobrolap_bot.integrations.apps_script_sheets import AppsScriptSheetsGateway

            gw = AppsScriptSheetsGateway(
                webapp_url=settings.gas_webapp_url,
                token=settings.gas_webapp_token,
            )
            logger.info("Using AppsScriptSheetsGateway")
            return gw
        except Exception:
            logger.exception("Apps Script gateway failed to init")

    # 2) Legacy optional: service account (needs google-auth extras)
    creds = settings.google_service_account_file
    if creds is not None and Path(creds).exists() and settings.google_sheets_spreadsheet_id:
        try:
            from dobrolap_bot.integrations.google_sheets_live import GoogleSheetsGateway

            logger.info("Using GoogleSheetsGateway (service account)")
            return GoogleSheetsGateway(
                spreadsheet_id=settings.google_sheets_spreadsheet_id,
                credentials_file=Path(creds),
                mapping_path=config_dir / "sheets_mapping.yaml",
            )
        except Exception:
            logger.exception("Service-account Sheets gateway failed")

    logger.warning(
        "GOOGLE_SHEETS_ENABLED=true but no GAS_WEBAPP_URL/TOKEN (and no service account) — "
        "using InMemorySheetsGateway"
    )
    return InMemorySheetsGateway()
