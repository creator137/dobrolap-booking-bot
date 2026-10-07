from aiogram.fsm.state import State, StatesGroup


class BookingForm(StatesGroup):
    consent = State()
    dates = State()
    pet_kind = State()
    pet_name = State()
    pet_weight = State()
    pet_vaccinated = State()
    pet_parasite = State()
    pet_behavior = State()
    pet_health = State()
    pet_passport = State()
    add_another_pet = State()
    choose_unit = State()
    feeding = State()
    services = State()
    confirm_submit = State()
    waiting_receipt = State()
    reply_to_owner = State()


class OwnerForm(StatesGroup):
    ask_question = State()
    suggest_unit = State()
    reject_reason = State()
