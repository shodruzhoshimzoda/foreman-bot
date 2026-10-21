from __future__ import annotations

import asyncio

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import Config
from bot.db import ACTIVE, Database
from bot.filters import IsActiveForeman
from bot.keyboards import BTN_MY, BTN_MYSTATS, foreman_list_kb
from bot.notify import safe_edit, send_task
from bot.texts import foreman_header, stat_block, task_line

router = Router()
router.message.filter(IsActiveForeman())
router.callback_query.filter(IsActiveForeman())


async def _render_list(db: Database, foreman_id: int):
    tasks = await db.list_tasks(foreman_id=foreman_id, statuses=ACTIVE, limit=30)
    if not tasks:
        return "Задач в работе нет. 👍", None
    text = f"📋 <b>Ваши задачи в работе</b> ({len(tasks)})\nНажмите на задачу, чтобы открыть её."
    return text, foreman_list_kb(tasks)


@router.message(F.text == BTN_MY)
async def my_tasks(message: Message, state: FSMContext, db: Database):
    """Панель прораба: все накопившиеся задачи в работе."""
    await state.clear()
    text, kb = await _render_list(db, message.from_user.id)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("fv:"))
async def view_task(cb: CallbackQuery, db: Database, bot: Bot):
    t = await db.get_task(int(cb.data.split(":")[1]))
    if not t or t["foreman_id"] != cb.from_user.id:
        return await cb.answer("Задача не найдена", show_alert=True)
    if t["status"] not in ACTIVE:
        text, kb = await _render_list(db, cb.from_user.id)
        await safe_edit(cb.message, text, kb)
        return await cb.answer("Эта задача уже закрыта шефом", show_alert=True)
    await send_task(bot, cb.from_user.id, t, foreman_header(t))
    await cb.answer()


@router.message(F.text == BTN_MYSTATS)
async def my_stats(message: Message, state: FSMContext, db: Database, config: Config):
    await state.clear()
    uid = message.from_user.id
    month, total, recent = await asyncio.gather(
        db.stats(foreman_id=uid, days=30),
        db.stats(foreman_id=uid, days=None),
        db.recent_tasks(uid, None, limit=10),
    )

    text = "📈 <b>Ваша статистика</b>\n\n<b>За 30 дней</b>\n" + stat_block(month[0], with_name=False)
    text += "\n\n<b>За всё время</b>\n" + stat_block(total[0], with_name=False)
    if recent:
        text += "\n\n<b>Последние задачи:</b>\n" + "\n".join(task_line(t, config.tz) for t in recent)
    await message.answer(text)
