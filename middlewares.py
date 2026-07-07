from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from typing import Callable, Dict, Any, Awaitable
from database import log_user_activity
import logging

logger = logging.getLogger(__name__)


class LoggingMiddleware(BaseMiddleware):
    """Middleware для логирования всех действий пользователей"""

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event,
        data: Dict[str, Any]
    ) -> Any:
        user = event.from_user if hasattr(event, 'from_user') else None
        if not user:
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            action = 'callback'
            details = event.data or ''
        elif hasattr(event, 'location') and event.location:
            action = 'location'
            details = f"lat={event.location.latitude:.4f}, lon={event.location.longitude:.4f}"
        elif hasattr(event, 'text') and event.text:
            if event.text.startswith('/'):
                action = 'command'
                details = event.text.split()[0]
            else:
                action = 'message'
                details = event.text[:100]
        else:
            action = 'other'
            details = ''

        try:
            await log_user_activity(
                user_id=user.id,
                username=user.username or '',
                first_name=user.first_name or '',
                last_name=user.last_name or '',
                action=action,
                details=details
            )
        except Exception as e:
            logger.error(f"Ошибка логирования: {e}")

        return await handler(event, data)
