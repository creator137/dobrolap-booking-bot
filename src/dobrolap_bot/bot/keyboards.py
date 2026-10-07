from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup


def yes_no_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Да"), KeyboardButton(text="Нет")]],
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


def pet_kind_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Собака"), KeyboardButton(text="Кошка")],
            [KeyboardButton(text="Другое")],
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
            [KeyboardButton(text="Натуральное с приготовлением")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
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
    """items: (service_id, title, selected)."""
    rows = []
    for sid, title, selected in items:
        mark = "✅ " if selected else ""
        rows.append(
            [InlineKeyboardButton(text=f"{mark}{title}"[:64], callback_data=f"svc:{sid}")]
        )
    rows.append([InlineKeyboardButton(text="Готово → сводка", callback_data="svc:done")])
    rows.append([InlineKeyboardButton(text="Без доп. услуг", callback_data="svc:none")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def submit_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отправить владельцу", callback_data="submit:yes")],
            [InlineKeyboardButton(text="Отменить заявку", callback_data="submit:no")],
        ]
    )


def owner_actions_kb(booking_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"own:approve:{booking_id}")],
            [InlineKeyboardButton(text="❓ Задать вопрос", callback_data=f"own:ask:{booking_id}")],
            [
                InlineKeyboardButton(
                    text="🔁 Другой вариант",
                    callback_data=f"own:alt:{booking_id}",
                )
            ],
            [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"own:reject:{booking_id}")],
        ]
    )


def owner_paid_kb(booking_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💰 Оплата получена",
                    callback_data=f"own:paid:{booking_id}",
                )
            ],
            [InlineKeyboardButton(text="❌ Отменить", callback_data=f"own:reject:{booking_id}")],
        ]
    )


def client_reply_kb(booking_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Ответить владельцу", callback_data=f"cli:reply:{booking_id}")]
        ]
    )
