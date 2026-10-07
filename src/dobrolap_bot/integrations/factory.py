from __future__ import annotations

import logging
from pathlib import Path

from dobrolap_bot.config.settings import Settings
from dobrolap_bot.integrations.google_sheets import (
    DisabledSheetsGateway,
    SheetsGateway,
    UnavailableSheetsGateway,
)

logger = logging.getLogger(__name__)


def build_sheets_gateway(settings: Settings, config_dir: Path) -> SheetsGateway:
    """Build Sheets gateway. When enabled but misconfigured → fail-closed."""
    _ = config_dir

    if not settings.google_sheets_enabled:
        logger.info("GOOGLE_SHEETS_ENABLED=false — DisabledSheetsGateway")
        return DisabledSheetsGateway()

    # 1) Apps Script Web App (preferred for grid calendar)
    if settings.gas_webapp_url and settings.gas_webapp_token:
        try:
            from dobrolap_bot.integrations.apps_script_sheets import AppsScriptSheetsGateway

            gw = AppsScriptSheetsGateway(
                webapp_url=settings.gas_webapp_url,
                token=settings.gas_webapp_token,
            )
            logger.info("Using AppsScriptSheetsGateway")
            return gw
        except Exception as exc:
            logger.exception("Apps Script gateway failed to init")
            return UnavailableSheetsGateway(f"apps_script_init_failed: {exc}")

    # 2) Service account grid reader
    creds = settings.google_service_account_file
    if creds is not None and Path(creds).exists() and settings.google_sheets_spreadsheet_id:
        try:
            from dobrolap_bot.integrations.google_sheets_live import GoogleSheetsGateway

            logger.info(
                "Using GoogleSheetsGateway (service account, grid, readonly=%s)",
                settings.google_sheets_readonly,
            )
            return GoogleSheetsGateway(
                spreadsheet_id=settings.google_sheets_spreadsheet_id,
                credentials_file=Path(creds),
                mapping_path=config_dir / "sheets_mapping.yaml",
                readonly=settings.google_sheets_readonly,
            )
        except Exception as exc:
            logger.exception("Service-account Sheets gateway failed")
            return UnavailableSheetsGateway(f"service_account_init_failed: {exc}")

    logger.error(
        "GOOGLE_SHEETS_ENABLED=true but GAS_WEBAPP_* / service account not configured — fail-closed"
    )
    return UnavailableSheetsGateway("sheets_not_configured")
