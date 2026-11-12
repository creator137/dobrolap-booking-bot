from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from dobrolap_bot.bot import handlers as h
from dobrolap_bot.bot.grooming import QUESTIONS
from dobrolap_bot.bot.presentation import _pet_lines
from dobrolap_bot.domain.enums import PetKind
from dobrolap_bot.domain.models import PetProfile
from dobrolap_bot.config.loader import load_catalog
from dobrolap_bot.repositories.sqlite import SqliteRepository
from dobrolap_bot.integrations.google_sheets import InMemorySheetsGateway
from dobrolap_bot.services.booking import BookingService
from test_client_ux import State
ROOT=Path(__file__).resolve().parents[1]

def msg(text=''):
    return SimpleNamespace(text=text,answer=AsyncMock(),photo=[SimpleNamespace(file_id='REFERENCE')])

@pytest.mark.asyncio
@pytest.mark.parametrize('kind',[PetKind.CAT,PetKind.DOG])
async def test_full_grooming_questionnaire_persisted_and_presented(kind,tmp_path):
    state=State(service_only=True,service_category='grooming',draft_kind=kind.value,draft_name='Test',draft_age_months=24)
    m=msg('Метис')
    await h.set_pet_breed(m,state)
    assert state.current==h.BookingForm.pet_age  # No sex/sterilization/heat questions.
    m.text='5'
    await h.set_pet_weight(m,state)
    assert state.current==h.BookingForm.grooming_question  # No boarding health checklist.
    values=['Да, регулярно','Боится фена, но терпит','Аллергия на шампунь','Недавняя операция','Не трогать левое ухо','Фен, вода','Ласковый голос','Мытьё, когти','Далее','Без духов','Нет','Тестовый владелец']
    for index,answer in enumerate(values):
        if QUESTIONS[index][0]=='result':
            await h.grooming_reference(m,state)
        m.text=answer
        await h.set_grooming_answer(m,state)
    assert state.current==h.BookingForm.add_another_pet
    pet=PetProfile.model_validate(state.data['pets'][0])
    assert pet.grooming_answers['media_consent'] is False
    assert pet.grooming_reference_file_id=='REFERENCE'
    assert not state.data['draft_grooming_answers']
    assert state.data['draft_grooming_reference'] is None
    summary='\n'.join(_pet_lines(pet))
    for text in ['Аллергия на шампунь','Не трогать левое ухо','Фото/видео для соцсетей: Нет','Тестовый владелец','Фото-референс: приложено']:
        assert text in summary
    assert 'Ветпаспорт' not in summary and 'Вакцинация' not in summary
    catalog=load_catalog(ROOT/'config')
    repo=SqliteRepository(tmp_path/'db.sqlite'); await repo.open()
    try:
        service=BookingService(repo=repo,catalog=catalog,sheets=InMemorySheetsGateway())
        booking,_=await service.submit_booking(telegram_user_id=123,customer_name='Test',username=None,consent_at=None,date_from=date(2027,1,10),date_to=date(2027,1,11),pets=[pet],unit_id=None,feeding=None,service_ids=['grooming_cat' if kind==PetKind.CAT else 'bath_dry_dog'],placement_flags=['service_only'],manual_matching=False,service_only=True,customer_contact='+79000000000')
        stored=await service.get(booking.id)
        # Pet profiles are part of the durable booking payload.
        from dobrolap_bot.services.summary import format_owner_summary
        owner=format_owner_summary(stored,catalog)
        assert 'Аллергия на шампунь' in owner and 'Фото/видео для соцсетей: Нет' in owner
    finally:
        await repo.close()

@pytest.mark.asyncio
async def test_consent_requires_explicit_answer_and_health_requires_detail():
    state=State(grooming_index=10,draft_grooming_answers={})
    m=msg('Возможно')
    await h.set_grooming_answer(m,state)
    assert state.data['grooming_index']==10
    state.data['grooming_index']=2;m.text='Да'
    await h.set_grooming_answer(m,state)
    assert state.data['grooming_index']==2

@pytest.mark.asyncio
async def test_boarding_keeps_its_questionnaire():
    state=State(service_only=False,draft_kind='dog')
    await h.set_pet_breed(msg('Метис'),state)
    assert state.current==h.BookingForm.pet_sex
    await h.set_pet_weight(msg('5'),state)
    assert state.current==h.BookingForm.pet_vaccinated

def test_long_summaries_fit_telegram():
    text=('Длинный ответ '+ '🐕'*700+'\n')*12
    parts=h._summary_parts(text)
    assert len(parts)>1
    assert all(len(p.encode('utf-16-le'))//2<=3900 for p in parts)
