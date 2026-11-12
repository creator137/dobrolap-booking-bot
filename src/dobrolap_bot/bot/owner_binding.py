"""One-time owner binding using a Telegram-supplied username in a private update."""
import json
import logging
import os
from pathlib import Path
from aiogram import BaseMiddleware

logger = logging.getLogger(__name__)


class OwnerBindingMiddleware(BaseMiddleware):
    def __init__(self, *, bot_id: int, path: Path, username: str = '', owner_id: int | None = None):
        self.bot_id = bot_id
        self.path = path
        self.username = username.lstrip('@').casefold()
        self.owner_id = owner_id
        if self.owner_id is None and path.exists():
            saved = json.loads(path.read_text())
            if saved.get('bot_id') != bot_id or not isinstance(saved.get('owner_id'), int) or saved['owner_id'] <= 0:
                raise ValueError('Invalid owner binding for this bot')
            self.owner_id = saved['owner_id']

    async def __call__(self, handler, event, data):
        message = getattr(event, 'message', None)
        user = getattr(message, 'from_user', None)
        if (self.owner_id is None and self.username and user and not user.is_bot
                and message.chat.type == 'private' and message.chat.id == user.id
                and (user.username or '').casefold() == self.username):
            self.path.parent.mkdir(parents=True, exist_ok=True)
            pending = self.path.with_suffix('.tmp')
            fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w') as stream:
                json.dump({'bot_id': self.bot_id, 'owner_id': user.id}, stream)
            os.replace(pending, self.path)
            self.owner_id = user.id
            logger.info('Owner account bound for bot=%s', self.bot_id)
            if not (message.text or '').split('@')[0].strip() == '/start':
                await message.answer('Ваш аккаунт привязан как владелец зоогостиницы. Откройте панель управления: /start')
        data['owner_chat_id'] = self.owner_id
        dispatcher = data.get('dispatcher')
        if dispatcher is not None:
            dispatcher['owner_chat_id'] = self.owner_id
        return await handler(event, data)
