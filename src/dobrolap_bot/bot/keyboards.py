from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from dobrolap_bot.bot.presentation import BEHAVIOR_LABELS
from dobrolap_bot.domain.enums import BookingStatus, PetKind


def yes_no_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Да"), KeyboardButton(text="Нет")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def no_kb() -> ReplyKeyboardMarkup:
    """Optional free-text step: skip with «Нет» or type an answer."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Нет")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def contact_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Поделиться номером", request_contact=True)],
            [KeyboardButton(text="Ввести номер вручную")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def passport_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Готово")],
            [KeyboardButton(text="Без фото")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def consent_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Согласен(на)", callback_data="consent:yes")],
            [InlineKeyboardButton(text="Отмена", callback_data="consent:no")],
        ]
    )


def _arrival_row(times: list[str]) -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text=t, callback_data=f"arr:{t}") for t in times]


def arrival_time_kb() -> InlineKeyboardMarkup:
    """Common arrival slots grouped by price rule; free text remains available."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✓ Без доплаты · 19:00–21:00", callback_data="arr:noop")],
            _arrival_row(["19:00", "19:30", "20:00"]),
            _arrival_row(["20:30", "21:00"]),
            [InlineKeyboardButton(text="½ 50% суток · 16:30–19:00", callback_data="arr:noop")],
            _arrival_row(["16:30", "17:00", "17:30"]),
            _arrival_row(["18:00", "18:30"]),
            [InlineKeyboardButton(text="☀ Полные сутки · 08:00–11:00", callback_data="arr:noop")],
            _arrival_row(["08:00", "09:00", "10:00", "11:00"]),
            [InlineKeyboardButton(text="⏱ Рано / поздно · +15%/час", callback_data="arr:noop")],
            _arrival_row(["07:00", "21:30", "22:00"]),
            [InlineKeyboardButton(text="✏️ Другое время", callback_data="arr:text")],
        ]
    )


def pet_kind_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Собака"), KeyboardButton(text="Кошка")],
            [KeyboardButton(text="Кролик"), KeyboardButton(text="Крыса")],
            [KeyboardButton(text="Хомяк"), KeyboardButton(text="Птица")],
            [KeyboardButton(text="Морская свинка"), KeyboardButton(text="Другое")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def add_pet_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Добавить ещё питомца")],
            [KeyboardButton(text="Перейти к подбору")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def feeding_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Корм владельца")],
            [KeyboardButton(text="Рацион гостиницы")],
            [KeyboardButton(text="Натуральное — готовое, минимум нарезки (150 ₽/сутки)")],
            [KeyboardButton(text="Натуральное — приготовить кашу (250 ₽/сутки)")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def feeding_source_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Продукты привезу сам(а)")],
            [KeyboardButton(text="Купите продукты, пожалуйста, с чеками")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def behavior_options(kind: PetKind) -> list[str]:
    if kind == PetKind.CAT:
        return [
            "zoo_aggression",
            "high_stress",
            "distrust_humans",
            "marks_territory",
            "chews_furniture",
            "mobility_limited",
            "needs_treatment",
            "disability",
        ]
    else:
        return [
            "aggression",
            "high_stress",
            "loud_barking",
            "elderly",
            "mobility_limited",
            "incontinence",
            "needs_treatment",
            "disability",
        ]


def behavior_kb(kind: PetKind, selected: set[str] | None = None) -> InlineKeyboardMarkup:
    selected = selected or set()
    keys = behavior_options(kind)
    rows = [
        [
            InlineKeyboardButton(
                text=("✅ " if key in selected else "") + BEHAVIOR_LABELS[key].capitalize(),
                callback_data=f"beh:{key}",
            )
        ]
        for key in keys
    ]
    rows.extend(
        [
            [InlineKeyboardButton(text="Особенностей нет", callback_data="beh:none")],
            [InlineKeyboardButton(text="Готово — продолжить", callback_data="beh:done")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def extraction_review_kb(field: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Верно", callback_data=f"review:{field}:yes")],
            [InlineKeyboardButton(text="✏️ Исправить", callback_data=f"review:{field}:edit")],
        ]
    )


def unit_choice_kb(unit_ids: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=title[:64], callback_data=f"unit:{uid}")]
        for uid, title in unit_ids
    ]
    rows.append(
        [InlineKeyboardButton(text="Нет подходящего — ручной подбор", callback_data="unit:manual")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def services_kb(items: list[tuple[str, str, bool]]) -> InlineKeyboardMarkup:
    rows = []
    for sid, title, selected in items:
        mark = "✅ " if selected else ""
        rows.append(
            [InlineKeyboardButton(text=f"{mark}{title}"[:64], callback_data=f"svc:{sid}")]
        )
    rows.append([InlineKeyboardButton(text="Готово → далее", callback_data="svc:done")])
    rows.append([InlineKeyboardButton(text="Без доп. услуг", callback_data="svc:none")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def submit_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отправить владельцу", callback_data="submit:yes")],
            [InlineKeyboardButton(text="Отменить заявку", callback_data="submit:no")],
        ]
    )


OWNER_MENU_HOME = "📊 Сводка"
OWNER_MENU_PENDING = "⏳ Ждут решения"
OWNER_MENU_UNPAID = "💳 Ждут оплату"
OWNER_MENU_CONFIRMED = "✅ Подтверждённые"
OWNER_MENU_CLIENTS = "👥 Клиенты"


def owner_menu_kb() -> ReplyKeyboardMarkup:
    """Persistent reply keyboard for the owner chat."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=OWNER_MENU_HOME), KeyboardButton(text=OWNER_MENU_PENDING)],
            [KeyboardButton(text=OWNER_MENU_UNPAID), KeyboardButton(text=OWNER_MENU_CONFIRMED)],
            [KeyboardButton(text=OWNER_MENU_CLIENTS)],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def owner_admin_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Сводка", callback_data="adm:home")],
            [
                InlineKeyboardButton(text="⏳ Ждут решения", callback_data="adm:pending"),
                InlineKeyboardButton(text="💳 Ждут оплату", callback_data="adm:unpaid"),
            ],
            [
                InlineKeyboardButton(text="✅ Подтверждённые", callback_data="adm:confirmed"),
                InlineKeyboardButton(text="👥 Клиенты", callback_data="adm:clients"),
            ],
        ]
    )


def owner_admin_bookings_kb(items: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """items: (booking_id, button_title)."""
    rows = [
        [InlineKeyboardButton(text=title[:64], callback_data=f"adm:open:{booking_id}")]
        for booking_id, title in items
    ]
    rows.append([InlineKeyboardButton(text="« В меню", callback_data="adm:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def owner_actions_kb(booking_id: str, *, has_unit: bool = True) -> InlineKeyboardMarkup:
    unit_btn = (
        "🔁 Другой вариант"
        if has_unit
        else "🏠 Выбрать помещение"
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"own:approve:{booking_id}")],
            [InlineKeyboardButton(text="❓ Задать вопрос", callback_data=f"own:ask:{booking_id}")],
            [InlineKeyboardButton(text=unit_btn, callback_data=f"own:alt:{booking_id}")],
            [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"own:reject:{booking_id}")],
        ]
    )


def owner_unit_choice_kb(
    booking_id: str, units: list[tuple[str, str]]
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=title[:64],
                callback_data=f"ownunit:{booking_id}:{unit_id}",
            )
        ]
        for unit_id, title in units
    ]
    rows.append(
        [InlineKeyboardButton(text="Закрыть список", callback_data=f"ownunit:{booking_id}:close")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def owner_paid_kb(booking_id: str) -> InlineKeyboardMarkup:
    """Payment actions for a reserve awaiting the deposit (receipt optional)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💰 Оплата получена",
                    callback_data=f"own:paid:{booking_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🚫 Отменить бронь",
                    callback_data=f"own:cancel:{booking_id}",
                )
            ],
        ]
    )


def owner_cancel_kb(booking_id: str) -> InlineKeyboardMarkup:
    """For cancel requests after approve / confirmed — not «Отклонить»."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚫 Отменить бронь",
                    callback_data=f"own:cancel:{booking_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="💰 Оплата получена",
                    callback_data=f"own:paid:{booking_id}",
                )
            ],
        ]
    )


def owner_booking_kb(
    booking_id: str, status: BookingStatus | str, *, has_unit: bool = True
) -> InlineKeyboardMarkup | None:
    """Owner card actions matching the booking's current status.

    «Подтвердить» (own:approve) is valid only for WAITING_OWNER; a reserve that
    already waits for the deposit needs «Оплата получена» / «Отменить бронь».
    """
    status = BookingStatus(status)
    if status == BookingStatus.WAITING_OWNER:
        return owner_actions_kb(booking_id, has_unit=has_unit)
    if status in (BookingStatus.OWNER_APPROVED, BookingStatus.WAITING_PAYMENT):
        return owner_paid_kb(booking_id)
    if status == BookingStatus.CONFIRMED:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🚫 Отменить бронь",
                        callback_data=f"own:cancel:{booking_id}",
                    )
                ]
            ]
        )
    return None


def owner_refund_kb(booking_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💸 Отметить возврат залога",
                    callback_data=f"own:refund:{booking_id}",
                )
            ]
        ]
    )


def client_reply_kb(booking_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Ответить владельцу", callback_data=f"cli:reply:{booking_id}")]
        ]
    )
