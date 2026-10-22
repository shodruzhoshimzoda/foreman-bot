from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject

from bot.db import Database


class IsChief(BaseFilter):
    async def __call__(self, event: TelegramObject, db: Database) -> bool:
        user = getattr(event, "from_user", None)
        return user is not None and await db.is_chief(user.id)


class IsActiveForeman(BaseFilter):
    async def __call__(self, event: TelegramObject, db: Database) -> bool:
        user = getattr(event, "from_user", None)
        return user is not None and await db.is_active_foreman(user.id)
