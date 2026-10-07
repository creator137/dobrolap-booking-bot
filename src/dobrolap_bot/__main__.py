from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher

from dobrolap_bot.bot.handlers import router as client_router
from dobrolap_bot.bot.owner import router as owner_router
from dobrolap_bot.config.loader import load_catalog
from dobrolap_bot.config.settings import get_settings
from dobrolap_bot.integrations.factory import build_sheets_gateway
from dobrolap_bot.repositories.fsm_sqlite import SqliteFsmStorage
from dobrolap_bot.repositories.sqlite import SqliteRepository
from dobrolap_bot.services.booking import BookingService
from dobrolap_bot.services.hold_watcher import run_hold_watcher


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
    booking_service = BookingService(
        repo=repo,
        catalog=catalog,
        sheets=sheets,
        hold_hours=settings.hold_hours,
    )

    fsm_path = db_path.with_name(db_path.stem + "_fsm.db")
    fsm_storage = SqliteFsmStorage(fsm_path)
    await fsm_storage.open()

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher(storage=fsm_storage)
    assets_dir = settings.assets_dir
    if not assets_dir.is_absolute():
        assets_dir = Path.cwd() / assets_dir

    dp["catalog"] = catalog
    dp["sheets"] = sheets
    dp["owner_chat_id"] = settings.owner_chat_id
    dp["payment_instructions"] = settings.payment_instructions
    dp["booking_service"] = booking_service
    dp["assets_dir"] = assets_dir
    dp.include_router(owner_router)
    dp.include_router(client_router)

    hold_task = asyncio.create_task(
        run_hold_watcher(
            bot=bot,
            booking_service=booking_service,
            owner_chat_id=settings.owner_chat_id,
            interval_sec=settings.hold_watch_interval_sec,
            reminder_hours_before=settings.hold_reminder_hours_before,
        ),
        name="hold_watcher",
    )

    logging.info(
        "Starting Dobrolap bot (long polling), db=%s fsm=%s hold_hours=%s",
        db_path,
        fsm_path,
        settings.hold_hours,
    )
    try:
        await dp.start_polling(bot)
    finally:
        hold_task.cancel()
        try:
            await hold_task
        except asyncio.CancelledError:
            pass
        await fsm_storage.close()
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
