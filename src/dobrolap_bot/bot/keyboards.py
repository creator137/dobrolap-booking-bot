from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from dobrolap_bot.bot.presentation import BEHAVIOR_LABELS
from dobrolap_bot.domain.enums import PetKind


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
            [KeyboardButton(text="Натуральное с приготовлением")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def behavior_kb(kind: PetKind, selected: set[str] | None = None) -> InlineKeyboardMarkup:
    selected = selected or set()
    if kind == PetKind.CAT:
        keys = [
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
        keys = [
            "aggression",
            "high_stress",
            "loud_barking",
            "elderly",
            "mobility_limited",
            "incontinence",
            "needs_treatment",
            "disability",
        ]
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
    """Shown only after a receipt was received."""
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
