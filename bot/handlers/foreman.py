from __future__ import annotations

import asyncio

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import Config
from bot.db import ACTIVE, Database
from bot.filters import IsActiveForeman
from bot.keyboards import BTN_MY, BTN_MYSTATS, chief_actions_kb, foreman_done_kb, foreman_list_kb
from bot.notify import drop_keyboard, safe_edit, safe_send, send_task
from bot.texts import PRIORITY_LABEL, esc, foreman_header, stat_block, task_line

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
async def view_task(cb: CallbackQuery, db: Database, bot: Bot, config: Config):
    t = await db.get_task(int(cb.data.split(":")[1]))
    if not t or t["foreman_id"] != cb.from_user.id:
        return await cb.answer("Задача не найдена", show_alert=True)
    if t["status"] not in ACTIVE:
        text, kb = await _render_list(db, cb.from_user.id)
        await safe_edit(cb.message, text, kb)
        note = "Вы уже отметили эту задачу — ждёт одобрения шефа" if t["status"] == "reported" else "Эта задача уже закрыта шефом"
        return await cb.answer(note, show_alert=True)
    await send_task(
        bot, cb.from_user.id, t, foreman_header(t, tz=config.tz),
        foreman_done_kb(t["id"], accepted=bool(t["accepted_at"])), kb_prompt="Примите задачу и отметьте, когда сделаете:",
    )
    await cb.answer()


@router.callback_query(F.data.startswith("fa:"))
async def accept_task(cb: CallbackQuery, db: Database, bot: Bot):
    """Прораб нажал «Принял»: шеф видит, что задачу заметили и взяли."""
    t = await db.get_task(int(cb.data.split(":")[1]))
    if not t or t["foreman_id"] != cb.from_user.id:
        return await cb.answer("Задача не найдена", show_alert=True)
    if not await db.accept(t["id"], cb.from_user.id):
        # уже принята (двойной клик) или закрыта — просто приводим кнопки в порядок
        try:
            await cb.message.edit_reply_markup(
                reply_markup=foreman_done_kb(t["id"], accepted=True) if t["status"] == "new" else None
            )
        except TelegramAPIError:
            pass
        return await cb.answer("Задача уже принята" if t["status"] == "new" else "Задача уже не в работе")
    try:
        await cb.message.edit_reply_markup(reply_markup=foreman_done_kb(t["id"], accepted=True))
    except TelegramAPIError:
        pass
    await cb.answer("Принято 👍")
    await safe_send(
        bot, t["chief_id"],
        f"👍 <b>{esc(t['foreman_name'])}</b> принял(а) задачу <b>#{t['id']}</b>\n{PRIORITY_LABEL.get(t['priority'], t['priority'])}",
    )


@router.callback_query(F.data.startswith("fd:"))
async def report_done(cb: CallbackQuery, db: Database, bot: Bot):
    """Прораб нажал «Сделал»: задача отмечена выполненной, но ждёт одобрения шефа."""
    t = await db.get_task(int(cb.data.split(":")[1]))
    if not t or t["foreman_id"] != cb.from_user.id:
        return await cb.answer("Задача не найдена", show_alert=True)
    if not await db.report_done(t["id"], cb.from_user.id):
        await drop_keyboard(cb.message)
        return await cb.answer("Эта задача уже отмечена или закрыта", show_alert=True)
    await drop_keyboard(cb.message)
    await cb.message.answer(f"☑️ Задача #{t['id']} отмечена как выполненная. Ждёт подтверждения шефа.")
    await cb.answer("Отправлено шефу")

    t = await db.get_task(t["id"])
    await safe_send(
        bot, t["chief_id"],
        f"☑️ <b>{esc(t['foreman_name'])}</b> отметил(а) задачу <b>#{t['id']}</b> как выполненную\n"
        f"{PRIORITY_LABEL.get(t['priority'], t['priority'])}\n\nОдобрить?",
        chief_actions_kb(t["id"], reported=True),
    )


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
