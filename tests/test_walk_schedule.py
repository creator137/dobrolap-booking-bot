from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from dobrolap_bot.bot import handlers as h
from dobrolap_bot.bot.presentation import _service_time_text
from dobrolap_bot.config.loader import load_catalog
from test_client_ux import State
ROOT=Path(__file__).resolve().parents[1]

def msg(text): return SimpleNamespace(text=text,answer=AsyncMock())

@pytest.mark.asyncio
@pytest.mark.parametrize('dates,expected',[('20.11.2027',('2027-11-20','2027-11-21')),('20.11.2027 - 25.11.2027',('2027-11-20','2027-11-25'))])
@pytest.mark.parametrize('schedule',['утром и вечером','в обед','в 8:00 и 20:00','по будням утром, в выходные вечером','14 00'])
async def test_manual_walk_dates_and_free_schedule(dates,expected,schedule):
    state=State(service_only=True,service_category='walk')
    m=msg(dates);await h.set_service_date(m,state)
    assert (state.data['date_from'],state.data['date_to'])==expected
    assert state.current==h.BookingForm.service_time
    m.text=schedule;await h.set_service_time(m,state)
    assert state.data['walk_schedule']==schedule
    assert state.current==h.BookingForm.pet_kind
    assert schedule in _service_time_text(state.data)
    assert schedule in _service_time_text({'service_details':{'service_category':'walk','walk_schedule':schedule}})
    catalog=load_catalog(ROOT/'config')
    await h._start_visit(m,state,catalog)
    assert state.current==h.BookingForm.pet_kind  # Does not ask dates again for free-text schedule.

@pytest.mark.asyncio
async def test_walk_manual_button_and_invalid_dates():
    state=State(service_only=True,service_category='walk',cal_pick_from='2027-11-19')
    cb=SimpleNamespace(message=SimpleNamespace(answer=AsyncMock()),answer=AsyncMock())
    await h.cal_text_hint(cb,state)
    assert state.data['cal_pick_from'] is None
    await h.set_service_date(msg('31.11.2027'),state)
    assert 'date_from' not in state.data
    await h.set_service_date(msg('20.11.2020'),state)
    assert 'date_from' not in state.data

@pytest.mark.asyncio
async def test_service_heat_wording_and_boarding_preserved():
    for service_only in (True,False):
        state=State(service_only=service_only,draft_sex='женский')
        m=msg('Нет');await h.set_pet_neutered(m,state)
        text=m.answer.call_args.args[0]
        assert ('в период оказания услуги' in text) is service_only
        assert ('во время размещения' in text) is not service_only

@pytest.mark.asyncio
async def test_grooming_still_requires_exact_time():
    state=State(service_only=True,service_category='grooming')
    await h.set_service_time(msg('утром и вечером'),state)
    assert 'arrival_time' not in state.data
    await h.set_service_time(msg('14 00'),state)
    assert state.data['arrival_time']=='14:00'

@pytest.mark.asyncio
async def test_walk_schedule_saved_and_visible_to_owner(tmp_path):
    from datetime import date
    from dobrolap_bot.repositories.sqlite import SqliteRepository
    from dobrolap_bot.services.booking import BookingService
    from dobrolap_bot.integrations.google_sheets import InMemorySheetsGateway
    from dobrolap_bot.domain.models import PetProfile
    from dobrolap_bot.domain.enums import PetKind
    from dobrolap_bot.services.summary import format_owner_summary
    from dobrolap_bot.bot.presentation import format_draft_summary
    catalog=load_catalog(ROOT/'config')
    repo=SqliteRepository(tmp_path/'app.db');await repo.open()
    try:
        service=BookingService(repo=repo,catalog=catalog,sheets=InMemorySheetsGateway())
        schedule='утром в 8:00 и вечером в 20:00'
        pet=PetProfile(kind=PetKind.DOG,name='Test')
        booking,_=await service.submit_booking(telegram_user_id=123,customer_name='Test',username=None,consent_at=None,date_from=date(2027,11,20),date_to=date(2027,11,25),pets=[pet],unit_id=None,feeding=None,service_ids=['walk'],placement_flags=['service_only'],manual_matching=False,service_only=True,service_details={'service_category':'walk','walk_schedule':schedule})
        stored=await service.get(booking.id)
        assert stored.payload['service_details']['walk_schedule']==schedule
        assert schedule in format_owner_summary(stored,catalog)
        assert schedule in format_draft_summary(data={'service_only':True,'service_category':'walk','walk_schedule':schedule,'date_from':'2027-11-20','date_to':'2027-11-25'},pets=[pet],catalog=catalog,quote=None)
    finally:
        await repo.close()
