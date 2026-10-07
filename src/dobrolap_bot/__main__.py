from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from dobrolap_bot.bot.handlers import router as client_router
from dobrolap_bot.bot.owner import router as owner_router
from dobrolap_bot.config.loader import load_catalog
from dobrolap_bot.config.settings import get_settings
from dobrolap_bot.integrations.factory import build_sheets_gateway
from dobrolap_bot.repositories.sqlite import SqliteRepository
from dobrolap_bot.services.booking import BookingService


async def run_bot() -> None:
    settings = get_settings()
    if not settings.bot_token:
        raise SystemExit("BOT_TOKEN is empty. Copy .env.example to .env and set the token.")

    config_dir = settings.config_dir
    if not config_dir.is_absolute():
        config_dir = Path.cwd() / config_dir
    catalog = load_catalog(config_dir)

    db_path = settings.database_path
    if not db_path.is_absolute():
        db_path = Path.cwd() / db_path

    sheets = build_sheets_gateway(settings, config_dir)

    repo = SqliteRepository(db_path)
    await repo.open()
    booking_service = BookingService(repo=repo, catalog=catalog, sheets=sheets)

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher(storage=MemoryStorage())
    dp["catalog"] = catalog
    dp["sheets"] = sheets
    dp["owner_chat_id"] = settings.owner_chat_id
    dp["payment_instructions"] = settings.payment_instructions
    dp["booking_service"] = booking_service
    dp.include_router(owner_router)
    dp.include_router(client_router)

    logging.info("Starting Dobrolap bot (long polling), db=%s", db_path)
    try:
        await dp.start_polling(bot)
    finally:
        await repo.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = get_settings()
    if not settings.bot_token:
        from dobrolap_bot import __version__

        config_dir = settings.config_dir
        if not config_dir.is_absolute():
            config_dir = Path.cwd() / config_dir
        catalog = load_catalog(config_dir)
        print(f"dobrolap-booking-bot {__version__}")
        print(f"accommodations: {len(catalog.accommodations)}")
        print(f"services: {len(catalog.services)}")
        print(f"daily rates: {len(catalog.daily_rates)}")
        print(f"sheets enabled: {settings.google_sheets_enabled}")
        print("BOT_TOKEN is empty — copy .env.example to .env before starting the bot.")
        return

    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
