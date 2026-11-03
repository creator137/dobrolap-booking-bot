"""Privacy-preserving FSM trace: action codes only, never message contents."""
import logging
from aiogram import BaseMiddleware

logger = logging.getLogger(__name__)


class FlowAuditMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        state = data.get("state")
        before = await state.get_state() if state else None
        callback = getattr(event, "callback_query", None)
        # Callback payloads may include identifiers; retain only the action family.
        action = callback.data.split(":", 1)[0] if callback and callback.data else "message"
        try:
            return await handler(event, data)
        finally:
            after = await state.get_state() if state else None
            draft = await state.get_data() if state else {}
            logger.info("flow update=%s action=%s from=%s to=%s category=%s manual=%s flags=%s",
                        getattr(event, "update_id", None), action, before, after,
                        draft.get("service_category"), draft.get("manual_matching"),
                        [f for f in draft.get("placement_flags", []) if ":" not in f])
