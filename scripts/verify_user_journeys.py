"""Drive actual aiogram routing/FSM with Telegram-shaped updates; no external writes.
This is a transport simulation, not a Telegram app acceptance test.
Run: PYTHONPATH=src .venv/bin/python scripts/verify_user_journeys.py
"""
import asyncio
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.types import Update, Message, User, Chat, CallbackQuery, MessageEntity
from dobrolap_bot.bot.handlers import router
from dobrolap_bot.bot.audit import FlowAuditMiddleware
from dobrolap_bot.config.loader import load_catalog
from dobrolap_bot.integrations.google_sheets import InMemorySheetsGateway
from dobrolap_bot.integrations.llm import DisabledLlmAdapter
from dobrolap_bot.repositories.sqlite import SqliteRepository
from dobrolap_bot.services.booking import BookingService

ROOT = Path(__file__).resolve().parents[1]

class Capture(BaseSession):
    def __init__(self):
        super().__init__()
        self.events = []
    async def close(self): pass
    async def stream_content(self, *args, **kwargs):
        yield b''
    async def make_request(self, bot, method, timeout=None):
        raw = method.model_dump(exclude_none=True)
        self.events.append({'method': method.__api_method__, 'text': raw.get('text', raw.get('caption')), 'markup': raw.get('reply_markup')})
        msg = Message(message_id=len(self.events), date=datetime.now(timezone.utc), chat=Chat(id=12345, type='private'), from_user=User(id=bot.id, is_bot=True, first_name='Bot'), text=raw.get('text',''))
        if method.__api_method__ == 'sendMediaGroup': return [msg for _ in raw['media']]
        if method.__api_method__ in {'answerCallbackQuery', 'deleteMessage'}: return True
        return msg

async def main():
    transport = Capture()
    bot = Bot('123456:TEST_TOKEN', session=transport)
    dp = Dispatcher()
    dp.update.middleware(FlowAuditMiddleware())
    dp.include_router(router)
    catalog = load_catalog(ROOT/'config')
    with tempfile.TemporaryDirectory() as tmp:
        repo = SqliteRepository(Path(tmp)/'test.db')
        await repo.open()
        sheets = InMemorySheetsGateway()
        service = BookingService(repo=repo, catalog=catalog, sheets=sheets)
        deps = dict(catalog=catalog, sheets=sheets, booking_service=service, assets_dir=ROOT/'assets', llm=DisabledLlmAdapter(), owner_chat_id=99999, payment_instructions='TEST')
        report = []
        seq = 0
        for name, kinds, category, grouping, stress in [
            ('rat_boarding',['Крыса'],None,None,False),
            ('cat_boarding',['Кошка'],None,None,False),
            *[(kind+'_boarding',[kind],None,None,False) for kind in ['Кролик','Хомяк','Морская свинка','Птица']],
            ('three_dogs_together',['Собака']*3,None,'Вместе',False),
            ('three_dogs_partial',['Собака']*3,None,'Частично',False),
            ('three_dogs_stress',['Собака']*3,None,'Вместе',True),
            ('cat_grooming',['Кошка'],'В зоогостиницу на груминг',None,False),
            ('rat_grooming_to_care',['Крыса'],'В зоогостиницу на груминг',None,False),
            ('dog_walk',['Собака'],'Выгул (собаки)',None,False),
            ('dog_taxi',['Собака'],'Зоотакси',None,False),
            ('dog_trainer',['Собака'],'Кинолог (собаки)',None,False),
        ]:
            user_id = 20000+len(report)
            user = User(id=user_id, is_bot=False, first_name='Scenario')
            state = dp.fsm.get_context(bot=bot, chat_id=user_id, user_id=user_id)
            start = len(transport.events)
            steps=[]
            async def send(text=None, callback=None):
                nonlocal seq
                seq += 1
                msg = Message(message_id=seq, date=datetime.now(timezone.utc), chat=Chat(id=user_id,type='private'),from_user=user,text=text or 'button',entities=[MessageEntity(type='bot_command', offset=0,length=6)] if text == '/start' else None)
                before=await state.get_state()
                update = Update(update_id=seq, callback_query=CallbackQuery(id=str(seq), from_user=user, chat_instance='test', message=msg, data=callback)) if callback else Update(update_id=seq,message=msg)
                await dp.feed_update(bot, update, **deps)
                steps.append({'input':callback or text,'from':before,'to':await state.get_state()})
            await send('/start')
            await send(callback='consent:yes')
            await send('+79000000000')
            await send('Разовая услуга без размещения' if category else 'Передержка')
            if category:
                await send(category)
                if (await state.get_state()).endswith('service_address'): await send('Тестовый адрес, дом 1')
                await send('20.11.2027')
                await send('16 00')
            else:
                await send('20.11.2027 - 22.11.2027')
                await send(callback='arr:19:00')
            for i,kind in enumerate(kinds):
                await send(kind)
                await send(f'Test{i+1}')
                if kind in {'Кошка','Собака'}:
                    await send('Нет'); await send('Женский'); await send('Да'); await send('Нет')
                    await send('2 года'); await send(callback='review:age:yes'); await send('6')
                    await send('Да'); await send('Да')
                    if stress and i==0: await send(callback='beh:high_stress')
                    await send(callback='beh:done')
                    await send('Нет'); await send('Без фото')
                if i+1<len(kinds): await send('Добавить питомца')
            await send('Перейти к подбору')
            if grouping:
                await send(grouping)
                if grouping=='Частично': await send('1,2;3')
            for _ in range(15):
                current=(await state.get_state() or '').split(':')[-1]
                if current=='choose_unit':
                    data=await state.get_data()
                    await send(callback='unit:'+next(iter(data['offered_sheet_labels'])))
                elif current=='placement_together':
                    await send('Вместе')  # stale retry must not repeat calculation
                    await send('Ручной подбор')
                elif current=='feeding': await send('Свой корм')
                elif current=='service_location': await send('МедУход')
                elif current=='services':
                    data=await state.get_data()
                    options=[b for e in transport.events[start:] for row in (e.get('markup') or {}).get('inline_keyboard',[]) for b in row if b.get('callback_data','').startswith('svc:') and b['callback_data'] not in {'svc:done','svc:none'}]
                    if category and options: await send(callback=options[-1]['callback_data'])
                    await send(callback='svc:done')
                elif current=='taxi_address': await send('Тестовый адрес, дом 1')
                elif current=='promo': await send('Нет')
                elif current=='confirm_submit': break
                else: raise AssertionError((name,current,steps[-4:]))
            assert (await state.get_state()).endswith('confirm_submit'), (name,steps[-5:])
            data=await state.get_data()
            assignments=data.get('room_assignments') or []
            assert len({a['sheet_label'] for a in assignments}) == len(assignments)
            if name=='cat_boarding':
                assert data['unit_id'] not in {'premium_xxl','outdoor_comfort'}
            if category:
                prompts=[e for e in transport.events[start:] if 'Выберите дату визита' in (e.get('text') or '')]
                assert len(prompts)==1, (name,len(prompts))
            await send(callback='submit:yes')
            assert await state.get_state() is None, (name, steps[-3:])
            report.append({'scenario':name,'result':'PASS','steps':steps,'outputs':[{'method':e['method'],'text':e['text']} for e in transport.events[start:]]})
        await repo.close()
        Path('docs/user-journeys-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print(f'{len(report)} complete journeys PASS; transcript: docs/user-journeys-report.json')
    await bot.session.close()

if __name__=='__main__': asyncio.run(main())
