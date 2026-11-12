from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from dobrolap_bot.bot.handlers import _available_services,_ask_services,toggle_service
from dobrolap_bot.config.loader import load_catalog
from dobrolap_bot.domain.models import PetProfile
from dobrolap_bot.domain.enums import PetKind
from test_client_ux import State
ROOT=Path(__file__).resolve().parents[1]
NEW={'trimming_dog':(3000,7000),'express_shedding_dog':(3000,7000),'model_haircut_dog':(4500,None),'dematting_dog':(200,1500)}

@pytest.mark.asyncio
@pytest.mark.parametrize('kind',[PetKind.DOG,PetKind.CAT,PetKind.RAT])
async def test_grooming_menu_prices_species_and_gallery(kind):
    catalog=load_catalog(ROOT/'config');pet=PetProfile(kind=kind,name='Test')
    services=_available_services(catalog,[pet],service_only=True,service_category='grooming')
    ids={s.id for s in services}
    assert ids & NEW.keys()==(NEW.keys() if kind==PetKind.DOG else set())
    for service in services:
        if service.id in NEW: assert (service.price_from_rub,service.price_to_rub)==NEW[service.id]
    state=State(service_only=True,service_category='grooming',pets=[pet.model_dump(mode='json')])
    msg=SimpleNamespace(answer=AsyncMock(),answer_photo=AsyncMock())
    await _ask_services(msg,state,catalog)
    assert msg.answer_photo.await_count==(4 if kind==PetKind.DOG else 0)
    if kind==PetKind.DOG:
        buttons=[b for row in msg.answer.call_args.kwargs['reply_markup'].inline_keyboard for b in row]
        assert {b.callback_data for b in buttons}>={f'svc:{id}' for id in NEW}
        paths=[str(c.args[0].path) for c in msg.answer_photo.call_args_list]
        assert len(set(paths))==4
        await _ask_services(msg,state,catalog)
        assert msg.answer_photo.await_count==4
        cb=SimpleNamespace(data='svc:dematting_dog',message=SimpleNamespace(edit_reply_markup=AsyncMock()),answer=AsyncMock())
        await toggle_service(cb,state,catalog)
        assert 'dematting_dog' in state.data['service_ids']
        captions=[c.kwargs['caption'] for c in msg.answer_photo.call_args_list]
        assert any('4 500' in c for c in captions)
        assert not any('Разбор колтунов' in c for c in captions)
