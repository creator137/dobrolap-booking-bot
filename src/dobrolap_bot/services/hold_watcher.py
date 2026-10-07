"""Background hold expiry and payment reminders."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta, timezone
from datetime import datetime

from aiogram import Bot

from dobrolap_bot.domain.enums import BookingStatus
from dobrolap_bot.services.booking import BookingService

logger = logging.getLogger(__name__)


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def run_hold_watcher(
    *,
    bot: Bot,
    booking_service: BookingService,
    owner_chat_id: int | None,
    interval_sec: float = 60.0,
    reminder_hours_before: float = 4.0,
) -> None:
    """Poll WAITING_PAYMENT bookings: remind once, then expire on timeout."""
    while True:
        try:
            await _tick(
                bot=bot,
                booking_service=booking_service,
                owner_chat_id=owner_chat_id,
                reminder_hours_before=reminder_hours_before,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("hold_watcher tick failed")
        await asyncio.sleep(max(interval_sec, 5.0))


async def _tick(
    *,
    bot: Bot,
    booking_service: BookingService,
    owner_chat_id: int | None,
    reminder_hours_before: float,
) -> None:
    now = datetime.now(timezone.utc)
    rows = await booking_service.repo.list_waiting_payment_holds()
    for booking in rows:
        if booking.status != BookingStatus.WAITING_PAYMENT:
            continue
        expires = booking.hold_expires_at
        if expires is None:
            continue
        expires = _aware(expires)

        # Reminder once before expiry
        if reminder_hours_before > 0 and booking.last_reminder_at is None:
            remind_at = expires - timedelta(hours=reminder_hours_before)
            if now >= remind_at and now < expires:
                marked = await booking_service.mark_hold_reminder_sent(booking.id)
                if marked is None:
                    continue
                text = (
                    f"Напоминание: по заявке {booking.id} оплата ещё не подтверждена.\n"
                    f"Резерв действует до {expires.isoformat()}."
                )
                client_id = booking.customer_telegram_id
                if client_id:
                    try:
                        await bot.send_message(client_id, text)
                    except Exception:
                        logger.exception("reminder to client failed booking=%s", booking.id)
                if owner_chat_id:
                    try:
                        await bot.send_message(
                            owner_chat_id,
                            f"⏰ {text}",
                        )
                    except Exception:
                        logger.exception("reminder to owner failed booking=%s", booking.id)

        if now < expires:
            continue

        try:
            expired = await booking_service.expire_hold(booking.id)
        except Exception as exc:
            logger.error(
                "expire_hold failed booking=%s err=%s — will retry; calendar not marked expired",
                booking.id,
                exc,
            )
            if owner_chat_id:
                try:
                    await bot.send_message(
                        owner_chat_id,
                        f"⚠️ Не удалось освободить календарь по просроченной заявке {booking.id}: {exc}",
                    )
                except Exception:
                    pass
            continue

        if expired is None:
            continue

        client_id = expired.customer_telegram_id
        if client_id:
            try:
                await bot.send_message(
                    client_id,
                    f"Срок оплаты по заявке {expired.id} истёк, резерв снят.\n"
                    "Можно оформить новую заявку: /start",
                )
            except Exception:
                logger.exception("expire notice to client failed booking=%s", expired.id)
        if owner_chat_id:
            try:
                await bot.send_message(
                    owner_chat_id,
                    f"⌛ Заявка {expired.id} истекла (EXPIRED), место освобождено.",
                )
            except Exception:
                logger.exception("expire notice to owner failed booking=%s", expired.id)
