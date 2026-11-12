from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from dobrolap_bot.bot.owner_binding import OwnerBindingMiddleware


def update(username='alenrethf',user_id=123,kind='private',text='/start'):
    return SimpleNamespace(message=SimpleNamespace(from_user=SimpleNamespace(id=user_id,username=username,is_bot=False),chat=SimpleNamespace(id=user_id,type=kind),text=text,answer=AsyncMock()))

@pytest.mark.asyncio
async def test_binding_persists_and_updates_dispatcher_and_filters(tmp_path):
    path=tmp_path/'owner.json';dispatcher={}
    binding=OwnerBindingMiddleware(bot_id=1,path=path,username='@alenrethf')
    handler=AsyncMock()
    data={'dispatcher':dispatcher}
    await binding(handler,update(),data)
    assert data['owner_chat_id']==123 and dispatcher['owner_chat_id']==123
    assert OwnerBindingMiddleware(bot_id=1,path=path,username='alenrethf').owner_id==123
    assert path.stat().st_mode & 0o777==0o600
    await binding(handler,update(user_id=456),data)
    assert data['owner_chat_id']==123  # Username cannot rebind after setup.

@pytest.mark.asyncio
@pytest.mark.parametrize('username,kind',[('stranger','private'),('alenrethf','group'),(None,'private')])
async def test_unapproved_identity_does_not_gain_owner_access(tmp_path,username,kind):
    binding=OwnerBindingMiddleware(bot_id=1,path=tmp_path/'owner.json',username='alenrethf')
    data={};await binding(AsyncMock(),update(username=username,kind=kind),data)
    assert data['owner_chat_id'] is None
    assert not binding.path.exists()

@pytest.mark.asyncio
async def test_existing_numeric_owner_takes_priority(tmp_path):
    binding=OwnerBindingMiddleware(bot_id=1,path=tmp_path/'owner.json',username='alenrethf',owner_id=999)
    data={};await binding(AsyncMock(),update(),data)
    assert data['owner_chat_id']==999

@pytest.mark.asyncio
async def test_watcher_resolves_current_owner_instead_of_startup_snapshot(monkeypatch):
    import asyncio
    from dobrolap_bot.services import hold_watcher
    tick=AsyncMock();monkeypatch.setattr(hold_watcher,'_tick',tick)
    async def stop(_):raise asyncio.CancelledError
    monkeypatch.setattr(hold_watcher.asyncio,'sleep',stop)
    with pytest.raises(asyncio.CancelledError):
        await hold_watcher.run_hold_watcher(bot=None,booking_service=None,owner_chat_id=None,owner_chat_id_provider=lambda:123)
    assert tick.call_args.kwargs['owner_chat_id']==123

@pytest.mark.asyncio
async def test_owner_filter_uses_bound_numeric_id(tmp_path):
    from dobrolap_bot.bot.owner import OwnerOnly
    binding=OwnerBindingMiddleware(bot_id=1,path=tmp_path/'owner.json',username='alenrethf')
    data={};await binding(AsyncMock(),update(),data)
    assert await OwnerOnly()(update().message,data['owner_chat_id'])
    assert not await OwnerOnly()(update(user_id=456).message,data['owner_chat_id'])
