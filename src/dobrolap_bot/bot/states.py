from aiogram.fsm.state import State, StatesGroup


class BookingForm(StatesGroup):
    consent = State()
    contact = State()
    dates = State()
    arrival_time = State()
    pet_kind = State()
    pet_name = State()
    pet_breed = State()
    pet_age = State()
    pet_age_review = State()
    pet_weight = State()
    pet_vaccinated = State()
    pet_parasite = State()
    pet_behavior = State()
    pet_behavior_review = State()
    pet_health = State()
    pet_health_review = State()
    pet_passport = State()
    add_another_pet = State()
    choose_unit = State()
    feeding = State()
    feeding_source = State()
    services = State()
    taxi_address = State()
    promo = State()
    confirm_submit = State()
    waiting_receipt = State()
    reply_to_owner = State()


class OwnerForm(StatesGroup):
    ask_question = State()
    reject_reason = State()
    cancel_reason = State()
    refund_note = State()
