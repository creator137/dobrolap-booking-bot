from pathlib import Path
from unittest.mock import AsyncMock
from types import SimpleNamespace
import pytest
from dobrolap_bot.bot.handlers import _ask_tariff_choice, set_tariff_choice
from dobrolap_bot.bot.presentation import tariff_label
from dobrolap_bot.bot.states import BookingForm
from dobrolap_bot.config.loader import load_catalog
from dobrolap_bot.domain.enums import PetKind
from dobrolap_bot.domain.models import PetProfile
from test_client_ux import State
ROOT = Path(__file__).resolve().parents[1]

@pytest.mark.asyncio
@pytest.mark.parametrize('kind', [PetKind.CAT, PetKind.DOG, PetKind.RAT])
async def test_tariffs_match_species_and_preview(kind):
    catalog=load_catalog(ROOT/'config')
    state=State(pets=[PetProfile(kind=kind,name='Test').model_dump(mode='json')])
    msg=SimpleNamespace(answer=AsyncMock(),answer_photo=AsyncMock())
    await _ask_tariff_choice(msg,state,catalog,ROOT/'assets')
    labels={b.text for row in msg.answer.call_args.kwargs['reply_markup'].keyboard for b in row}
    expected={tariff_label(a.tariff_kind) for a in catalog.active_accommodations() if kind in a.allowed_species}
    assert labels==expected|{'Любой подходящий','Вернуться назад'}
    if kind==PetKind.CAT:
        assert not {tariff_label('outdoor'), 'Премиум (усиленный вольер XXL)'} & labels

@pytest.mark.asyncio
async def test_back_preserves_draft_and_rejects_stale_species_tariff():
    catalog=load_catalog(ROOT/'config')
    data=dict(pets=[PetProfile(kind=PetKind.CAT,name='Test').model_dump(mode='json')], date_from='2027-01-10',date_to='2027-01-12',customer_contact='TEST')
    state=State(**data)
    msg=SimpleNamespace(text=tariff_label(catalog.get_accommodation('outdoor_comfort').tariff_kind),answer=AsyncMock())
    await set_tariff_choice(msg,state,catalog,None,None,ROOT/'assets')
    assert 'tariff_choice' not in state.data
    msg.text='Вернуться назад'
    await set_tariff_choice(msg,state,catalog,None,None,ROOT/'assets')
    assert state.current==BookingForm.add_another_pet
    assert all(state.data[key]==value for key,value in data.items())
