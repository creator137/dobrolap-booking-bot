from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from dobrolap_bot.bot import handlers as h
from dobrolap_bot.config.loader import load_catalog
from dobrolap_bot.domain.models import PetProfile
from dobrolap_bot.domain.enums import PetKind
from test_client_ux import State, message
ROOT = Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('kind', list(PetKind))
def test_service_matrix(kind):
    catalog = load_catalog(ROOT / 'config')
    pets = [PetProfile(kind=kind, name='Test')]
    ids = {s.id for s in h._available_services(catalog, pets, service_only=True)}
    boarding = {s.id for s in h._available_services(catalog, pets, service_only=False)}
    assert 'med_care' not in ids  # МедУход только с передержкой
    if kind not in {PetKind.DOG, PetKind.CAT}:
        assert ids == set()
        assert boarding == {'med_care'}
    else:
        assert 'med_care' in boarding
    if kind != PetKind.DOG:
        assert not ids & {'walk', 'dog_trainer', 'dogsitter'}
    groom = {s.id for s in h._available_services(catalog, pets, service_only=True, service_category='grooming')}
    assert not groom & {'walk', 'zoo_taxi', 'med_care', 'cat_nanny'}
    assert bool(groom) == (kind in {PetKind.CAT, PetKind.DOG})

@pytest.mark.asyncio
async def test_rodent_cannot_submit_old_food_button():
    state = State(pets=[{'kind': 'rat', 'name': 'Test'}])
    msg = message('Натуральное — приготовить кашу (250 ₽/сутки)')
    await h.set_feeding(msg, state, load_catalog(ROOT / 'config'))
    assert 'feeding' not in state.data
    assert [b.text for row in msg.answer.call_args.kwargs['reply_markup'].keyboard for b in row] == ['Свой корм', 'Вернуться назад']

@pytest.mark.asyncio
async def test_old_service_selection_is_removed():
    pet = PetProfile(kind=PetKind.CAT, name='Test')
    state = State(service_only=True, service_category='grooming', pets=[pet.model_dump(mode='json')], service_ids=['walk', 'med_care'])
    cb = SimpleNamespace(data='svc:done', message=SimpleNamespace(edit_reply_markup=AsyncMock(), answer=AsyncMock()), answer=AsyncMock())
    await h.toggle_service(cb, state, load_catalog(ROOT / 'config'))
    assert state.data['service_ids'] == []
    cb.answer.assert_awaited_once()

@pytest.mark.asyncio
async def test_category_change_preserves_date_and_profiles():
    pet = PetProfile(kind=PetKind.DOG, name='Test', weight_kg=8)
    state = State(service_only=True, pets=[pet.model_dump(mode='json')], date_from='2027-11-20', arrival_time='16:00')
    msg = message('Выгул (собаки)')
    await h.set_service_location(msg, state, ROOT / 'assets', load_catalog(ROOT / 'config'))
    assert state.current == h.BookingForm.service_address
    assert state.data['date_from'] == '2027-11-20'
    assert len(state.data['pets']) == 1
    assert state.data['service_category'] == 'walk'


@pytest.mark.asyncio
async def test_medcare_removed_from_one_off_menu():
    labels = [b.text for row in h.service_location_kb().keyboard for b in row]
    assert 'МедУход' not in labels
    catalog = load_catalog(ROOT / 'config')
    dog = [PetProfile(kind=PetKind.DOG, name='Test', weight_kg=8)]
    assert 'med_care' not in {s.id for s in h._available_services(catalog, dog, service_only=True)}
    assert 'med_care' in {s.id for s in h._available_services(catalog, dog, service_only=False)}
