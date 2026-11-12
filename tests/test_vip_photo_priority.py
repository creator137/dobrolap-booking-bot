from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from dobrolap_bot.bot.handlers import _ask_tariff_choice
from dobrolap_bot.config.loader import load_catalog
from dobrolap_bot.domain.enums import PetKind
from dobrolap_bot.domain.models import PetProfile
from dobrolap_bot.services.placement import PlacementService
from test_client_ux import State
ROOT = Path(__file__).resolve().parents[1]

@pytest.mark.asyncio
@pytest.mark.parametrize('kind', [PetKind.CAT, PetKind.DOG])
async def test_vip_preview_uses_formulas_room(kind):
    pet = PetProfile(kind=kind, name='Test', weight_kg=6, vaccinated=True, parasite_treated=True)
    state = State(pets=[pet.model_dump(mode='json')])
    msg = SimpleNamespace(answer=AsyncMock(), answer_photo=AsyncMock())
    await _ask_tariff_choice(msg, state, load_catalog(ROOT/'config'), ROOT/'assets')
    vip = [call for call in msg.answer_photo.call_args_list if 'VIP+' in call.kwargs.get('caption','')]
    assert len(vip) == 1
    assert Path(vip[0].args[0].path).name == '02-second-floor-formulas-room.jpg'
    assert 'комната с формулами' in vip[0].kwargs['caption']

@pytest.mark.parametrize('kind', [PetKind.CAT, PetKind.DOG])
def test_house_second_floor_is_last_suitable_offer(kind):
    pet = PetProfile(kind=kind, name='Test', weight_kg=6, vaccinated=True, parasite_treated=True)
    catalog = load_catalog(ROOT/'config')
    offers = PlacementService(catalog).suggest([pet], limit=100).candidates
    assert len(offers)>1
    assert offers[-1].accommodation.id == 'house_second_floor'
    assert catalog.get_accommodation('house_second_floor').photo_paths == ['assets/rooms/16-house-reserve-vip-plus.jpg']
