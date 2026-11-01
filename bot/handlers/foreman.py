from __future__ import annotations

import asyncio

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import Config
from bot.db import ACTIVE, Database
from bot.filters import IsActiveForeman
from bot.keyboards import (
    BTN_MY,
    BTN_MYSTATS,
    MENU_BUTTONS,
    chief_actions_kb,
    foreman_done_kb,
    foreman_list_kb,
    report_kb,
)
from bot.notify import safe_edit, safe_send, send_report, send_task
from bot.states import ReportDone
from bot.texts import PRIORITY_LABEL, esc, foreman_header, report_header, stat_block, task_line

router = Router()
MAX_REPORT_PHOTOS = 10    # лимит Telegram на один альбом
MAX_CAPTION = 1000        # описание отчёта
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


def _proof_text(task_id: int, data: dict) -> str:
    photos = len(data.get("items") or [])
    caption = data.get("caption") or ""
    lines = [
        f"📸 <b>Отчёт по задаче #{task_id}</b>",
        f"Пришлите фото того, что сделали (до {MAX_REPORT_PHOTOS}). Описание — подписью к фото или отдельным сообщением.",
        "",
        f"Фото: {photos} · Описание: {'есть' if caption else 'нет'}",
    ]
    if caption:
        lines.append(f"📝 {esc(caption[:100])}{'…' if len(caption) > 100 else ''}")
    lines.append("\nКогда всё готово — нажмите кнопку ниже.")
    return "\n".join(lines)


async def _refresh_prompt(bot: Bot, chat_id: int, data: dict) -> None:
    """Обновляем одно и то же сообщение со счётчиком, а не отвечаем на каждое фото."""
    if not data.get("prompt_id"):
        return
    try:
        await bot.edit_message_text(
            _proof_text(data["task_id"], data), chat_id=chat_id, message_id=data["prompt_id"],
            reply_markup=report_kb(len(data.get("items") or [])),
        )
    except TelegramBadRequest:
        pass  # «message is not modified» и подобное — не страшно


@router.callback_query(F.data.startswith("fd:"))
async def report_start(cb: CallbackQuery, state: FSMContext, db: Database):
    """«Сделал»: просим фото результата. Статус меняется, только когда отчёт отправлен шефу."""
    t = await db.get_task(int(cb.data.split(":")[1]))
    if not t or t["foreman_id"] != cb.from_user.id:
        return await cb.answer("Задача не найдена", show_alert=True)
    if t["status"] not in ACTIVE:
        note = "Эта задача уже отмечена — ждёт одобрения шефа" if t["status"] == "reported" else "Эта задача уже закрыта"
        return await cb.answer(note, show_alert=True)
    data = {"task_id": t["id"], "items": [], "caption": "", "group": None}
    await state.set_state(ReportDone.proof)
    sent = await cb.message.answer(_proof_text(t["id"], data), reply_markup=report_kb(0))
    await state.update_data(**data, prompt_id=sent.message_id)
    await cb.answer()


@router.message(ReportDone.proof, F.photo)
async def report_photo(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    items = data.get("items") or []
    group = message.media_group_id
    same_album = bool(group) and group == data.get("group")
    if len(items) >= MAX_REPORT_PHOTOS:
        if not same_album:  # хвост того же альбома молча игнорируем
            await message.answer(f"Максимум {MAX_REPORT_PHOTOS} фото в одном отчёте. Нажмите «Отправить шефу».")
        return
    sizes = message.photo  # по возрастанию размера: [2] ≈ 800px — превью для дашборда, [-1] — оригинал
    items = sorted(
        [*items, {"kind": "photo", "file_id": sizes[-1].file_id, "thumb_id": sizes[min(2, len(sizes) - 1)].file_id,
                  "mid": message.message_id}],
        key=lambda i: i["mid"],
    )
    caption = data.get("caption") or ""
    new = (message.caption or "").strip()
    if new:  # у альбома подпись одна; у отдельных фото подписи складываем
        caption = new if not caption else (caption if same_album else f"{caption}\n{new}")
    data = {**data, "items": items, "caption": caption[:MAX_CAPTION], "group": group or data.get("group")}
    await state.update_data(items=items, caption=data["caption"], group=data["group"])
    await _refresh_prompt(bot, message.chat.id, data)


@router.message(ReportDone.proof, F.text, ~F.text.in_(MENU_BUTTONS), ~F.text.startswith("/"))
async def report_text(message: Message, state: FSMContext, bot: Bot):
    """Описание отдельным сообщением (заменяет прежнее)."""
    data = await state.get_data()
    data["caption"] = message.text.strip()[:MAX_CAPTION]
    await state.update_data(caption=data["caption"])
    await _refresh_prompt(bot, message.chat.id, data)


@router.message(ReportDone.proof, ~F.text.in_(MENU_BUTTONS))
async def report_other(message: Message):
    await message.answer("Пришлите фото или текст-описание. Видео и файлы в отчёт пока не добавляются.")


@router.callback_query(ReportDone.proof, F.data == "fr_send")
async def report_send(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot):
    data = await state.get_data()
    await state.clear()
    task_id = data.get("task_id")
    if not task_id:
        return await cb.answer("Отчёт устарел, нажмите «Сделал» заново", show_alert=True)
    items = [{k: v for k, v in it.items() if k != "mid"} for it in data.get("items") or []]
    ok, report_id = await db.submit_report(task_id, cb.from_user.id, data.get("caption") or "", items)
    if not ok:
        await safe_edit(cb.message, f"Задача #{task_id} уже закрыта или отмечена — отчёт не отправлен.")
        return await cb.answer()

    t = await db.get_task(task_id)
    report = await db.get_report(report_id) if report_id else None
    delivered = await send_report(
        bot, t["chief_id"], t, report, report_header(t), chief_actions_kb(task_id, reported=True)
    )
    tail = "Ждёт подтверждения шефа." if delivered else "Шефу не удалось доставить сообщение — он увидит задачу в дашборде."
    await safe_edit(cb.message, f"☑️ Задача #{task_id} отмечена как выполненная. {tail}")
    await cb.answer("Отправлено шефу" if delivered else "Сохранено")


@router.callback_query(ReportDone.proof, F.data == "fr_cancel")
async def report_cancel(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    await safe_edit(cb.message, f"Отчёт отменён. Задача #{data.get('task_id', '')} осталась в работе — отметить её можно через «📋 Мои задачи».")
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
