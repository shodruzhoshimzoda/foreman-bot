from aiogram import Router
from aiogram.types import CallbackQuery, Message

from db import Database
from keyboards import chief_menu, foreman_menu

router = Router()


@router.message()
async def unknown_message(message: Message, db: Database):
    uid = message.from_user.id
    if await db.is_chief(uid):
        await message.answer("Не понял. Воспользуйтесь меню ниже или командой /help.", reply_markup=chief_menu())
    elif await db.is_active_foreman(uid):
        await message.answer("Не понял. Воспользуйтесь меню ниже или командой /help.", reply_markup=foreman_menu())
    else:
        await message.answer("Доступ только по ссылке-приглашению от шефа. Нажмите /start после перехода по ссылке.")


@router.callback_query()
async def stale_callback(cb: CallbackQuery):
    await cb.answer("Кнопка устарела. Откройте меню заново (/menu).", show_alert=True)
