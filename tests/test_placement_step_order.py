from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
import pytest
from dobrolap_bot.bot import handlers as h
from dobrolap_bot.domain.models import PetProfile
from dobrolap_bot.domain.enums import PetKind
from dobrolap_bot.config.loader import load_catalog
from test_client_ux import State
ROOT=Path(__file__).resolve().parents[1]

def setup():
    pets=[PetProfile(kind=PetKind.CAT,name='Cat',weight_kg=5),PetProfile(kind=PetKind.DOG,name='Dog',weight_kg=5)]
    return State(pets=[p.model_dump(mode='json') for p in pets]), SimpleNamespace(text='Перейти к подбору',answer=AsyncMock(),answer_photo=AsyncMock())

@pytest.mark.asyncio
@pytest.mark.parametrize('mode,groups',[('Вместе',[[0,1]]),('Раздельно',[[0],[1]])])
async def test_mode_before_tariff_then_room(mode,groups):
    state,msg=setup();catalog=load_catalog(ROOT/'config')
    await h.add_another(msg,state,catalog,None,None,ROOT/'assets')
    assert state.current==h.BookingForm.placement_together
    msg.answer_photo.assert_not_awaited()
    msg.text=mode
    await h.set_placement_together(msg,state,catalog,None,None,ROOT/'assets')
    assert state.current==h.BookingForm.tariff_choice
    assert state.data['placement_groups']==groups
    assert [p.name for p in h._current_tariff_pets(state.data)] == (['Cat','Dog'] if mode=='Вместе' else ['Cat'])
    msg.text='Любой подходящий'
    with patch.object(h,'_run_placement',new_callable=AsyncMock) as run:
        await h.set_tariff_choice(msg,state,catalog,None,None,ROOT/'assets')
        run.assert_awaited_once()

@pytest.mark.asyncio
async def test_next_group_gets_own_tariff_and_back_returns_to_mode():
    state,msg=setup();catalog=load_catalog(ROOT/'config')
    await state.update_data(placement_groups=[[0],[1]],placement_group_index=0,tariff_choice='comfort')
    await h._record_room(msg,state,catalog,None,None,ROOT/'assets','comfort','Room 1')
    assert state.current==h.BookingForm.tariff_choice
    assert state.data['tariff_choice'] is None
    assert [p.name for p in h._current_tariff_pets(state.data)]==['Dog']
    assert len(state.data['room_assignments'])==1
    msg.text='Вернуться назад'
    await h.set_tariff_choice(msg,state,catalog,None,None,ROOT/'assets')
    assert state.current==h.BookingForm.placement_together
    assert len(state.data['pets'])==2
