from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InputMediaPhoto,
    Message,
    ReplyKeyboardRemove,
    ReplyKeyboardMarkup,
    KeyboardButton,
)

from dobrolap_bot.bot.calendar_kb import (
    build_calendar,
    dates_prompt,
    parse_day,
    parse_nav,
)
from dobrolap_bot.bot.helpers import (
    FEED_MAP,
    KIND_MAP,
    is_young,
    normalize_phone,
    parse_age_months,
    parse_dates,
    parse_single_date,
    parse_time,
    parse_yes,
    resolve_photo_path,
)
from dobrolap_bot.bot.keyboards import (
    add_pet_kb,
    booking_kind_kb,
    placement_together_kb,
    tariff_choice_kb,
    arrival_time_kb,
    behavior_kb,
    behavior_options,
    consent_kb,
    contact_kb,
    extraction_review_kb,
    feeding_kb,
    feeding_source_kb,
    no_kb,
    owner_actions_kb,
    owner_cancel_kb,
    owner_paid_kb,
    passport_kb,
    pet_kind_kb,
    promo_choice_kb,
    services_kb,
    service_location_kb,
    service_place_kb,
    trainer_program_kb,
    submit_kb,
    unit_choice_kb,
    yes_no_kb,
)
from dobrolap_bot.bot.presentation import (
    format_draft_summary,
    format_money,
    placement_reason_label,
    status_label,
    tariff_label,
    service_option_label,
)
from dobrolap_bot.bot.states import BookingForm
from dobrolap_bot.config.loader import Catalog
from dobrolap_bot.domain.enums import BookingStatus, FeedingOption, PetKind
from dobrolap_bot.domain.models import BehaviorFlags, PetProfile
from dobrolap_bot.integrations.google_sheets import SheetsGateway, SheetsUnavailableError
from dobrolap_bot.services.booking import BookingService
from dobrolap_bot.services.placement import PlacementService
from dobrolap_bot.services.pricing import PricingService
from dobrolap_bot.services.arrival import (
    ARRIVAL_RULES_TEXT,
    arrival_price_notice,
    arrival_requires_price_review,
)
from dobrolap_bot.integrations.llm import DisabledLlmAdapter, LlmAdapter, LlmUnavailableError
from dobrolap_bot.bot.presentation import BEHAVIOR_LABELS, format_age
from dobrolap_bot.services.summary import format_client_status, format_owner_summary

router = Router(name="client")
logger = logging.getLogger(__name__)

HOTEL_ADDRESS = 'СНТ «Заречное», 38, Люберецкий район'

# Разовые услуги, которые часто заказывают на несколько дней.
MULTI_DAY_SERVICE_CATEGORIES = frozenset({"walk", "home"})
DOG_ONLY_SERVICE_CATEGORIES = frozenset({"walk", "trainer"})
CAT_ONLY_SERVICE_CATEGORIES = frozenset({"zoopsych"})
PLACE_CHOICE_CATEGORIES = frozenset({"trainer", "zoopsych"})

TRAINER_PROGRAMS = {
    "коррекция проблемного поведения": "behavior_correction",
    "воспитательная дрессировка щенка": "puppy_training",
    "обучение командам": "commands",
    "курс «управляемая городская собака»": "city_dog",
    'курс "управляемая городская собака"': "city_dog",
    "консультация": "consultation",
    "адаптация собаки из приюта": "shelter_adaptation",
}

TRAINER_PROGRAM_LABELS = {
    "behavior_correction": "Коррекция проблемного поведения",
    "puppy_training": "Воспитательная дрессировка щенка",
    "commands": "Обучение командам",
    "city_dog": "Курс «Управляемая городская собака»",
    "consultation": "Консультация",
    "shelter_adaptation": "Адаптация собаки из приюта",
}


async def _send_price_photos(message: Message, assets_dir: Path, filenames: list[str]) -> None:
    for filename in filenames:
        path = assets_dir / "pricing" / filename
        if not path.is_file():
            logger.warning("Price photo missing: %s", path)
            continue
        try:
            await message.answer_photo(
                FSInputFile(path),
                caption="Прайс для ознакомления. Актуальные условия и итоговую стоимость подтвердит руководитель.",
            )
        except Exception:
            logger.exception("Could not send price photo: %s", path)

# Telegram albums arrive as concurrent updates; buffer them so FSM doesn't drop photos.
_passport_album_buffers: dict[str, list[str]] = {}
_passport_album_tasks: dict[str, asyncio.Task] = {}

REVIEW_AND_VOLUNTEER_INFO = (
    "\n\nАкция за отзывы: 5% за отзыв, 10% за отзыв с фото питомца, "
    "15% за отзывы на двух разных площадках. Скидка действует на одну передержку "
    "до 31 дня; повторно — за отзыв на новой площадке. Максимум по акции за отзывы — 25%. "
    "Если подходит акция — выберите «Скидка за отзыв» или «Есть промокод». "
    "После проверки оператор согласует окончательную цену со скидкой. "
    "Можно сочетать не более двух акций.\n"
    "Если вы волонтёр — оставьте заявку, оператор свяжется с вами для уточнения "
    "условий и расчёта льготной стоимости."
)

PROMO_ASK = (
    "Есть промокод или акция? Выберите вариант кнопкой "
    "или введите промокод текстом." + REVIEW_AND_VOLUNTEER_INFO
)


def _available_services(catalog: Catalog, pets: list[PetProfile], *, service_only: bool = False, service_category: str | None = None) -> list:
    preferred = [
        "nail_trim",
        "med_care",
        "bath_dry_dog",
        "grooming_cat",
        "zoo_taxi",
        "walk",
        "hygiene_complex_dog",
    ]
    pet_kinds = {pet.kind for pet in pets}
    by_id = {
        service.id: service
        for service in catalog.services
        if service.active
        and service.id != "natural_feeding"
        and (service_only or service.id not in {"walk", "dogsitter", "cat_nanny"})
        and (not service_only or service.id != "med_care")
        and (not service.applies_to or pet_kinds.issubset(set(service.applies_to)))
    }
    ordered = [by_id[i] for i in preferred if i in by_id]
    for s in catalog.services:
        if s.id in by_id and s not in ordered:
            ordered.append(s)
    if service_category:
        categories = {
            "grooming": {
                "nail_trim",
                "bath_dry_dog",
                "brushing_dog",
                "hygiene_complex_dog",
                "grooming_cat",
                "bath_dry_cat",
                "brushing_cat",
            },
            "taxi": {"zoo_taxi"},
            "walk": {"walk"},
            "trainer": {"dog_trainer"},
            "zoopsych": {"zoopsychologist"},
            "home": {"dogsitter", "cat_nanny"},
        }
        ordered = [item for item in ordered if item.id in categories.get(service_category, set())]
    if pet_kinds and not pet_kinds & {PetKind.DOG, PetKind.CAT}:
        # Грызуны/птицы: в передержке только медуход; в разовых услугах отдельных позиций нет.
        ordered = [item for item in ordered if item.id == "med_care"] if not service_only else []
    return ordered


def _feeding_keyboard(data: dict):
    own_only = any(p["kind"] not in {"dog", "cat"} for p in data.get("pets", []))
    keyboard = feeding_kb()
    if own_only:
        keyboard.keyboard = keyboard.keyboard[:1]
    return keyboard




@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, llm: LlmAdapter) -> None:
    await state.clear()
    await state.set_state(BookingForm.consent)
    llm_notice = (
        "\nСвободный текст о возрасте, поведении и здоровье будет передан сервису OpenAI "
        "для распознавания; результат можно проверить и исправить."
        if not isinstance(llm, DisabledLlmAdapter) else ""
    )
    welcome_text = (
        "Зоогостиница Добролап — пространство, где ваш питомец главный гость. 🐾\n"
        "Вся информация о нас, условиях и доступных услугах — на нашем сайте:\n"
        "🔗 https://dobrolap.clients.site/\n"
        "Меня зовут Алёна, я основатель и ваш проводник в заботе о питомце. Кинолог, "
        "6 лет волонтёрского опыта, работа в зообизнесе.\n"
        "Мы понимаем характер, привычки и настроение животных.\n"
        "Что берём с собой: привычный корм, миски, лоток/пелёнки/клетку, любимые игрушки "
        "и вещи со знакомым запахом. Грызуны — только в своей клетке в тихой комнате, "
        "с ежедневной уборкой и выгулом. Всем — свежая вода, кормление и чистота.\n"
        "Связаться со мной можно напрямую в ➡️Telegram: @alenrethf\n"
        "➡️ ВКонтакте ID 174515997\n"
        "➡️ aloyna777tep@gmail.com\n"
        "➡️+79253350270➡️Telegram: @alenrethf\n"
        "📍 Наш адрес: СНТ «Заречное», 38, Люберецкий район.\n"
        "✅ Много положительных отзывов на картах: Яндекс.Карты и 2ГИС и сотсетях\n"
        "✅Мы каждый день публикуем фото и видео наших гостей!\n"
        "➡️ Наша группа ВК: https://vk.com/zoogost777\n"
        "➡️ Telegram-канал: https://t.me/dobrolapzoo\n"
        "Что мы предлагаем:\n"
        "✅ Своя закрытая территория для выгула\n"
        "✅ Индивидуальное размещение\n"
        "✅ Полный уход: выгул 2 раза в день, кормление, игры.\n"
        "✅ Договор✅ Зоотакси\n"
        "Здесь каждый хвостик будет чувствовать себя как дома! ❤️\n"
        "Ждём вас и ваших питомцев в гости!\n\n"
        "Я бот зоогостиницы. Помогу заполнить анкету, подобрать свободное место и "
        "посчитать предварительную стоимость. Бронь подтверждает руководитель зоогостиницы вручную.\n\n"
        "Обязательные требования к питомцам:\n"
        "• Обработка от паразитов — обязательна для всех.\n"
        "• Вакцинация — обязательна для всех, кроме животных с ограничениями по здоровью "
        "(для них предусмотрена отдельная комната).\n"
        "В ветпаспорте должны быть отметки об обработке от паразитов (блохи + глистогонное) "
        "и о необходимых прививках, включая бешенство.\n"
        "Пожалуйста, сделайте прививки заранее — минимум за 2 недели до заезда.\n\n"
        "Условия бронирования:\n"
        "• Отмена брони: более чем за 24 часа до заезда — полный возврат; "
        "за 24 часа и менее — возврат 50%.\n"
        "• Полная оплата всего срока проживания — при заезде. Продление возможно по согласованию.\n"
        "• Бронь возвращается в конце передержки как залог.\n"
        "Для подтверждения брони нужны: ваше имя и чек об оплате брони.\n\n"
        "Заезд и выезд: в середине дня — обеденный перерыв, точное время уточняйте у "
        "руководителя зоогостиницы. Время заезда и выезда в индивидуальных случаях "
        "согласовывается отдельно.\n\n"
        "Для продолжения нужно согласие на обработку данных питомца, контактных данных "
        "и адреса подачи, если вы закажете зоотакси."
        + llm_notice
    )
    await message.answer(welcome_text, reply_markup=consent_kb())


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Диалог сброшен. /start — новая заявка.")


@router.message(Command("status"))
async def cmd_status(
    message: Message,
    booking_service: BookingService,
    catalog: Catalog,
) -> None:
    booking = await booking_service.repo.find_latest_by_telegram(
        message.from_user.id,
        statuses=[
            BookingStatus.WAITING_OWNER,
            BookingStatus.OWNER_APPROVED,
            BookingStatus.WAITING_PAYMENT,
            BookingStatus.CONFIRMED,
        ],
    )
    if not booking:
        await message.answer("Активных заявок не нашёл. /start — создать новую.")
        return
    await message.answer(format_client_status(booking, catalog))


@router.message(Command("cancel_booking"))
async def cmd_cancel_booking(
    message: Message,
    booking_service: BookingService,
    owner_chat_id: int | None,
) -> None:
    booking = await booking_service.repo.find_latest_by_telegram(
        message.from_user.id,
        statuses=[
            BookingStatus.WAITING_OWNER,
            BookingStatus.OWNER_APPROVED,
            BookingStatus.WAITING_PAYMENT,
            BookingStatus.CONFIRMED,
        ],
    )
    if not booking:
        await message.answer("Активной заявки нет.")
        return
    if booking.status == BookingStatus.WAITING_OWNER:
        await booking_service.cancel(booking.id, "client_request")
        await message.answer(f"Заявка №{booking.id} отменена.")
        if owner_chat_id and message.bot:
            await message.bot.send_message(
                owner_chat_id,
                f"Клиент отменил заявку {booking.id} до подтверждения.",
            )
        return

    await message.answer(
        f"Запрос на отмену заявки №{booking.id} отправлен руководителю зоогостиницы.\n"
        "Политика возврата залога: более чем за 24 часа — полный возврат, "
        "за 24 часа и менее — 50%. Окончательное решение за руководителем зоогостиницы."
    )
    if owner_chat_id and message.bot:
        await message.bot.send_message(
            owner_chat_id,
            f"⚠️ Клиент просит отменить заявку №{booking.id}.\n"
            f"Текущий статус: {status_label(booking.status)}.",
            reply_markup=owner_cancel_kb(booking.id),
        )


def _calendar_kb(*, pick_from: date | None = None, year: int | None = None, month: int | None = None):
    today = date.today()
    anchor = pick_from or today
    y = year or anchor.year
    m = month or anchor.month
    min_date = (pick_from + timedelta(days=1)) if pick_from else today
    return build_calendar(year=y, month=m, today=today, pick_from=pick_from, min_date=min_date)


async def _finish_dates(message: Message, state: FSMContext, date_from: date, date_to: date) -> None:
    await state.update_data(
        date_from=date_from.isoformat(),
        date_to=date_to.isoformat(),
        cal_pick_from=None,
    )
    await state.set_state(BookingForm.arrival_time)
    await message.answer(
        f"Даты: {date_from.strftime('%d.%m.%Y')} → {date_to.strftime('%d.%m.%Y')}\n"
        "Во сколько планируете приехать? Выберите кнопку или введите время, например: 19:30.\n\n"
        + ARRIVAL_RULES_TEXT,
        reply_markup=arrival_time_kb(),
    )


async def _apply_arrival_time(message: Message, state: FSMContext, arrival) -> None:
    data = await state.get_data()
    flags = set(data.get("placement_flags") or [])
    if arrival_requires_price_review(arrival):
        flags.add("arrival_price_review")
    else:
        flags.discard("arrival_price_review")
    await state.update_data(
        arrival_time=arrival.strftime("%H:%M"),
        arrival_price_notice=arrival_price_notice(arrival),
        placement_flags=sorted(flags),
    )
    await state.set_state(BookingForm.pet_kind)
    await message.answer(
        f"Время заезда: {arrival.strftime('%H:%M')}.\n"
        f"{arrival_price_notice(arrival)}\n\n"
        "Кто ваш питомец?",
        reply_markup=pet_kind_kb(),
    )


@router.callback_query(BookingForm.arrival_time, F.data == "arr:noop")
async def arrival_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(BookingForm.arrival_time, F.data == "arr:text")
async def arrival_ask_text(callback: CallbackQuery) -> None:
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(
        "Напишите желаемое время, например: 18:00. Вне утреннего и вечернего окон "
        "технический перерыв: возможность заезда и доплату согласует руководитель."
    )
    await callback.answer()


@router.callback_query(BookingForm.arrival_time, F.data.startswith("arr:"))
async def arrival_pick(callback: CallbackQuery, state: FSMContext) -> None:
    raw = (callback.data or "").removeprefix("arr:")
    arrival = parse_time(raw)
    if arrival is None:
        await callback.answer("Некорректное время", show_alert=True)
        return
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.answer(f"Заезд {arrival.strftime('%H:%M')}")
    await _apply_arrival_time(callback.message, state, arrival)


@router.message(BookingForm.arrival_time)
async def set_arrival_time(message: Message, state: FSMContext) -> None:
    arrival = parse_time(message.text or "")
    if arrival is None:
        await message.answer(
            "Не разобрал время. Выберите кнопку или напишите ЧЧ:ММ, например: 19:30.",
            reply_markup=arrival_time_kb(),
        )
        return
    await _apply_arrival_time(message, state, arrival)


@router.callback_query(BookingForm.consent, F.data == "consent:yes")
async def consent_yes(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(
        consent_at=datetime.now(timezone.utc).isoformat(),
        pets=[],
        service_ids=[],
        cal_pick_from=None,
    )
    await state.set_state(BookingForm.contact)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "Оставьте номер телефона для связи по заявке.\n"
        "Можно безопасно отправить свой номер кнопкой Telegram или ввести его вручную.",
        reply_markup=contact_kb(),
    )
    await callback.answer()


@router.callback_query(BookingForm.consent, F.data == "consent:no")
async def consent_no(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Без согласия продолжить нельзя. Если передумаете — /start.")
    await callback.answer()


async def _start_dates(message: Message, state: FSMContext) -> None:
    today = date.today()
    await state.set_state(BookingForm.dates)
    await message.answer(
        dates_prompt(),
        reply_markup=_calendar_kb(year=today.year, month=today.month),
        parse_mode="HTML",
    )


@router.message(BookingForm.contact, F.contact)
async def set_contact_from_telegram(message: Message, state: FSMContext) -> None:
    if not message.contact or message.contact.user_id not in {None, message.from_user.id}:
        await message.answer("Пожалуйста, отправьте свой номер или введите его вручную.")
        return
    phone = normalize_phone(message.contact.phone_number)
    if not phone:
        await message.answer("Не удалось распознать номер. Введите его вручную, например +7 900 123-45-67.")
        return
    await state.update_data(customer_contact=phone)
    await message.answer(f"Телефон сохранён: {phone}", reply_markup=ReplyKeyboardRemove())
    await _ask_booking_kind(message, state)


@router.message(BookingForm.contact)
async def set_contact_manually(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if text.lower() == "ввести номер вручную":
        await message.answer(
            "Введите номер телефона, например +7 900 123-45-67.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return
    phone = normalize_phone(text)
    if not phone:
        await message.answer("Проверьте номер. Нужны 10–15 цифр, например +7 900 123-45-67.")
        return
    await state.update_data(customer_contact=phone)
    await message.answer(f"Телефон сохранён: {phone}", reply_markup=ReplyKeyboardRemove())
    await _ask_booking_kind(message, state)


async def _ask_booking_kind(message: Message, state: FSMContext) -> None:
    await state.set_state(BookingForm.booking_kind)
    await message.answer(
        "Что вам нужно?",
        reply_markup=booking_kind_kb(),
    )


@router.message(BookingForm.booking_kind)
async def set_booking_kind(message: Message, state: FSMContext, assets_dir: Path) -> None:
    text = (message.text or "").strip().lower()
    if "передержк" in text:
        await state.update_data(service_only=False)
        await _start_dates(message, state)
        return
    if "разов" in text or "без размещен" in text:
        await state.update_data(service_only=True, service_ids=[], service_category=None)
        await message.answer(f"Разовые услуги. Адрес зоогостиницы: {HOTEL_ADDRESS}. Стоимость подтвердит оператор.")
        await _send_price_photos(message, assets_dir, ["04-price-list-services.jpg"])
        await state.set_state(BookingForm.service_location)
        await message.answer("Какая услуга нужна?", reply_markup=service_location_kb())
        return
    await message.answer("Выберите кнопку.", reply_markup=booking_kind_kb())


def _pet_kind_markup_for_category(category: str | None) -> ReplyKeyboardMarkup:
    if category in DOG_ONLY_SERVICE_CATEGORIES:
        return pet_kind_kb(dogs_only=True)
    if category in CAT_ONLY_SERVICE_CATEGORIES:
        return pet_kind_kb(cats_only=True)
    if category in {"grooming", "home"}:
        return pet_kind_kb(dogs_and_cats_only=True)
    return pet_kind_kb()


def _service_dates_prompt(category: str | None) -> str:
    if category in MULTI_DAY_SERVICE_CATEGORIES:
        return (
            "Услуга может понадобиться на несколько дней. "
            "Выберите дату начала, затем дату окончания в календаре "
            "или напишите ДД.ММ.ГГГГ - ДД.ММ.ГГГГ."
        )
    return "Выберите дату визита в календаре или напишите ДД.ММ.ГГГГ."


async def _ask_service_time(message: Message, state: FSMContext) -> None:
    await state.set_state(BookingForm.service_time)
    await message.answer("На какое время планируете услугу? Например: 14:00 или 14 00.")


async def _ask_pet_after_service_time(message: Message, state: FSMContext) -> None:
    category = (await state.get_data()).get("service_category")
    await state.set_state(BookingForm.pet_kind)
    await message.answer("Кто ваш питомец?", reply_markup=_pet_kind_markup_for_category(category))


async def _continue_after_service_place(message: Message, state: FSMContext, catalog: Catalog) -> None:
    data = await state.get_data()
    if data.get("service_category") == "trainer" and not data.get("trainer_program"):
        await state.set_state(BookingForm.trainer_program)
        await message.answer(
            "Какая программа нужна кинологу?",
            reply_markup=trainer_program_kb(),
        )
        return
    await _start_visit(message, state, catalog)


@router.message(BookingForm.service_date)
async def set_service_date(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    category = data.get("service_category")
    today = date.today()
    if category in MULTI_DAY_SERVICE_CATEGORIES:
        parsed = parse_dates(message.text or "")
        if parsed:
            date_from, date_to = parsed
            if date_from < today:
                await message.answer(
                    f"Дата начала не может быть в прошлом (сегодня {today.strftime('%d.%m.%Y')})."
                )
                return
            if date_to <= date_from:
                await message.answer("Дата окончания должна быть позже даты начала.")
                return
            await state.update_data(
                date_from=date_from.isoformat(),
                date_to=date_to.isoformat(),
                cal_pick_from=None,
            )
            await _ask_service_time(message, state)
            return
    visit_date = parse_single_date(message.text or "")
    if visit_date is None:
        await message.answer(
            "Такой даты нет или формат неверный. "
            + (
                "Напишите ДД.ММ.ГГГГ - ДД.ММ.ГГГГ или выберите в календаре."
                if category in MULTI_DAY_SERVICE_CATEGORIES
                else "В ноябре 30 дней. Выберите дату в календаре или напишите ДД.ММ.ГГГГ."
            ),
            reply_markup=_calendar_kb(),
        )
        return
    if visit_date < today:
        await message.answer(f"Дата не может быть в прошлом (сегодня {today.strftime('%d.%m.%Y')}).")
        return
    if category in MULTI_DAY_SERVICE_CATEGORIES:
        await state.update_data(cal_pick_from=visit_date.isoformat())
        await message.answer(
            f"Начало: {visit_date.strftime('%d.%m.%Y')}. Теперь выберите дату окончания "
            "или напишите полный период ДД.ММ.ГГГГ - ДД.ММ.ГГГГ.",
            reply_markup=_calendar_kb(pick_from=visit_date, year=visit_date.year, month=visit_date.month),
        )
        return
    await state.update_data(
        date_from=visit_date.isoformat(),
        date_to=(visit_date + timedelta(days=1)).isoformat(),
        cal_pick_from=None,
    )
    await _ask_service_time(message, state)


@router.message(BookingForm.service_time)
async def set_service_time(message: Message, state: FSMContext) -> None:
    visit_time = parse_time(message.text or "")
    if visit_time is None:
        await message.answer("Не разобрал время. Формат ЧЧ:ММ, например 14:00.")
        return
    await state.update_data(arrival_time=visit_time.strftime("%H:%M"))
    await _ask_pet_after_service_time(message, state)


@router.message(BookingForm.service_location)
async def set_service_location(message: Message, state: FSMContext, assets_dir: Path, catalog: Catalog) -> None:
    text = (message.text or "").strip().lower()
    categories = {
        "в зоогостиницу на груминг": "grooming",
        "зоотакси": "taxi",
        "выгул (собаки)": "walk",
        "кинолог (собаки)": "trainer",
        "зоопсихолог (кошки)": "zoopsych",
        "выезд на дом (зооняня)": "home",
    }
    category = categories.get(text)
    if not category:
        await message.answer("Выберите услугу кнопкой.", reply_markup=service_location_kb())
        return
    await state.update_data(
        service_category=category,
        service_ids=[],
        trainer_program=None,
        cal_pick_from=None,
        service_location=None,
        service_address=None,
    )
    if category in PLACE_CHOICE_CATEGORIES:
        note = (
            "Кинолог — только для собак. Для кошек выберите «Зоопсихолог (кошки)»."
            if category == "trainer"
            else "Зоопсихолог — для кошек. Кинолог работает только с собаками."
        )
        await state.set_state(BookingForm.service_place)
        await message.answer(
            f"{note}\nГде провести занятие? Адрес зоогостиницы ({HOTEL_ADDRESS}) или ваш.",
            reply_markup=service_place_kb(),
        )
        return
    needs_client_address = category in {"home", "walk", "taxi"}
    await state.update_data(
        service_location="home" if needs_client_address else "hotel",
        service_address=None if needs_client_address else HOTEL_ADDRESS,
    )
    if needs_client_address:
        await state.set_state(BookingForm.service_address)
        prompt = (
            "Укажите адрес для выгула (точную стоимость подтвердит оператор):"
            if category == "walk"
            else "Укажите адрес для услуги (точную стоимость подтвердит оператор):"
        )
        await message.answer(prompt, reply_markup=ReplyKeyboardRemove())
        return
    await _start_visit(message, state, catalog)


@router.message(BookingForm.service_place)
async def set_service_place(message: Message, state: FSMContext, catalog: Catalog) -> None:
    text = (message.text or "").strip().lower()
    if text in {"адрес зоогостиницы", "зоогостиница", "гостиница"}:
        await state.update_data(service_location="hotel", service_address=HOTEL_ADDRESS)
        await _continue_after_service_place(message, state, catalog)
        return
    if text in {"ваш адрес", "мой адрес", "у меня"}:
        await state.update_data(service_location="home", service_address=None)
        await state.set_state(BookingForm.service_address)
        await message.answer(
            "Укажите ваш адрес (точную стоимость подтвердит оператор):",
            reply_markup=ReplyKeyboardRemove(),
        )
        return
    await message.answer(
        f"Выберите место: адрес зоогостиницы ({HOTEL_ADDRESS}) или ваш.",
        reply_markup=service_place_kb(),
    )


@router.message(BookingForm.service_address)
async def set_service_address(message: Message, state: FSMContext, catalog: Catalog) -> None:
    address = (message.text or "").strip()
    if len(address) < 3:
        await message.answer("Напишите адрес текстом.")
        return
    await state.update_data(service_address=address, service_location="home")
    await _continue_after_service_place(message, state, catalog)


@router.message(BookingForm.trainer_program)
async def set_trainer_program(message: Message, state: FSMContext, catalog: Catalog) -> None:
    text = (message.text or "").strip().lower()
    program = TRAINER_PROGRAMS.get(text)
    if not program:
        await message.answer("Выберите программу кнопкой.", reply_markup=trainer_program_kb())
        return
    await state.update_data(trainer_program=program)
    await _start_visit(message, state, catalog)


async def _start_visit(message: Message, state: FSMContext, catalog: Catalog) -> None:
    data = await state.get_data()
    if data.get("date_from") and data.get("arrival_time"):
        if data.get("pets"):
            await _ask_services(message, state, catalog)
        else:
            await _ask_pet_after_service_time(message, state)
        return
    await state.set_state(BookingForm.service_date)
    await state.update_data(cal_pick_from=None)
    await message.answer(
        _service_dates_prompt(data.get("service_category")),
        reply_markup=_calendar_kb(),
    )


@router.callback_query(BookingForm.service_date, F.data == "cal:noop")
@router.callback_query(BookingForm.dates, F.data == "cal:noop")
async def cal_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(BookingForm.service_date, F.data == "cal:text")
@router.callback_query(BookingForm.dates, F.data == "cal:text")
async def cal_text_hint(callback: CallbackQuery) -> None:
    await callback.message.answer(
        "Напишите дату визита ДД.ММ.ГГГГ или даты проживания ДД.ММ.ГГГГ - ДД.ММ.ГГГГ.",
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(BookingForm.service_date, F.data == "cal:reset")
@router.callback_query(BookingForm.dates, F.data == "cal:reset")
async def cal_reset(callback: CallbackQuery, state: FSMContext) -> None:
    today = date.today()
    data = await state.get_data()
    await state.update_data(cal_pick_from=None)
    prompt = (
        _service_dates_prompt(data.get("service_category"))
        if data.get("service_only")
        else dates_prompt()
    )
    await callback.message.edit_text(
        prompt,
        reply_markup=_calendar_kb(year=today.year, month=today.month),
        parse_mode="HTML",
    )
    await callback.answer("Сброшено")


@router.callback_query(BookingForm.service_date, F.data.startswith("cal:nav:"))
@router.callback_query(BookingForm.dates, F.data.startswith("cal:nav:"))
async def cal_nav(callback: CallbackQuery, state: FSMContext) -> None:
    parsed = parse_nav(callback.data or "")
    if not parsed:
        await callback.answer()
        return
    year, month = parsed
    data = await state.get_data()
    pick_raw = data.get("cal_pick_from")
    pick_from = date.fromisoformat(pick_raw) if pick_raw else None
    await callback.message.edit_reply_markup(
        reply_markup=_calendar_kb(pick_from=pick_from, year=year, month=month)
    )
    await callback.answer()


@router.callback_query(BookingForm.service_date, F.data.startswith("cal:day:"))
@router.callback_query(BookingForm.dates, F.data.startswith("cal:day:"))
async def cal_day(callback: CallbackQuery, state: FSMContext) -> None:
    chosen = parse_day(callback.data or "")
    if not chosen:
        await callback.answer("Некорректная дата", show_alert=True)
        return
    today = date.today()
    data = await state.get_data()
    if data.get("service_only"):
        category = data.get("service_category")
        multi_day = category in MULTI_DAY_SERVICE_CATEGORIES
        pick_raw = data.get("cal_pick_from")
        if multi_day:
            if not pick_raw:
                if chosen < today:
                    await callback.answer("Дата в прошлом", show_alert=True)
                    return
                await state.update_data(cal_pick_from=chosen.isoformat())
                await callback.message.edit_text(
                    f"Начало услуги: {chosen.strftime('%d.%m.%Y')}. Выберите дату окончания:",
                    reply_markup=_calendar_kb(
                        pick_from=chosen, year=chosen.year, month=chosen.month
                    ),
                )
                await callback.answer(f"С {chosen.strftime('%d.%m.%Y')}")
                return
            date_from = date.fromisoformat(pick_raw)
            if chosen <= date_from:
                await callback.answer("Окончание должно быть позже начала", show_alert=True)
                return
            await state.update_data(
                date_from=date_from.isoformat(),
                date_to=chosen.isoformat(),
                cal_pick_from=None,
            )
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
            await callback.answer()
            await _ask_service_time(callback.message, state)
            return
        if chosen < today:
            await callback.answer("Дата в прошлом", show_alert=True)
            return
        await state.update_data(
            date_from=chosen.isoformat(),
            date_to=(chosen + timedelta(days=1)).isoformat(),
            cal_pick_from=None,
        )
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await callback.answer()
        await _ask_service_time(callback.message, state)
        return
    pick_raw = data.get("cal_pick_from")

    if not pick_raw:
        if chosen < today:
            await callback.answer("Дата в прошлом", show_alert=True)
            return
        await state.update_data(cal_pick_from=chosen.isoformat())
        await callback.message.edit_text(
            dates_prompt(pick_from=chosen),
            reply_markup=_calendar_kb(
                pick_from=chosen, year=chosen.year, month=chosen.month
            ),
            parse_mode="HTML",
        )
        await callback.answer(f"Заезд {chosen.strftime('%d.%m.%Y')}")
        return

    date_from = date.fromisoformat(pick_raw)
    if chosen <= date_from:
        await callback.answer("Выезд должен быть позже заезда", show_alert=True)
        return
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.answer()
    await _finish_dates(callback.message, state, date_from, chosen)


@router.message(BookingForm.dates)
async def set_dates(message: Message, state: FSMContext) -> None:
    parsed = parse_dates(message.text or "")
    if not parsed:
        today = date.today()
        data = await state.get_data()
        pick_raw = data.get("cal_pick_from")
        pick_from = date.fromisoformat(pick_raw) if pick_raw else None
        await message.answer(
            "Не разобрал даты. Выберите в календаре или формат: 10.10.2026 - 15.10.2026",
            reply_markup=_calendar_kb(
                pick_from=pick_from,
                year=(pick_from or today).year,
                month=(pick_from or today).month,
            ),
            parse_mode="HTML",
        )
        return
    date_from, date_to = parsed
    today = date.today()
    if date_from < today:
        await message.answer(
            f"Дата заезда не может быть в прошлом (сегодня {today.strftime('%d.%m.%Y')})."
        )
        return
    await _finish_dates(message, state, date_from, date_to)


@router.message(BookingForm.pet_kind)
async def set_pet_kind(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    category = data.get("service_category")
    kind = KIND_MAP.get((message.text or "").strip().lower())
    markup = _pet_kind_markup_for_category(category)
    if not kind:
        await message.answer("Выберите вариант с клавиатуры.", reply_markup=markup)
        return
    if category in DOG_ONLY_SERVICE_CATEGORIES and kind != PetKind.DOG:
        note = (
            "Кинолог работает только с собаками. Для кошек выберите «Зоопсихолог (кошки)» в списке услуг."
            if category == "trainer"
            else "Выгул доступен только для собак. Выберите «Собака»."
        )
        await message.answer(note, reply_markup=pet_kind_kb(dogs_only=True))
        return
    if category in CAT_ONLY_SERVICE_CATEGORIES and kind != PetKind.CAT:
        await message.answer(
            "Зоопсихолог — для кошек. Для собак выберите «Кинолог (собаки)».",
            reply_markup=pet_kind_kb(cats_only=True),
        )
        return
    if category in {"grooming", "home"} and kind not in {PetKind.DOG, PetKind.CAT}:
        await message.answer("Выберите вариант с клавиатуры.", reply_markup=markup)
        return
    await state.update_data(draft_kind=kind.value)
    await state.set_state(BookingForm.pet_name)
    if data.get("service_only"):
        note = ""
    elif kind in {PetKind.BIRD, PetKind.RABBIT, PetKind.RAT, PetKind.HAMSTER, PetKind.GUINEA_PIG}:
        note = " Для птиц и грызунов обязательно нужна собственная клетка."
    elif kind == PetKind.DOG:
        note = (
            "\n\n‼️Для собак просим привезти: корм, амуницию, ветпаспорт, "
            "(по желанию: средства гигиены, любимые игрушки....)"
        )
    elif kind == PetKind.CAT:
        note = (
            "\n\n‼️ Для кошек с собой просим привезти: ветпаспорт, привычный корм, "
            "лоток с наполнителем, миски и любимые вещи питомца, по необходимости шампунь "
            "или средство для медухода или витамины ( всё необходимое)"
        )
    else:
        note = ""
    await message.answer("Кличка питомца?" + note)


@router.message(BookingForm.pet_name)
async def set_pet_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if len(name) < 1:
        await message.answer("Введите кличку.")
        return
    await state.update_data(draft_name=name)
    data = await state.get_data()
    kind = PetKind(data["draft_kind"])
    if kind not in {PetKind.DOG, PetKind.CAT}:
        await _store_current_pet(message, state)
        return
    await state.set_state(BookingForm.pet_breed)
    await message.answer(
        "Какая порода? Если порода неизвестна или питомец — метис, нажмите «Нет».",
        reply_markup=no_kb(),
    )


async def _store_current_pet(
    message: Message,
    state: FSMContext,
    *,
    passport_ids: list[str] | None = None,
) -> None:
    data = await state.get_data()
    kind = PetKind(data["draft_kind"])
    age_months = data.get("draft_age_months")
    pet = PetProfile(
        kind=kind,
        name=data["draft_name"],
        breed=data.get("draft_breed"),
        age_months=age_months,
        weight_kg=data.get("draft_weight"),
        sex=data.get("draft_sex"),
        neutered=data.get("draft_neutered"),
        in_heat=bool(data.get("draft_heat")),
        is_puppy_or_kitten=is_young(kind, age_months),
        vaccinated=data.get("draft_vaccinated"),
        parasite_treated=data.get("draft_parasite"),
        behavior=BehaviorFlags.model_validate(data.get("draft_behavior") or {}),
        behavior_notes=data.get("draft_behavior_raw"),
        health_notes=data.get("draft_health"),
        passport_file_ids=list(passport_ids or []),
    )
    pets = list(data.get("pets") or [])
    pets.append(pet.model_dump(mode="json"))
    await state.update_data(
        pets=pets,
        draft_kind=None,
        draft_name=None,
        draft_breed=None,
        draft_age_months=None,
        draft_weight=None,
        draft_sex=None,
        draft_neutered=None,
        draft_heat=None,
        draft_vaccinated=None,
        draft_parasite=None,
        draft_behavior=None,
        draft_behavior_raw=None,
        draft_health=None,
        draft_passport_ids=[],
    )
    await state.set_state(BookingForm.add_another_pet)
    young = " (щенок/котёнок)" if pet.is_puppy_or_kitten else ""
    await message.answer(
        f"Питомец «{pet.name}»{young} добавлен. Всего питомцев: {len(pets)}.",
        reply_markup=add_pet_kb(),
    )


@router.message(BookingForm.pet_breed)
async def set_pet_breed(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    breed = None if text.lower() in {"нет", "-", "метьс", "метис", "не знаю"} else text
    await state.update_data(draft_breed=breed)
    await state.set_state(BookingForm.pet_sex)
    await message.answer("Пол питомца?", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Мужской"), KeyboardButton(text="Женский")]], resize_keyboard=True))


@router.message(BookingForm.pet_sex)
async def set_pet_sex(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip().lower()
    if value not in {"мужской", "женский"}:
        await message.answer("Выберите пол: Мужской или Женский.")
        return
    await state.update_data(draft_sex=value)
    await state.set_state(BookingForm.pet_neutered)
    await message.answer("Питомец кастрирован / стерилизована?", reply_markup=yes_no_kb())


@router.message(BookingForm.pet_neutered)
async def set_pet_neutered(message: Message, state: FSMContext) -> None:
    value = parse_yes(message.text or "")
    if value is None:
        await message.answer("Выберите Да или Нет.", reply_markup=yes_no_kb())
        return
    # Sterilized/neutered animals cannot be in heat — skip the question.
    await state.update_data(draft_neutered=value, draft_heat=False)
    data = await state.get_data()
    if data.get("draft_sex") == "женский" and value is False:
        await state.set_state(BookingForm.pet_heat)
        await message.answer(
            "Есть ли сейчас течка или ожидается во время размещения?",
            reply_markup=yes_no_kb(),
        )
        return
    await _ask_pet_age(message, state)


@router.message(BookingForm.pet_heat)
async def set_pet_heat(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("draft_neutered") is True:
        await state.update_data(draft_heat=False)
        await _ask_pet_age(message, state)
        return
    value = parse_yes(message.text or "")
    if value is None:
        await message.answer("Выберите Да или Нет.", reply_markup=yes_no_kb())
        return
    await state.update_data(draft_heat=value)
    if value:
        await message.answer("При течке предлагаем только отдельную комнату.")
    await _ask_pet_age(message, state)


async def _ask_pet_age(message: Message, state: FSMContext) -> None:
    await state.set_state(BookingForm.pet_age)
    await message.answer(
        "Сколько питомцу лет и месяцев? Например: «2 года 3 месяца» или «8 месяцев». "
        "Если меньше месяца, напишите число недель.",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(BookingForm.pet_age)
async def set_pet_age(message: Message, state: FSMContext, llm: LlmAdapter) -> None:
    raw = (message.text or "").strip()
    age = None
    try:
        signals = await llm.extract_pet_signals(raw, field="age")
        if not signals.needs_clarification:
            age = signals.age_months
    except LlmUnavailableError:
        age = parse_age_months(raw)
    if age is None:
        await message.answer(
            "Не удалось однозначно понять возраст. Напишите, например: «2 года 3 месяца» "
            "или точное число месяцев."
        )
        return
    await state.update_data(draft_age_candidate=age)
    await state.set_state(BookingForm.pet_age_review)
    await message.answer(
        f"Возраст: {format_age(age)}. Верно?",
        reply_markup=extraction_review_kb("age"),
    )


@router.callback_query(BookingForm.pet_age_review, F.data.startswith("review:age:"))
async def review_pet_age(callback: CallbackQuery, state: FSMContext) -> None:
    action = (callback.data or "").split(":")[-1]
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer()
    if action != "yes":
        await state.set_state(BookingForm.pet_age)
        await callback.message.answer("Напишите точный возраст ещё раз, например «18 месяцев».")
        return
    data = await state.get_data()
    age = data.get("draft_age_candidate")
    if age is None:
        await state.set_state(BookingForm.pet_age)
        await callback.message.answer("Напишите возраст ещё раз.")
        return
    await state.update_data(draft_age_months=age, draft_age_candidate=None)
    data = await state.get_data()
    if data.get("draft_kind") in {PetKind.DOG.value, PetKind.CAT.value}:
        await state.set_state(BookingForm.pet_weight)
        await callback.message.answer("Вес питомца в кг (число)?")
    else:
        await state.update_data(draft_weight=None)
        await state.set_state(BookingForm.pet_vaccinated)
        await callback.message.answer("Есть действующая вакцинация?", reply_markup=yes_no_kb())


@router.message(BookingForm.pet_weight)
async def set_pet_weight(message: Message, state: FSMContext) -> None:
    try:
        weight = float((message.text or "").replace(",", ".").strip())
        if weight <= 0 or weight > 120:
            raise ValueError
    except ValueError:
        await message.answer("Введите вес числом, например 8.5")
        return
    await state.update_data(draft_weight=weight)
    await state.set_state(BookingForm.pet_vaccinated)
    await message.answer("Есть действующая вакцинация?", reply_markup=yes_no_kb())


@router.message(BookingForm.pet_vaccinated)
async def set_vaccinated(message: Message, state: FSMContext) -> None:
    val = parse_yes(message.text or "")
    if val is None:
        await message.answer("Ответьте «Да» или «Нет».", reply_markup=yes_no_kb())
        return
    await state.update_data(draft_vaccinated=val)
    await state.set_state(BookingForm.pet_parasite)
    await message.answer("Обработка от паразитов сделана?", reply_markup=yes_no_kb())


@router.message(BookingForm.pet_parasite)
async def set_parasite(message: Message, state: FSMContext) -> None:
    val = parse_yes(message.text or "")
    if val is None:
        await message.answer("Ответьте «Да» или «Нет».", reply_markup=yes_no_kb())
        return
    await state.update_data(draft_parasite=val)
    await state.set_state(BookingForm.pet_behavior)
    data = await state.get_data()
    kind = PetKind(data["draft_kind"])
    await state.update_data(draft_behavior_selected=[])
    await message.answer(
        "Расскажите обычным текстом об особенностях поведения и ухода — например, «боится людей, но не агрессивен». "
        "Можно также выбрать несколько пунктов кнопками. Если особенностей нет, нажмите «Особенностей нет».",
        reply_markup=behavior_kb(kind),
    )


async def _finish_behavior(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    selected = set(data.get("draft_behavior_selected") or [])
    flags = BehaviorFlags(**{key: True for key in selected})
    await state.update_data(draft_behavior=flags.model_dump())
    await state.set_state(BookingForm.pet_health)
    await message.answer(
        "Есть дополнительные сведения о здоровье, лекарствах или уходе?\n"
        "Можно написать обычным текстом или нажать «Нет».",
        reply_markup=no_kb(),
    )


@router.callback_query(BookingForm.pet_behavior, F.data.startswith("beh:"))
async def toggle_behavior(callback: CallbackQuery, state: FSMContext) -> None:
    action = (callback.data or "").split(":", 1)[1]
    data = await state.get_data()
    kind = PetKind(data["draft_kind"])
    selected = set(data.get("draft_behavior_selected") or [])
    if action == "none":
        selected.clear()
        await state.update_data(draft_behavior_selected=[])
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer()
        await _finish_behavior(callback.message, state)
        return
    if action == "done":
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer()
        await _finish_behavior(callback.message, state)
        return
    allowed = set(behavior_options(kind))
    if action not in allowed:
        await callback.answer("Неизвестный вариант", show_alert=True)
        return
    if action in selected:
        selected.remove(action)
    else:
        selected.add(action)
    await state.update_data(draft_behavior_selected=sorted(selected))
    await callback.message.edit_reply_markup(reply_markup=behavior_kb(kind, selected))
    await callback.answer()


@router.message(BookingForm.pet_behavior)
async def set_behavior_text(message: Message, state: FSMContext, llm: LlmAdapter) -> None:
    raw = (message.text or "").strip()
    data = await state.get_data()
    kind = PetKind(data["draft_kind"])
    if not raw:
        await message.answer("Опишите поведение текстом или выберите пункты кнопками.", reply_markup=behavior_kb(kind))
        return
    await state.update_data(draft_behavior_raw=raw)
    if raw.lower() in {"нет", "нет особенностей", "-"}:
        await state.update_data(draft_behavior_selected=[])
        await _finish_behavior(message, state)
        return
    try:
        signals = await llm.extract_pet_signals(raw, field="behavior")
    except LlmUnavailableError:
        await message.answer(
            "Текст сохранил для руководителя зоогостиницы. Автоматический разбор сейчас недоступен. "
            "Отметьте известные особенности кнопками; остальные руководитель зоогостиницы увидит в заявке.",
            reply_markup=behavior_kb(kind),
        )
        return
    selected = (set(signals.behavior_flags) & set(behavior_options(kind))) if not signals.needs_clarification else set()
    await state.update_data(draft_behavior_selected=sorted(selected))
    labels = ", ".join(BEHAVIOR_LABELS[key] for key in sorted(selected)) or "явных особенностей не выделено"
    suffix = "\nЕсли смысл не передан полностью, исправьте кнопками: исходный текст сохранён для руководителя зоогостиницы."
    if signals.needs_clarification:
        suffix = "\nФормулировка неоднозначна: отметьте нужные пункты кнопками или уточните текст. Исходный текст сохранён."
    await state.set_state(BookingForm.pet_behavior_review)
    await message.answer(
        f"Я понял: {labels}.{suffix}", reply_markup=extraction_review_kb("behavior")
    )


@router.callback_query(BookingForm.pet_behavior_review, F.data.startswith("review:behavior:"))
async def review_behavior(callback: CallbackQuery, state: FSMContext) -> None:
    action = (callback.data or "").split(":")[-1]
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer()
    if action == "yes":
        await _finish_behavior(callback.message, state)
        return
    data = await state.get_data()
    await state.set_state(BookingForm.pet_behavior)
    await callback.message.answer(
        "Исправьте отмеченные пункты кнопками или напишите описание заново.",
        reply_markup=behavior_kb(PetKind(data["draft_kind"]), set(data.get("draft_behavior_selected") or [])),
    )


@router.message(BookingForm.pet_health)
async def set_health(message: Message, state: FSMContext, llm: LlmAdapter) -> None:
    text = (message.text or "").strip()
    health = None if text.lower() in {"нет", "-"} else text
    if not text:
        await message.answer("Опишите особенности здоровья текстом или нажмите «Нет».", reply_markup=no_kb())
        return
    if health is None:
        await _finish_health(message, state, health=None, flags=[])
        return
    try:
        signals = await llm.extract_pet_signals(health, field="health")
        flags = [] if signals.needs_clarification else signals.health_flags
    except LlmUnavailableError:
        flags = []
        await message.answer(
            "Автоматический разбор недоступен. Сохраню ваше описание дословно "
            "и передам руководителю зоогостиницы на ручную проверку."
        )
    await state.update_data(draft_health_candidate=health, draft_health_flags_candidate=flags)
    await state.set_state(BookingForm.pet_health_review)
    labels = ", ".join(BEHAVIOR_LABELS[key] for key in flags) or "автоматических отметок нет"
    await message.answer(
        f"Описание: {health}\nОтметки: {labels}. Всё верно?",
        reply_markup=extraction_review_kb("health"),
    )


async def _finish_health(message: Message, state: FSMContext, *, health: str | None, flags: list[str]) -> None:
    behavior_data = (await state.get_data()).get("draft_behavior") or {}
    current = BehaviorFlags.model_validate(behavior_data)
    for key in flags:
        if key in BehaviorFlags.model_fields:
            setattr(current, key, True)
    await state.update_data(draft_health=health, draft_behavior=current.model_dump())
    await state.set_state(BookingForm.pet_passport)
    await message.answer(
        "Пришлите фото страниц ветпаспорта:\n"
        "• данные питомца и владельца;\n"
        "• вакцинация, включая бешенство;\n"
        "• обработки от паразитов.\n"
        "Можно несколько фото. Когда закончите — «Готово».\n"
        "Если фото нет — «Без фото» (заявка уйдёт руководителю зоогостиницы как неполная).",
        reply_markup=passport_kb(),
    )


@router.callback_query(BookingForm.pet_health_review, F.data.startswith("review:health:"))
async def review_health(callback: CallbackQuery, state: FSMContext) -> None:
    action = (callback.data or "").split(":")[-1]
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer()
    if action != "yes":
        await state.set_state(BookingForm.pet_health)
        await callback.message.answer("Напишите уточнённое описание здоровья или нажмите «Нет».", reply_markup=no_kb())
        return
    data = await state.get_data()
    await _finish_health(
        callback.message, state,
        health=data.get("draft_health_candidate"),
        flags=list(data.get("draft_health_flags_candidate") or []),
    )


async def _append_passport_photos(
    message: Message, state: FSMContext, file_ids: list[str]
) -> None:
    data = await state.get_data()
    files = list(data.get("draft_passport_ids") or [])
    for file_id in file_ids:
        if file_id and file_id not in files:
            files.append(file_id)
    await state.update_data(draft_passport_ids=files)
    await message.answer(
        f"Фото сохранено ({len(files)}). Ещё фото или «Готово».",
        reply_markup=passport_kb(),
    )


@router.message(BookingForm.pet_passport, F.photo)
async def passport_photo(message: Message, state: FSMContext) -> None:
    file_id = message.photo[-1].file_id
    group_id = message.media_group_id
    if not group_id:
        await _append_passport_photos(message, state, [file_id])
        return

    # Album: wait until Telegram finishes delivering the whole media group.
    key = f"{message.chat.id}:{group_id}"
    _passport_album_buffers.setdefault(key, []).append(file_id)
    previous = _passport_album_tasks.get(key)
    if previous is not None:
        previous.cancel()

    async def _flush_album() -> None:
        try:
            await asyncio.sleep(0.8)
        except asyncio.CancelledError:
            return
        ids = _passport_album_buffers.pop(key, [])
        _passport_album_tasks.pop(key, None)
        if not ids:
            return
        await _append_passport_photos(message, state, ids)

    _passport_album_tasks[key] = asyncio.create_task(_flush_album())


@router.message(BookingForm.pet_passport)
async def passport_done(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip().lower()
    if text not in {"готово", "далее", "ok", "ок", "без фото", "пропустить"}:
        await message.answer(
            "Пришлите страницы с данными питомца и владельца, вакцинацией (включая бешенство) "
            "и обработками от паразитов — или нажмите «Готово».\n"
            "Если фото нет — «Без фото» (заявка уйдёт руководителю зоогостиницы как неполная).",
            reply_markup=passport_kb(),
        )
        return

    data = await state.get_data()
    passport_ids = list(data.get("draft_passport_ids") or [])
    incomplete_flags = list(data.get("placement_flags") or [])
    if not passport_ids:
        incomplete_flags.append(f"incomplete_passport:{data.get('draft_name') or '?'}")
        await message.answer(
            "Фото паспорта нет — помечу заявку как неполную для руководителя зоогостиницы."
        )

    await state.update_data(
        placement_flags=sorted(set(incomplete_flags)),
    )
    await _store_current_pet(message, state, passport_ids=passport_ids)


@router.message(BookingForm.add_another_pet)
async def add_another(
    message: Message,
    state: FSMContext,
    catalog: Catalog,
    sheets: SheetsGateway,
    booking_service: BookingService,
    assets_dir: Path,
) -> None:
    text = (message.text or "").strip().lower()
    if "добавить" in text:
        data = await state.get_data()
        category = data.get("service_category") if data.get("service_only") else None
        await state.set_state(BookingForm.pet_kind)
        await message.answer(
            "Кто следующий питомец?",
            reply_markup=_pet_kind_markup_for_category(category),
        )
        return
    if "подбор" in text or "далее" in text:
        data = await state.get_data()
        if data.get("service_only"):
            flags = sorted(set(data.get("placement_flags") or []) | {"service_only"})
            await state.update_data(unit_id=None, manual_matching=False, placement_flags=flags)
            await message.answer(
                "Размещение не нужно — переходим к выбору услуг.", reply_markup=ReplyKeyboardRemove()
            )
            await _ask_services(message, state, catalog)
            return
        pets_count = len(data.get("pets") or [])
        await state.update_data(tariff_choice=None, room_assignments=[], placement_group_index=0, together_unavailable=False)
        if pets_count > 1:
            await state.set_state(BookingForm.placement_together)
            await message.answer(
                "Как разместить питомцев? Вместе — скидка 50% на второго и последующих; "
                "раздельно — 30%. Для более двух питомцев можно выбрать «Частично» и указать группы.",
                reply_markup=placement_together_kb(partial=pets_count > 2),
            )
        else:
            await state.update_data(placement_groups=[[0]], placement_together=True, together_unavailable=False)
            await _run_placement(message, state, catalog, sheets, booking_service, assets_dir)
        return
    await message.answer("Выберите кнопку.", reply_markup=add_pet_kb())


def _tariff_choice_labels(catalog: Catalog) -> list[str]:
    tariffs = sorted({a.tariff_kind for a in catalog.active_accommodations()})
    return [tariff_label(t) for t in tariffs]


async def _ask_tariff_choice(
    message: Message, state: FSMContext, catalog: Catalog, assets_dir: Path
) -> None:
    labels = _tariff_choice_labels(catalog)
    data = await state.get_data()
    pets = [PetProfile.model_validate(p) for p in data.get("pets") or []]
    if len(pets) > 1:
        await message.answer(
            "Если питомцы живут вместе в одном помещении — скидка 50% на второго и каждого "
            "следующего. При раздельном размещении — 30%. Итог зависит от выбранного тарифа."
        )
    kinds = {pet.kind for pet in pets}
    price_files = []
    if PetKind.DOG in kinds:
        price_files.append("03-price-list-dogs.jpg")
    if kinds - {PetKind.DOG}:
        price_files.append("05-price-list-cats-other.jpg")
    await _send_price_photos(message, assets_dir, price_files)
    await message.answer(
        "Ниже — фото вариантов размещения из каталога. Это знакомство с помещениями; "
        "свободные и подходящие варианты на ваши даты проверю после выбора тарифа.",
        reply_markup=ReplyKeyboardRemove(),
    )
    shown = set()
    for unit in catalog.active_accommodations():
        if unit.tariff_kind in shown or not kinds.issubset(set(unit.allowed_species)):
            continue
        paths = unit.photos_for(pets)
        # A category preview may use a verified room photo, without claiming it is free.
        if not paths:
            paths = [path for group in unit.photo_paths_by_sheet_label.values() for path in group]
        for path_str in paths:
            path = resolve_photo_path(path_str, assets_dir)
            if not path:
                continue
            try:
                caption = f"{tariff_label(unit.tariff_kind)} — пример: {unit.name}"
                if data.get("date_from") and data.get("date_to"):
                    preview_quote = PricingService(catalog).quote(
                        pets=pets,
                        unit=unit,
                        date_from=date.fromisoformat(data["date_from"]),
                        date_to=date.fromisoformat(data["date_to"]),
                        feeding=FeedingOption.OWNER_FOOD,
                    )
                    if preview_quote.has_accommodation_amount:
                        caption += (
                            f"\nПо текущему тарифу: предварительно {format_money(preview_quote.total_rub)} "
                            "за весь выбранный срок"
                            + (" за всех питомцев вместе" if len(pets) > 1 else "")
                            + ". Без питания, услуг и доплаты за заезд. Итог подтвердит руководитель."
                        )
                    else:
                        caption += "\nСтоимость для вашего питомца уточнит руководитель."
                await message.answer_photo(
                    FSInputFile(path), caption=caption
                )
                shown.add(unit.tariff_kind)
                break
            except Exception:
                logger.exception("Could not send tariff preview: %s", path)
    await state.set_state(BookingForm.tariff_choice)
    await message.answer(
        "Какой тариф размещения вас интересует? Если не уверены — выберите «Любой "
        "подходящий», и я подберу по анкете питомца.",
        reply_markup=tariff_choice_kb(labels),
    )


@router.message(BookingForm.tariff_choice)
async def set_tariff_choice(
    message: Message,
    state: FSMContext,
    catalog: Catalog,
    sheets: SheetsGateway,
    booking_service: BookingService,
    assets_dir: Path,
) -> None:
    text = (message.text or "").strip()
    label_to_tariff = {tariff_label(t): t for t in {a.tariff_kind for a in catalog.active_accommodations()}}
    if text == "Любой подходящий":
        tariff_kind = None
    elif text in label_to_tariff:
        tariff_kind = label_to_tariff[text]
    else:
        await message.answer(
            "Выберите тариф кнопкой.", reply_markup=tariff_choice_kb(_tariff_choice_labels(catalog))
        )
        return
    await state.update_data(tariff_choice=tariff_kind)

    data = await state.get_data()
    pets_count = len(data.get("pets") or [])
    if pets_count > 1:
        await state.set_state(BookingForm.placement_together)
        await message.answer(
            "Питомцев несколько — разместить их вместе в одном помещении или раздельно?\n"
            "Вместе: скидка 50% на второго и каждого следующего питомца.\n"
            "Раздельно: скидка 30% на второго и каждого следующего питомца, "
            "помещения подбирает руководитель зоогостиницы.",
            reply_markup=placement_together_kb(),
        )
        return
    await _run_placement(message, state, catalog, sheets, booking_service, assets_dir)


@router.message(BookingForm.placement_together)
async def set_placement_together(
    message: Message,
    state: FSMContext,
    catalog: Catalog,
    sheets: SheetsGateway,
    booking_service: BookingService,
    assets_dir: Path,
) -> None:
    text = (message.text or "").strip().lower()
    data = await state.get_data()
    count = len(data.get("pets") or [])
    if text == "ручной подбор":
        await state.update_data(unit_id=None, room_assignments=[], manual_matching=True)
        await state.set_state(BookingForm.feeding)
        await message.answer(
            "Заявку передам на ручной подбор. Как будем кормить?",
            reply_markup=_feeding_keyboard(await state.get_data()),
        )
        return
    if text in {"запросить вместе у руководителя", "запросить вместе"}:
        flags = sorted(
            set(data.get("placement_flags") or [])
            | {"mixed_species_together_request", "manual_matching"}
        )
        await state.update_data(
            placement_together=True,
            placement_flags=flags,
            placement_groups=[list(range(count))],
            placement_group_index=0,
            room_assignments=[
                {
                    "pet_indices": list(range(count)),
                    "unit_id": None,
                    "sheet_label": None,
                    "manual": True,
                }
            ],
            unit_id=None,
            requested_sheet_label=None,
            manual_matching=True,
            together_unavailable=False,
        )
        await state.set_state(BookingForm.feeding)
        await message.answer(
            "Запрос на совместное размещение разных видов передам руководителю. "
            "Скидку 50% на второго и следующих питомцев учтём после согласования.\n\n"
            "Как будем кормить?",
            reply_markup=_feeding_keyboard(await state.get_data()),
        )
        return
    if text == "частично" and count > 2:
        await state.set_state(BookingForm.placement_groups)
        names = "; ".join(f"{index}: {pet['name']}" for index, pet in enumerate(data["pets"], 1))
        await message.answer(
            f"Укажите группы номерами питомцев: 1,2;3 (первые двое вместе, третий отдельно).\n{names}",
            reply_markup=ReplyKeyboardRemove(),
        )
        return
    if text not in {"вместе", "раздельно"}:
        await message.answer(
            "Выберите кнопку: «Вместе» или «Раздельно».",
            reply_markup=placement_together_kb(partial=count > 2),
        )
        return
    if text == "вместе" and data.get("together_unavailable"):
        await message.answer(
            "Для этой группы совместный вариант не найден. Выберите раздельное размещение, "
            "запросите совместное у руководителя или передайте заявку на ручной подбор."
        )
        return
    together = text == "вместе"
    pets_kinds = {
        PetProfile.model_validate(pet).kind for pet in (data.get("pets") or [])
    }
    if together and len(pets_kinds) > 1:
        flags = sorted(
            set(data.get("placement_flags") or [])
            | {"mixed_species_together_request", "manual_matching"}
        )
        await state.update_data(
            placement_together=True,
            placement_flags=flags,
            placement_groups=[list(range(count))],
            placement_group_index=0,
            room_assignments=[
                {
                    "pet_indices": list(range(count)),
                    "unit_id": None,
                    "sheet_label": None,
                    "manual": True,
                }
            ],
            unit_id=None,
            requested_sheet_label=None,
            manual_matching=True,
        )
        await state.set_state(BookingForm.feeding)
        await message.answer(
            "Разные виды вместе размещаем только после согласования с руководителем. "
            "Заявку отправлю на ручной подбор; скидку 50% на второго питомца учтём после подтверждения.\n\n"
            "Как будем кормить?",
            reply_markup=_feeding_keyboard(await state.get_data()),
        )
        return
    flags = sorted(
        set(data.get("placement_flags") or [])
        | (set() if together else {"separate_placement"})
    )
    groups = [list(range(count))] if together else [[index] for index in range(count)]
    await state.update_data(
        placement_together=together,
        placement_flags=flags,
        placement_groups=groups,
        placement_group_index=0,
        room_assignments=[],
    )
    await _run_placement(message, state, catalog, sheets, booking_service, assets_dir)


@router.message(BookingForm.placement_groups)
async def set_placement_groups(message: Message, state: FSMContext, catalog: Catalog, sheets: SheetsGateway, booking_service: BookingService, assets_dir: Path) -> None:
    data = await state.get_data()
    count = len(data.get("pets") or [])
    try:
        groups = [[int(value.strip()) - 1 for value in group.split(",")] for group in (message.text or "").split(";")]
        indices = [index for group in groups for index in group]
        if sorted(indices) != list(range(count)) or not 1 < len(groups) < count:
            raise ValueError("invalid_groups")
    except ValueError:
        await message.answer("Укажите каждого питомца ровно один раз, например: 1,2;3. Нужна хотя бы одна совместная группа и одна отдельная.")
        return
    await state.update_data(placement_groups=groups, placement_together=False, placement_group_index=0, room_assignments=[])
    await _run_placement(message, state, catalog, sheets, booking_service, assets_dir)


async def _run_placement(
    message: Message,
    state: FSMContext,
    catalog: Catalog,
    sheets: SheetsGateway,
    booking_service: BookingService,
    assets_dir: Path,
) -> None:
    data = await state.get_data()
    pets = [PetProfile.model_validate(p) for p in data.get("pets") or []]
    all_pets = pets
    groups = data.get("placement_groups") or [list(range(len(pets)))]
    group_index = data.get("placement_group_index", 0)
    pets = [all_pets[index] for index in groups[group_index]]
    date_from = date.fromisoformat(data["date_from"])
    date_to = date.fromisoformat(data["date_to"])
    nights = (date_to - date_from).days
    together = data.get("placement_together", True)
    tariff_kind = data.get("tariff_choice")

    try:
        occupied_labels = booking_service.fetch_occupied_labels(date_from, date_to)
    except SheetsUnavailableError as exc:
        logger.exception(
            "availability check failed date_from=%s date_to=%s", date_from, date_to
        )
        incomplete = "calendar_date_range_incomplete" in str(exc)
        flag = "calendar_dates_missing" if incomplete else "sheets_unavailable"
        flags = sorted(set(data.get("placement_flags") or []) | {flag})
        await state.update_data(unit_id=None, manual_matching=True, placement_flags=flags)
        await state.set_state(BookingForm.feeding)
        if incomplete:
            client_text = (
                f"В календаре занятости нет столбцов на даты "
                f"{date_from.strftime('%d.%m.%Y')}–{date_to.strftime('%d.%m.%Y')}.\n"
                "Свободное место проверить нельзя — заявку отправлю руководителю зоогостиницы на ручной подбор.\n\n"
                "Как будем кормить?"
            )
        else:
            client_text = (
                "Календарь занятости сейчас недоступен — не могу показать свободные места.\n"
                "Заявку отправлю руководителю зоогостиницы на ручной подбор.\n\nКак будем кормить?"
            )
        await message.answer(client_text, reply_markup=_feeding_keyboard(await state.get_data()))
        return

    occupied_labels |= {item["sheet_label"].lower() for item in data.get("room_assignments") or []}
    occupied = booking_service.occupied_catalog_ids_from_labels(occupied_labels)

    result = PlacementService(catalog).suggest(
        pets, occupied_unit_ids=occupied, tariff_kind=tariff_kind, limit=100
    )
    flags = sorted(set(data.get("placement_flags") or []) | set(result.owner_flags))
    await state.update_data(
        placement_flags=flags,
        requires_manual=result.requires_manual_matching,
    )

    if not result.candidates:
        if len(pets) > 1:
            mixed = len({p.kind for p in pets}) > 1
            await state.set_state(BookingForm.placement_together)
            keyboard = placement_together_kb(partial=len(all_pets) > 2)
            keyboard.keyboard = [
                [button for button in row if button.text != "Вместе"] for row in keyboard.keyboard
            ]
            keyboard.keyboard = [row for row in keyboard.keyboard if row]
            await state.update_data(together_unavailable=True)
            if mixed:
                keyboard.keyboard.append(
                    [KeyboardButton(text="Запросить вместе у руководителя")]
                )
            keyboard.keyboard.append([KeyboardButton(text="Ручной подбор")])
            reason = (
                "Разные виды животных вместе автоматически не размещаем. "
                if mixed
                else "Совместного свободного помещения, подходящего всем питомцам группы, нет. "
            )
            await message.answer(
                reason
                + (
                    "Можно разместить раздельно, запросить совместное размещение у руководителя "
                    "или изменить группы."
                    if mixed
                    else "Можно разместить раздельно или изменить группы."
                ),
                reply_markup=keyboard,
            )
            return
        # Separate/partial flow: keep every group in room_assignments (auto or manual).
        if len(groups) > 1:
            names = ", ".join(p.name for p in pets)
            remaining = group_index + 1 < len(groups)
            await message.answer(
                f"Для {names} автоматического места не нашёл — передам "
                + (
                    "этого питомца на ручной подбор и продолжу подбор для остальных."
                    if remaining
                    else "этого питомца на ручной подбор руководителя."
                )
            )
            await _record_room(
                message,
                state,
                catalog,
                sheets,
                booking_service,
                assets_dir,
                unit_id="__manual__",
                label="",
            )
            return
        await state.update_data(unit_id=None, manual_matching=True)
        await state.set_state(BookingForm.feeding)
        pet_names = ", ".join(p.name for p in pets)
        no_match_text = (
            f"В тарифе «{tariff_label(tariff_kind)}» свободных мест под {pet_names} не нашёл. "
            if tariff_kind
            else f"Автоматически подходящих свободных мест под {pet_names} не нашёл. "
        )
        await message.answer(
            no_match_text
            + "Заявку всё равно отправлю руководителю зоогостиницы на ручной подбор.\n\n"
            "Как будем кормить?",
            reply_markup=_feeding_keyboard(await state.get_data()),
        )
        return

    pricing = PricingService(catalog)
    choices: list[tuple[str, str]] = []
    offered_labels: dict[str, str] = {}
    await message.answer(
        "Подобрал свободные варианты для: " + ", ".join(p.name for p in pets),
        reply_markup=ReplyKeyboardRemove(),
    )

    for i, cand in enumerate(result.candidates, 1):
        acc = cand.accommodation
        try:
            label = booking_service.free_sheet_label_from_labels(acc.id, occupied_labels)
        except ValueError:
            continue  # Occupancy changed since the first calendar read.
        offered_labels[acc.id] = label
        quote = pricing.quote(
            pets=pets,
            unit=acc,
            date_from=date_from,
            date_to=date_to,
            feeding=FeedingOption.OWNER_FOOD,
            arrival_time=data.get("arrival_time"),
            together=together,
        )
        gross = sum(line.amount_rub for line in quote.lines if line.scope.value == "accommodation")
        net = gross + sum(
            line.amount_rub for line in quote.lines if line.scope.value == "discount"
        )
        day_net = net // nights if nights else net
        day_gross = gross // nights if nights else gross
        if quote.has_accommodation_amount:
            if net != gross:
                price_text = (
                    f"≈ {day_net} ₽/сут. со скидкой (без скидки ≈ {day_gross} ₽/сут.)\n"
                    f"Предварительно за {nights} сут.: {format_money(net)} "
                    f"(без скидки {format_money(gross)})"
                )
            else:
                price_text = f"≈ {day_net} ₽/сут., предварительно за {nights} сут.: {format_money(net)}"
        else:
            price_text = "Стоимость подтвердит оператор после уточнения условий"
        caption = f"{i}. {acc.name}\n{price_text}\nЗалог: {quote.deposit_rub} ₽"
        for line in quote.lines:
            if line.scope.value == "discount":
                caption += f"\n{line.label}: {format_money(line.amount_rub)}"
        if cand.reasons:
            caption += "\nПочему подходит: " + "; ".join(
                placement_reason_label(reason) for reason in cand.reasons[:2]
            )
        if quote.provisional or cand.requires_owner_review:
            caption += "\n⚠️ требует подтверждения руководителем зоогостиницы"
        if acc.photo_paths_by_species and len(acc.calendar_labels()) > 1:
            caption += "\nФото показывает тип размещения; конкретный бокс подтвердит руководитель зоогостиницы."

        choices.append((acc.id, f"{i}. {acc.name} — {quote.total_rub} ₽" if quote.has_accommodation_amount else f"{i}. {acc.name} — расчёт оператора"))

        caption = "Для: " + ", ".join(p.name for p in pets) + "\n" + caption
        photos = []
        for path_str in acc.photos_for(pets, sheet_label=label)[:5]:
            resolved = resolve_photo_path(path_str, assets_dir)
            if resolved:
                photos.append(resolved)
        if photos:
            media = [
                InputMediaPhoto(
                    media=FSInputFile(photo_path),
                    caption=caption if idx == 0 else None,
                )
                for idx, photo_path in enumerate(photos)
            ]
            try:
                await message.answer_media_group(media)
            except Exception:
                logger.exception(
                    "media group failed for unit=%s photos=%s; sending one by one",
                    acc.id,
                    [str(p) for p in photos],
                )
                await message.answer(caption)
                for photo_path in photos:
                    try:
                        await message.answer_photo(FSInputFile(photo_path))
                    except Exception:
                        logger.exception("single photo failed path=%s", photo_path)
        else:
            await message.answer(caption)

    if not choices:
        await state.update_data(unit_id=None, manual_matching=True)
        await state.set_state(BookingForm.feeding)
        await message.answer(
            "Свободные варианты изменились. Передам заявку руководителю зоогостиницы на ручной подбор. "
            "Как будем кормить?", reply_markup=_feeding_keyboard(await state.get_data()),
        )
        return
    if result.requires_manual_matching:
        await message.answer("⚠️ Заявка всё равно уйдёт на ручное подтверждение.")

    await state.set_state(BookingForm.choose_unit)
    await state.update_data(offered_sheet_labels=offered_labels)
    if len(choices) == 1 and all(p.kind in {PetKind.RABBIT, PetKind.RAT, PetKind.HAMSTER, PetKind.GUINEA_PIG, PetKind.BIRD} for p in pets):
        unit_id = choices[0][0]
        await _record_room(message, state, catalog, sheets, booking_service, assets_dir, unit_id, offered_labels[unit_id])
        return
    await message.answer("Выберите вариант:", reply_markup=unit_choice_kb(choices))


async def _record_room(message: Message, state: FSMContext, catalog: Catalog, sheets: SheetsGateway, booking_service: BookingService, assets_dir: Path, unit_id: str, label: str) -> None:
    data = await state.get_data()
    groups = data.get("placement_groups") or [list(range(len(data.get("pets") or [])))]
    index = data.get("placement_group_index", 0)
    assignments = list(data.get("room_assignments") or [])
    manual_unit = unit_id == "__manual__"
    assignments.append(
        {
            "pet_indices": groups[index],
            "unit_id": None if manual_unit else unit_id,
            "sheet_label": label or None,
            "manual": manual_unit,
        }
    )
    first_auto = next((item for item in assignments if item.get("unit_id")), None)
    any_manual = any(item.get("manual") or not item.get("unit_id") for item in assignments)
    await state.update_data(
        room_assignments=assignments,
        placement_group_index=index + 1,
        unit_id=(first_auto or {}).get("unit_id"),
        requested_sheet_label=(first_auto or {}).get("sheet_label"),
        manual_matching=any_manual,
    )
    if index + 1 < len(groups):
        await _run_placement(message, state, catalog, sheets, booking_service, assets_dir)
        return
    await state.set_state(BookingForm.feeding)
    await message.answer(
        "Как будем кормить? Рацион гостиницы платный, стоимость рассчитывается индивидуально.",
        reply_markup=_feeding_keyboard(await state.get_data()),
    )


@router.callback_query(BookingForm.choose_unit, F.data.startswith("unit:"))
async def choose_unit(callback: CallbackQuery, state: FSMContext, catalog: Catalog, sheets: SheetsGateway, booking_service: BookingService, assets_dir: Path) -> None:
    unit_id = callback.data.split(":", 1)[1]
    offered = (await state.get_data()).get("offered_sheet_labels") or {}
    if unit_id == "manual":
        await state.update_data(unit_id=None, requested_sheet_label=None, room_assignments=[], manual_matching=True)
    else:
        if unit_id not in offered:
            await callback.answer("Вариант больше не доступен. Повторите подбор.", show_alert=True)
            return
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer()
        await _record_room(callback.message, state, catalog, sheets, booking_service, assets_dir, unit_id, offered[unit_id])
        return
    await state.set_state(BookingForm.feeding)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Как будем кормить?", reply_markup=_feeding_keyboard(await state.get_data()))
    await callback.answer()


@router.message(BookingForm.feeding)
async def set_feeding(message: Message, state: FSMContext, catalog: Catalog) -> None:
    feeding = FEED_MAP.get((message.text or "").strip().lower())
    data = await state.get_data()
    own_only = any(p["kind"] not in {"dog", "cat"} for p in data.get("pets", []))
    if own_only and feeding != FeedingOption.OWNER_FOOD:
        await message.answer("Для птиц и грызунов — только свой корм. Выберите «Свой корм».", reply_markup=_feeding_keyboard(data))
        return
    if not feeding:
        await message.answer("Выберите вариант с клавиатуры.", reply_markup=_feeding_keyboard(await state.get_data()))
        return
    await state.update_data(feeding=feeding.value, service_ids=[])
    if feeding in {FeedingOption.NATURAL_READY, FeedingOption.NATURAL_PORRIDGE, FeedingOption.NATURAL_COOKED}:
        await state.set_state(BookingForm.feeding_source)
        await message.answer(
            "Кто предоставляет продукты? При покупке гостиница передаст чеки.",
            reply_markup=feeding_source_kb(),
        )
        return
    await _ask_services(message, state, catalog)


async def _ask_services(message: Message, state: FSMContext, catalog: Catalog) -> None:
    await state.set_state(BookingForm.services)
    await message.answer("Переходим к дополнительным услугам.", reply_markup=ReplyKeyboardRemove())
    data = await state.get_data()
    pets = [PetProfile.model_validate(p) for p in data.get("pets") or []]
    available = _available_services(catalog, pets, service_only=bool(data.get("service_only")), service_category=data.get("service_category"))
    items = [(s.id, service_option_label(s), False) for s in available]
    if not items and data.get("service_only"):
        await state.set_state(BookingForm.service_location)
        await message.answer(
            "Эта услуга не подходит выбранным питомцам. "
            "Груминг — для кошек и собак; выгул и кинолог — только для собак; "
            "зоопсихолог — для кошек. МедУход доступен только при передержке. "
            "Выберите другую услугу.",
            reply_markup=service_location_kb(),
        )
        return
    if not items:
        await state.set_state(BookingForm.promo)
        await message.answer(
            "Для этих питомцев дополнительных услуг в каталоге пока нет.\n" + PROMO_ASK,
            reply_markup=promo_choice_kb(),
        )
        return
    await message.answer(
        "Выберите услуги (можно несколько). На кнопках — ориентировочная стоимость; "
        "точную цену подтвердит руководитель. "
        "Если выберете зоотакси, попрошу адрес для расчёта поездки. Нажмите «Готово», когда закончите.",
        reply_markup=services_kb(items),
    )


@router.message(BookingForm.feeding_source)
async def set_feeding_source(message: Message, state: FSMContext, catalog: Catalog) -> None:
    answer = (message.text or "").strip()
    options = {
        "продукты привезу сам(а)": "owner_provides",
        "купите продукты, пожалуйста, с чеками": "hotel_purchases_receipts",
    }
    source = options.get(answer.lower())
    if not source:
        await message.answer("Выберите, кто предоставляет продукты.", reply_markup=feeding_source_kb())
        return
    await state.update_data(natural_food_source=source)
    await _ask_services(message, state, catalog)


@router.callback_query(BookingForm.services, F.data.startswith("svc:"))
async def toggle_service(callback: CallbackQuery, state: FSMContext, catalog: Catalog) -> None:
    action = callback.data.split(":", 1)[1]
    data = await state.get_data()
    selected = set(data.get("service_ids") or [])
    pets = [PetProfile.model_validate(p) for p in data.get("pets") or []]
    available = _available_services(catalog, pets, service_only=bool(data.get("service_only")), service_category=data.get("service_category"))
    allowed_ids = {service.id for service in available}
    selected &= allowed_ids
    await state.update_data(service_ids=sorted(selected))

    if action in {"none", "done"}:
        if data.get("service_only") and (action == "none" or not selected):
            await callback.answer("Выберите хотя бы одну услугу", show_alert=True)
            return
        if action == "none":
            await state.update_data(service_ids=[])
            selected.clear()
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        if "zoo_taxi" in selected and data.get("service_category") == "taxi" and data.get("service_address"):
            await state.update_data(taxi_address=data["service_address"])
            await state.set_state(BookingForm.promo)
            await callback.message.answer(
                "Адрес передам оператору.\n" + PROMO_ASK,
                reply_markup=promo_choice_kb(),
            )
        elif "zoo_taxi" in selected:
            await state.set_state(BookingForm.taxi_address)
            await callback.message.answer("Укажите адрес, откуда забрать питомца для зоотакси:")
        else:
            await state.set_state(BookingForm.promo)
            await callback.message.answer(PROMO_ASK, reply_markup=promo_choice_kb())
        await callback.answer()
        return

    if action not in allowed_ids:
        await callback.answer("Эта услуга не подходит выбранным питомцам", show_alert=True)
        return
    if action in selected:
        selected.remove(action)
    else:
        selected.add(action)
    await state.update_data(service_ids=sorted(selected))
    items = [(s.id, service_option_label(s), s.id in selected) for s in available]
    await callback.message.edit_reply_markup(reply_markup=services_kb(items))
    await callback.answer()


@router.message(BookingForm.taxi_address)
async def set_taxi_address(message: Message, state: FSMContext) -> None:
    address = (message.text or "").strip()
    if len(address) < 5:
        await message.answer("Напишите адрес подробнее, чтобы оператор мог рассчитать поездку.")
        return
    await state.update_data(taxi_address=address)
    await state.set_state(BookingForm.promo)
    await message.answer(
        "Адрес передам оператору для расчёта зоотакси.\n" + PROMO_ASK,
        reply_markup=promo_choice_kb(),
    )


@router.message(BookingForm.promo)
async def set_promo(
    message: Message, state: FSMContext, catalog: Catalog,
    booking_service: BookingService,
) -> None:
    text = (message.text or "").strip()
    lower = text.lower()
    review_claim = lower in {
        "отзыв",
        "акция за отзыв",
        "скидка за отзыв",
        "скидка за отзыв (после проверки)",
    }
    if review_claim:
        await state.set_state(BookingForm.review_proof)
        await message.answer(
            "Пришлите скриншот отзыва фото или документом. "
            "После проверки оператор согласует окончательную цену со скидкой.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return
    if lower in {"есть промокод"}:
        await message.answer(
            "Введите промокод текстом:",
            reply_markup=ReplyKeyboardRemove(),
        )
        return
    if message.photo or message.document:
        await _save_review_proof(message, state, catalog)
        return
    promo = None if lower in {"нет", "-", "нет промокода", "нет промокода / акций"} else text.strip().upper()
    if promo:
        data = await state.get_data()
        pricing = PricingService(catalog)
        rule = pricing.find_active_promo(
            promo,
            on_date=pricing.promo_today(),
        )
        if rule is None:
            await message.answer(
                "Такой промокод не найден, ещё не действует или уже закончился.\n"
                "Проверьте написание или выберите другой вариант.",
                reply_markup=promo_choice_kb(),
            )
            return
        if rule.condition.get("first_placement") and await booking_service.repo.has_prior_placement_by_telegram(message.from_user.id, data.get("customer_contact")):
            await message.answer(
                "Этот промокод действует только на первое размещение. "
                "По вашему аккаунту уже есть действующая или подтверждённая заявка. "
                "Если это ошибка, сообщите руководителю зоогостиницы; продолжить можно без промокода.",
                reply_markup=promo_choice_kb(),
            )
            return
        await message.answer(
            "Промокод принят. Если есть отзыв, пришлите его скриншот после предварительного расчёта; "
            "оператор проверит сочетание скидок."
        )
    await state.update_data(promo_code=promo, promo_verified=bool(promo))
    await _show_summary_message(message, state, catalog)


async def _save_review_proof(message: Message, state: FSMContext, catalog: Catalog) -> None:
    file_id = message.photo[-1].file_id if message.photo else (message.document.file_id if message.document else None)
    if not file_id:
        await message.answer("Пришлите скриншот отзыва фото или документом.")
        return
    await state.update_data(
        review_discount_claim=True,
        review_proof_file_id=file_id,
        review_proof_is_document=bool(message.document),
    )
    await message.answer("Скриншот приложен. Оператор проверит отзыв и окончательную стоимость.")
    await _show_summary_message(message, state, catalog)


@router.message(BookingForm.review_proof)
async def set_review_proof(message: Message, state: FSMContext, catalog: Catalog) -> None:
    await _save_review_proof(message, state, catalog)


@router.message(BookingForm.confirm_submit, F.photo | F.document)
async def add_review_proof_to_summary(message: Message, state: FSMContext, catalog: Catalog) -> None:
    await _save_review_proof(message, state, catalog)


async def _show_summary_message(message: Message, state: FSMContext, catalog: Catalog) -> None:
    data = await state.get_data()
    pets = [PetProfile.model_validate(p) for p in data.get("pets") or []]
    feeding_opt = FeedingOption(data["feeding"]) if data.get("feeding") else None
    service_ids = list(data.get("service_ids") or [])
    unit_id = data.get("unit_id")
    promo = data.get("promo_code")
    assignments = data.get("room_assignments") or []

    quote = None
    unit = catalog.get_accommodation(unit_id) if unit_id else None
    if unit is None:
        for item in assignments:
            assigned_id = item.get("unit_id")
            if assigned_id:
                unit = catalog.get_accommodation(assigned_id)
                if unit:
                    break
    if unit is None and assignments and not data.get("service_only"):
        active = catalog.active_accommodations()
        unit = active[0] if active else None

    if unit and not data.get("service_only"):
        quote = PricingService(catalog).quote(
            pets=pets,
            unit=unit,
            date_from=date.fromisoformat(data["date_from"]),
            date_to=date.fromisoformat(data["date_to"]),
            feeding=feeding_opt,
            service_ids=service_ids,
            promo_code=promo,
            promo_eligible=bool(data.get("promo_verified")),
            arrival_time=data.get("arrival_time"),
            together=data.get("placement_together", True),
            room_assignments=assignments or None,
        )
        if data.get("review_discount_claim"):
            quote.provisional = True
            quote.explanation += (
                " Скидка за отзыв: после проверки оператор согласует окончательную цену со скидкой."
            )
        await state.update_data(
            price_total=(
                quote.total_rub if quote.has_accommodation_amount else None
            ),
            deposit_amount=quote.deposit_rub,
            quote_explanation=quote.explanation,
            quote_provisional=quote.provisional,
        )
    else:
        deposit = PricingService(catalog).deposit_amount(len(pets) or 1)
        await state.update_data(price_total=None, deposit_amount=deposit)

    await state.set_state(BookingForm.confirm_submit)
    refreshed = await state.get_data()
    await message.answer(
        format_draft_summary(data=refreshed, pets=pets, catalog=catalog, quote=quote),
        reply_markup=submit_kb(),
    )


@router.callback_query(BookingForm.confirm_submit, F.data == "submit:yes")
async def submit_yes(
    callback: CallbackQuery,
    state: FSMContext,
    booking_service: BookingService,
    catalog: Catalog,
    owner_chat_id: int | None,
) -> None:
    data = await state.get_data()
    pets = [PetProfile.model_validate(p) for p in data.get("pets") or []]
    feeding = FeedingOption(data["feeding"]) if data.get("feeding") else None
    consent_raw = data.get("consent_at")
    consent_at = datetime.fromisoformat(consent_raw) if consent_raw else None

    try:
        booking, _quote = await booking_service.submit_booking(
            telegram_user_id=callback.from_user.id,
            customer_name=callback.from_user.full_name,
            username=callback.from_user.username,
            consent_at=consent_at,
            date_from=date.fromisoformat(data["date_from"]),
            date_to=date.fromisoformat(data["date_to"]),
            pets=pets,
            unit_id=data.get("unit_id"),
            feeding=feeding,
            service_ids=list(data.get("service_ids") or []),
            placement_flags=list(data.get("placement_flags") or []),
            manual_matching=bool(data.get("manual_matching") or data.get("requires_manual")),
            promo_code=data.get("promo_code"),
            customer_contact=data.get("customer_contact"),
            requested_sheet_label=data.get("requested_sheet_label"),
            arrival_time=data.get("arrival_time"),
            service_details={
                key: value for key, value in {
                    "taxi_address": data.get("taxi_address"),
                    "natural_food_source": data.get("natural_food_source"),
                    "service_location": data.get("service_location"),
                    "service_category": data.get("service_category"),
                    "trainer_program": data.get("trainer_program"),
                    "trainer_program_label": TRAINER_PROGRAM_LABELS.get(
                        data.get("trainer_program") or ""
                    ),
                }.items() if value
            },
            review_discount_claim=bool(data.get("review_discount_claim")),
            review_proof_file_id=data.get("review_proof_file_id"),
            review_proof_is_document=bool(data.get("review_proof_is_document")),
            placement_together=bool(data.get("placement_together", True)),
            room_assignments=data.get("room_assignments") or None,
            service_only=bool(data.get("service_only")),
            service_address=data.get("service_address"),
        )
    except SheetsUnavailableError:
        logger.exception("booking submit failed: Sheets unavailable")
        await callback.message.answer(
            "Календарь недоступен — заявку сейчас сохранить с проверкой занятости нельзя. "
            "Попробуйте позже или напишите руководителю зоогостиницы напрямую."
        )
        await callback.answer()
        return
    except ValueError as exc:
        if str(exc) in {"promo_not_first_placement", "promo_invalid_or_expired"}:
            await state.update_data(promo_code=None, promo_verified=False)
            await state.set_state(BookingForm.promo)
            await callback.message.answer(
                "Промокод больше не применим: срок истёк или право на первое размещение уже использовано. "
                "Введите другой промокод или выберите вариант без промокода.",
                reply_markup=promo_choice_kb(),
            )
            await callback.answer()
            return
        if str(exc) == "selected_unit_occupied":
            await callback.message.answer(
                "Выбранное место только что заняли. Начните подбор заново: /start"
            )
            await callback.answer()
            return
        logger.exception("booking submit failed with invalid data: %s", exc)
        await callback.message.answer(
            "Не удалось отправить заявку из-за ошибки в данных. Проверьте анкету или начните заново: /start"
        )
        await callback.answer()
        return

    summary = format_owner_summary(booking, catalog)
    if owner_chat_id and callback.bot:
        await callback.bot.send_message(
            owner_chat_id,
            summary,
            reply_markup=owner_actions_kb(
                booking.id,
                has_unit=bool(booking.unit_id),
                service_only=bool(booking.payload.get("service_only")),
            ),
        )
        for pet in pets:
            ids = list(pet.passport_file_ids or [])
            if not ids:
                continue
            caption = f"Паспорт: {pet.name} / заявка {booking.id} ({len(ids)} фото)"
            try:
                if len(ids) == 1:
                    await callback.bot.send_photo(owner_chat_id, ids[0], caption=caption)
                else:
                    media = [
                        InputMediaPhoto(media=fid, caption=caption if i == 0 else None)
                        for i, fid in enumerate(ids[:10])
                    ]
                    await callback.bot.send_media_group(owner_chat_id, media=media)
                    for fid in ids[10:]:
                        await callback.bot.send_photo(owner_chat_id, fid)
            except Exception:
                logger.exception(
                    "Could not forward passport photos for booking %s pet %s",
                    booking.id,
                    pet.name,
                )
                for fid in ids:
                    try:
                        await callback.bot.send_photo(
                            owner_chat_id,
                            fid,
                            caption=caption,
                        )
                    except Exception:
                        logger.exception("passport photo forward failed file_id=%s", fid)
        proof_id = booking.payload.get("review_proof_file_id")
        if proof_id:
            try:
                caption = f"Скриншот отзыва / заявка {booking.id}; проверьте площадку и скидку"
                if booking.payload.get("review_proof_is_document"):
                    await callback.bot.send_document(owner_chat_id, proof_id, caption=caption)
                else:
                    await callback.bot.send_photo(owner_chat_id, proof_id, caption=caption)
            except Exception:
                logger.exception("Could not forward review proof for booking %s", booking.id)
        await callback.message.answer(
            f"Заявка №{booking.id} отправлена руководителю зоогостиницы.\n"
            "Ожидайте решения. Реквизиты придут только после подтверждения.\n"
            "Статус: /status"
        )
    else:
        await callback.message.answer(
            "Заявка сохранена, но уведомление руководителю зоогостиницы сейчас недоступно. "
            "Пожалуйста, свяжитесь с зоогостиницей напрямую."
        )

    await state.clear()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.answer()


@router.callback_query(BookingForm.confirm_submit, F.data == "submit:no")
async def submit_no(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Заявку отменил. /start — начать снова.")
    await callback.answer()


async def _accept_receipt(
    message: Message,
    booking_service: BookingService,
    owner_chat_id: int | None,
    file_id: str,
    *,
    as_document: bool = False,
    booking_id: str | None = None,
) -> bool:
    """Attach receipt for WAITING_PAYMENT booking (FSM or SQLite recovery)."""
    bookings = await booking_service.repo.list_by_telegram(
        message.from_user.id,
        statuses=[BookingStatus.WAITING_PAYMENT],
    )
    if not bookings:
        return False
    if booking_id:
        booking = next((item for item in bookings if item.id == booking_id), None)
        if booking is None:
            await message.answer("Эта заявка уже не ожидает оплату. Проверьте /status.")
            return True
    elif len(bookings) == 1:
        booking = bookings[0]
    else:
        ids = ", ".join(item.id for item in bookings)
        await message.answer(
            f"У вас несколько заявок на оплату: {ids}. "
            "Выберите нужную командой /receipt НОМЕР_ЗАЯВКИ и пришлите чек ещё раз."
        )
        return True
    try:
        booking = await booking_service.attach_receipt(booking.id, file_id)
    except Exception:
        logger.exception("receipt attach failed booking=%s", booking.id)
        await message.answer(
            "Не удалось сохранить чек. Попробуйте отправить его ещё раз немного позже."
        )
        return True

    await message.answer(
        "Чек получил и передал руководителю зоогостиницы на проверку. "
        "После подтверждения оплаты бронь будет зафиксирована."
    )
    if owner_chat_id and message.bot:
        if as_document:
            await message.bot.send_document(
                owner_chat_id,
                file_id,
                caption=f"Чек по заявке {booking.id}",
                reply_markup=owner_paid_kb(booking.id),
            )
        else:
            await message.bot.send_photo(
                owner_chat_id,
                file_id,
                caption=f"Чек по заявке {booking.id}",
                reply_markup=owner_paid_kb(booking.id),
            )
    return True


@router.message(Command("receipt"))
async def cmd_receipt(message: Message, state: FSMContext, booking_service: BookingService) -> None:
    parts = (message.text or "").split(maxsplit=1)
    booking_id = parts[1].strip() if len(parts) == 2 else ""
    bookings = await booking_service.repo.list_by_telegram(
        message.from_user.id, statuses=[BookingStatus.WAITING_PAYMENT]
    )
    if not bookings:
        await message.answer("Заявок, ожидающих оплату, нет.")
        return
    if not booking_id and len(bookings) == 1:
        booking_id = bookings[0].id
    if booking_id not in {item.id for item in bookings}:
        ids = ", ".join(item.id for item in bookings)
        await message.answer(f"Укажите номер своей заявки: /receipt НОМЕР_ЗАЯВКИ. Доступные: {ids}")
        return
    await state.set_state(BookingForm.waiting_receipt)
    await state.update_data(booking_id=booking_id)
    await message.answer(f"Пришлите чек по заявке {booking_id} фото или документом.")


@router.message(BookingForm.waiting_receipt, F.photo)
async def receipt_photo_fsm(
    message: Message,
    state: FSMContext,
    booking_service: BookingService,
    owner_chat_id: int | None,
) -> None:
    data = await state.get_data()
    await _accept_receipt(
        message, booking_service, owner_chat_id, message.photo[-1].file_id,
        booking_id=data.get("booking_id"),
    )


@router.message(BookingForm.waiting_receipt, F.document)
async def receipt_document_fsm(
    message: Message,
    state: FSMContext,
    booking_service: BookingService,
    owner_chat_id: int | None,
) -> None:
    if not message.document:
        return
    data = await state.get_data()
    await _accept_receipt(
        message,
        booking_service,
        owner_chat_id,
        message.document.file_id,
        as_document=True,
        booking_id=data.get("booking_id"),
    )


# Recovery after bot restart: accept receipt by SQLite status, not only FSM.
@router.message(F.photo)
async def receipt_photo_recovery(
    message: Message,
    state: FSMContext,
    booking_service: BookingService,
    owner_chat_id: int | None,
) -> None:
    current = await state.get_state()
    if current is not None:
        return
    handled = await _accept_receipt(
        message, booking_service, owner_chat_id, message.photo[-1].file_id
    )
    if not handled:
        return


@router.message(F.document)
async def receipt_document_recovery(
    message: Message,
    state: FSMContext,
    booking_service: BookingService,
    owner_chat_id: int | None,
) -> None:
    current = await state.get_state()
    if current is not None or not message.document:
        return
    await _accept_receipt(
        message,
        booking_service,
        owner_chat_id,
        message.document.file_id,
        as_document=True,
    )


@router.callback_query(F.data.startswith("cli:reply:"))
async def client_reply_start(callback: CallbackQuery, state: FSMContext) -> None:
    booking_id = callback.data.split(":")[-1]
    await state.set_state(BookingForm.reply_to_owner)
    await state.update_data(booking_id=booking_id)
    await callback.message.answer("Напишите ответ руководителю зоогостиницы одним сообщением.")
    await callback.answer()


@router.message(BookingForm.reply_to_owner)
async def client_reply_send(
    message: Message,
    state: FSMContext,
    booking_service: BookingService,
    owner_chat_id: int | None,
) -> None:
    data = await state.get_data()
    booking_id = data.get("booking_id")
    if not booking_id:
        await state.clear()
        return
    text = (message.text or "").strip()
    if not text:
        await message.answer("Пустой ответ. Напишите текст.")
        return
    await booking_service.add_client_reply(booking_id, text)
    if owner_chat_id and message.bot:
        booking = await booking_service.get(booking_id)
        await message.bot.send_message(
            owner_chat_id,
            f"💬 Ответ клиента по заявке {booking_id}:\n{text}",
            reply_markup=owner_actions_kb(
                booking_id,
                has_unit=bool(booking and booking.unit_id),
                service_only=bool(booking and booking.payload.get("service_only")),
            ),
        )
    await message.answer("Ответ отправил руководителю зоогостиницы.")
    await state.clear()
