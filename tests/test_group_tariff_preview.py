from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from dobrolap_bot.bot.handlers import _ask_tariff_choice
from dobrolap_bot.bot.presentation import tariff_label
from dobrolap_bot.config.loader import load_catalog
from dobrolap_bot.domain.models import PetProfile
from dobrolap_bot.domain.enums import PetKind
from test_client_ux import State
ROOT=Path(__file__).resolve().parents[1]

@pytest.mark.asyncio
@pytest.mark.parametrize('kinds', [(PetKind.CAT,PetKind.DOG),(PetKind.DOG,PetKind.DOG),(PetKind.CAT,PetKind.CAT)])
async def test_two_small_pets_get_m_l_not_single_pet_rooms(kinds):
    catalog=load_catalog(ROOT/'config')
    pets=[PetProfile(kind=k,name=f'Test{i}',weight_kg=5,vaccinated=True,parasite_treated=True) for i,k in enumerate(kinds)]
    state=State(pets=[p.model_dump(mode='json') for p in pets],date_from='2027-01-10',date_to='2027-01-12')
    msg=SimpleNamespace(answer=AsyncMock(),answer_photo=AsyncMock())
    await _ask_tariff_choice(msg,state,catalog,ROOT/'assets')
    labels={b.text for row in msg.answer.call_args.kwargs['reply_markup'].keyboard for b in row}
    assert tariff_label('optimal_s') not in labels
    assert tariff_label('economy') not in labels
    assert tariff_label('standard_m') in labels
    assert tariff_label('standard_l') in labels
    photos=msg.answer_photo.call_args_list
    captions=[c.kwargs.get('caption','') for c in photos]
    assert not any('пример: Оптимальный S' in c or 'пример: Эконом' in c for c in captions)
    if len(set(kinds))>1:
        assert any('пример: Стандарт M' in c for c in captions)
        assert any('пример: Стандарт L' in c for c in captions)
        assert all('совместимость подтверждает' in c for c in captions if '— пример:' in c)
        paths={Path(c.args[0].path).name for c in photos}
        assert '24-standard-m-cat.png' in paths

@pytest.mark.asyncio
async def test_single_small_dog_still_gets_s():
    catalog=load_catalog(ROOT/'config')
    from dobrolap_bot.bot.handlers import _tariff_choice_labels
    assert tariff_label('optimal_s') in _tariff_choice_labels(catalog,[PetProfile(kind=PetKind.DOG,name='Test',weight_kg=5)])
