from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from dobrolap_bot.bot import handlers as h
from dobrolap_bot.bot.presentation import tariff_label
from dobrolap_bot.config.loader import load_catalog
from dobrolap_bot.domain.enums import PetKind
from dobrolap_bot.domain.models import PetProfile
from dobrolap_bot.services.booking import BookingService
from dobrolap_bot.services.placement import PlacementService
from dobrolap_bot.integrations.google_sheets import InMemorySheetsGateway
from test_client_ux import State
ROOT=Path(__file__).resolve().parents[1]

def message(text=''):
    return SimpleNamespace(text=text,answer=AsyncMock(),answer_photo=AsyncMock(),answer_media_group=AsyncMock())

@pytest.mark.asyncio
@pytest.mark.parametrize('kind,label',[(PetKind.RAT,'Крыса'),(PetKind.BIRD,'Птица'),(PetKind.RABBIT,'Кролик')])
async def test_nanny_accepts_small_pets_and_has_operator_priced_service(kind,label):
    catalog=load_catalog(ROOT/'config')
    state=State(service_only=True,service_category='home')
    m=message(label);await h.set_pet_kind(m,state)
    assert state.data['draft_kind']==kind.value
    assert state.current==h.BookingForm.pet_name
    services=h._available_services(catalog,[PetProfile(kind=kind,name='Test')],service_only=True,service_category='home')
    assert {s.id for s in services}=={'small_pet_nanny'}
    assert services[0].price_from_rub is None
    dog_services=h._available_services(catalog,[PetProfile(kind=PetKind.DOG,name='Test')],service_only=True,service_category='home')
    assert {'walk','dogsitter'} <= {s.id for s in dog_services}

@pytest.mark.asyncio
@pytest.mark.parametrize('calendar',[True,False])
async def test_nanny_end_date_can_be_selected(calendar):
    state=State(service_only=True,service_category='home')
    if calendar:
        cb=SimpleNamespace(data='cal:day:2027-11-20',message=SimpleNamespace(edit_text=AsyncMock(),edit_reply_markup=AsyncMock(),answer=AsyncMock()),answer=AsyncMock())
        await h.cal_day(cb,state)
        cb.data='cal:day:2027-11-25';await h.cal_day(cb,state)
    else:
        await h.set_service_date(message('20.11.2027'),state)
        await h.set_service_date(message('25.11.2027'),state)
    assert state.data['date_from']=='2027-11-20'
    assert state.data['date_to']=='2027-11-25'
    assert state.current==h.BookingForm.service_time

@pytest.mark.asyncio
async def test_nanny_same_day_calendar_and_single_day_text():
    state=State(service_only=True,service_category='home')
    await h.set_service_date(message('20.11.2027'),state)
    await h.set_service_date(message('Один день'),state)
    assert state.data['date_to']=='2027-11-21'
    state=State(service_only=True,service_category='home')
    cb=SimpleNamespace(data='cal:day:2027-11-20',message=SimpleNamespace(edit_text=AsyncMock(),edit_reply_markup=AsyncMock(),answer=AsyncMock()),answer=AsyncMock())
    await h.cal_day(cb,state);await h.cal_day(cb,state)
    assert state.current==h.BookingForm.service_time
    assert state.data['date_to']=='2027-11-21'

@pytest.mark.asyncio
async def test_only_one_xxl_and_other_tariffs_for_second_large_dog():
    catalog=load_catalog(ROOT/'config');sheets=InMemorySheetsGateway()
    service=BookingService(repo=None,catalog=catalog,sheets=sheets)
    pets=[PetProfile(kind=PetKind.DOG,name=f'Dog{i}',weight_kg=30,vaccinated=True,parasite_treated=True) for i in range(2)]
    state=State(pets=[p.model_dump(mode='json') for p in pets],placement_groups=[[0],[1]],placement_group_index=0,placement_together=False,date_from='2027-11-20',date_to='2027-11-22')
    m=message();await h._run_placement(m,state,catalog,sheets,service,ROOT/'assets')
    label=state.data['offered_sheet_labels']['premium_xxl']
    assert len(catalog.get_accommodation('premium_xxl').calendar_labels())==1
    await h._record_room(m,state,catalog,sheets,service,ROOT/'assets','premium_xxl',label)
    assert state.current==h.BookingForm.tariff_choice
    labels={b.text for row in m.answer.call_args.kwargs['reply_markup'].keyboard for b in row}
    assert tariff_label('premium') not in labels
    assert 'Любой подходящий' in labels
    assert h._tariff_preview_units(catalog,[pets[1]],state.data['room_assignments'])
    # A stale selected premium tariff must offer alternatives rather than duplicate XXL.
    await state.update_data(tariff_choice='premium')
    await h._run_placement(m,state,catalog,sheets,service,ROOT/'assets')
    assert state.current==h.BookingForm.tariff_choice
    assert state.data['tariff_choice'] is None
    ids={c.accommodation.id for c in PlacementService(catalog).suggest([pets[1]],limit=100).candidates}
    assert not ids & {'standard_m','standard_l','optimal_s','economy'}
    assert h._price_scope([pets[1]],state.data)=='Цена за одного питомца: Dog1. Группа 2 из 2.'

@pytest.mark.asyncio
async def test_nanny_manual_end_hint_keeps_start_date():
    state=State(service_only=True,service_category='home',cal_pick_from='2027-11-20')
    cb=SimpleNamespace(message=SimpleNamespace(answer=AsyncMock()),answer=AsyncMock())
    await h.cal_text_hint(cb,state)
    assert state.data['cal_pick_from']=='2027-11-20'
    assert 'окончания' in cb.message.answer.call_args.args[0]
    await h.set_service_date(message('25.11.2027'),state)
    assert state.data['date_from']=='2027-11-20' and state.data['date_to']=='2027-11-25'
