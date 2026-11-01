from __future__ import annotations

import asyncio
import csv
import io

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from bot.config import Config
from bot.db import OPEN, Database
from bot.filters import IsChief
from bot.keyboards import (
    dashboard_kb,
    BTN_ACTIVE,
    BTN_NEW,
    BTN_STATS,
    BTN_TEAM,
    MENU_BUTTONS,
    approve_kb,
    cancel_kb,
    chief_actions_kb,
    foremen_pick_kb,
    foreman_done_kb,
    foreman_menu,
    priority_kb,
    stats_back_kb,
    stats_kb,
    task_list_kb,
    team_kb,
)
from bot.notify import drop_keyboard, safe_edit, safe_send, send_report, send_task
from bot.states import NewTask
from bot.texts import (
    album_summary,
    KIND_LABEL,
    PERIOD_LABEL,
    PRIORITY_DUE,
    PRIORITY_LABEL,
    STATUS_ICON,
    STATUS_LABEL,
    chief_header,
    esc,
    foreman_header,
    preview,
    stat_block,
    task_line,
    total_block,
)
from bot.utils import fmt_local

router = Router()
router.message.filter(IsChief())
router.callback_query.filter(IsChief())

MAX_TEXT = 3000
ALBUM_KINDS = ("photo", "video")   # эти вложения можно присылать несколькими штуками
MAX_ALBUM = 10                     # лимит Telegram на один альбом


def extract_content(message: Message):
    """Что прислал шеф: (вид, file_id, текст, превью, длительность) или None, если тип не поддерживается."""
    text = (message.text or message.caption or "").strip()
    if message.photo:
        # размеры идут по возрастанию: [2] ≈ 800px — для карточки в дашборде, [-1] — оригинал (до 1280px)
        sizes = message.photo
        thumb = sizes[min(2, len(sizes) - 1)]
        return "photo", sizes[-1].file_id, text, thumb.file_id, None
    if message.voice:
        return "voice", message.voice.file_id, text, None, message.voice.duration
    if message.video:
        return "video", message.video.file_id, text, None, message.video.duration
    if message.document:
        return "document", message.document.file_id, text, None, None
    if message.text:
        return "text", None, text, None, None
    return None


async def _own_task(db: Database, task_id: int, chief_id: int):
    t = await db.get_task(task_id)
    return t if t and t["chief_id"] == chief_id else None


# =====================================================================
# Новая задача: содержимое -> важность -> прорабы -> отправка
# =====================================================================
@router.message(F.text == BTN_NEW)
async def new_task(message: Message, state: FSMContext, db: Database):
    await state.clear()
    if not await db.list_foremen(message.from_user.id, "active"):
        await message.answer(
            "У вас пока нет прорабов. Откройте «👷 Прорабы», отправьте им ссылку-приглашение и подтвердите заявки."
        )
        return
    await state.set_state(NewTask.content)
    await message.answer(
        "Отправьте задачу — <b>текстом, фото или голосовым</b> (к фото можно добавить подпись).",
        reply_markup=cancel_kb(),
    )


def _item(kind: str, file_id: str, thumb_id: str | None, duration: int | None, mid: int) -> dict:
    return {"kind": kind, "file_id": file_id, "thumb_id": thumb_id, "duration": duration, "mid": mid}


def _prompt_text(kind: str, items: list) -> str:
    """Подсказка шагу «важность»: для фото/видео показывает, сколько вложений уже принято."""
    if kind not in ALBUM_KINDS:
        return f"{KIND_LABEL[kind]} принято. Выберите <b>важность</b>:"
    head = f"{KIND_LABEL[kind]} принято." if len(items) <= 1 else f"Принято — {album_summary(items)}"
    more = "\n<i>Можно добавить ещё — просто отправьте их.</i>" if len(items) < MAX_ALBUM else ""
    return f"{head}{more}\nВыберите <b>важность</b>:"


@router.message(NewTask.content, ~F.text.in_(MENU_BUTTONS))
async def nt_content(message: Message, state: FSMContext):
    data = extract_content(message)
    if data is None:
        return await message.answer("Этот тип сообщения не поддерживается. Отправьте текст, фото или голосовое.")
    kind, file_id, text, thumb_id, duration = data
    if len(text) > MAX_TEXT:
        return await message.answer(f"Слишком длинный текст (максимум {MAX_TEXT} символов). Сократите его.")
    items = [_item(kind, file_id, thumb_id, duration, message.message_id)] if kind in ALBUM_KINDS else []
    await state.update_data(
        kind=kind, file_id=file_id, text=text, thumb_id=thumb_id, duration=duration,
        items=items, group=message.media_group_id,
    )
    await state.set_state(NewTask.priority)
    sent = await message.answer(_prompt_text(kind, items), reply_markup=priority_kb())
    await state.update_data(prompt_id=sent.message_id)


@router.message(StateFilter(NewTask.priority, NewTask.foremen), ~F.text.in_(MENU_BUTTONS))
async def nt_stray(message: Message, state: FSMContext):
    """Ещё фото/видео после первого: дописываем в ту же задачу (альбом или пересылка по одному)."""
    data = await state.get_data()
    items = data.get("items") or []
    extra = extract_content(message)
    on_priority = await state.get_state() == NewTask.priority.state
    same_album = bool(message.media_group_id) and message.media_group_id == data.get("group")

    if items and extra and extra[0] in ALBUM_KINDS and (on_priority or same_album):
        if len(items) < MAX_ALBUM:
            kind, file_id, text, thumb_id, duration = extra
            items = sorted([*items, _item(kind, file_id, thumb_id, duration, message.message_id)], key=lambda i: i["mid"])
            first = items[0]  # поля задачи описывают первое вложение (для превью и старых запросов)
            await state.update_data(
                items=items, kind=first["kind"], file_id=first["file_id"], thumb_id=first["thumb_id"],
                duration=first["duration"], text=data.get("text") or text[:MAX_TEXT],
            )
            if on_priority and data.get("prompt_id"):
                try:  # обновляем счётчик в одном и том же сообщении, а не отвечаем на каждое фото
                    await message.bot.edit_message_text(
                        _prompt_text(first["kind"], items), chat_id=message.chat.id,
                        message_id=data["prompt_id"], reply_markup=priority_kb(),
                    )
                except TelegramBadRequest:
                    pass
        return
    if same_album:  # хвост альбома, который уже не принимаем (например, голосовое в альбоме) — без шума
        return
    await message.answer("Задача уже принята. Нажмите кнопку выше или /cancel, чтобы начать заново.")


@router.callback_query(NewTask.priority, F.data.startswith("nt_pr:"))
async def nt_priority(cb: CallbackQuery, state: FSMContext, db: Database):
    code = cb.data.split(":")[1]
    if code not in PRIORITY_LABEL:
        return await cb.answer()
    foremen = await db.list_foremen(cb.from_user.id, "active")
    if not foremen:
        await state.clear()
        await safe_edit(cb.message, "Нет активных прорабов.")
        return await cb.answer()
    pick = [{"tg_id": f["tg_id"], "full_name": f["full_name"]} for f in foremen]
    await state.update_data(priority=code, selected=[], foremen=pick)
    await state.set_state(NewTask.foremen)
    await safe_edit(cb.message, f"Важность: {PRIORITY_LABEL[code]}")
    await cb.message.answer("Кому отправить?", reply_markup=foremen_pick_kb(foremen, set()))
    await cb.answer()


@router.callback_query(NewTask.foremen, F.data.startswith("nt_f:"))
async def nt_toggle(cb: CallbackQuery, state: FSMContext):
    fid = int(cb.data.split(":")[1])
    data = await state.get_data()
    selected = set(data.get("selected", []))
    selected ^= {fid}
    await state.update_data(selected=list(selected))
    await cb.message.edit_reply_markup(reply_markup=foremen_pick_kb(data.get("foremen", []), selected))
    await cb.answer()


@router.callback_query(F.data == "nt_cancel")
async def nt_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_edit(cb.message, "Создание задачи отменено.")
    await cb.answer()


async def _deliver(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, config: Config, to_all: bool):
    data = await state.get_data()
    chief_id = cb.from_user.id
    active = {f["tg_id"]: f for f in await db.list_foremen(chief_id, "active")}
    ids = list(active) if to_all else [i for i in data.get("selected", []) if i in active]
    if not ids:
        return await cb.answer("Выберите хотя бы одного прораба", show_alert=True)
    await state.clear()
    items = data.get("items") or []
    media = [{k: v for k, v in i.items() if k != "mid"} for i in items] if len(items) > 1 else None

    # одна вставка на всех прорабов, затем рассылка параллельно (лимит Telegram — ~30 сообщений/с)
    tasks = await db.create_tasks(
        chief_id, ids, data["kind"], data.get("file_id"), data.get("text", ""), data["priority"],
        thumb_id=data.get("thumb_id"), duration=data.get("duration"), media=media,
    )
    sem = asyncio.Semaphore(10)

    async def _send(task) -> bool:
        async with sem:
            return await send_task(
                bot, task["foreman_id"], task, foreman_header(task, new=True, tz=config.tz),
                foreman_done_kb(task["id"]), kb_prompt="Примите задачу и отметьте, когда сделаете:",
            )

    results = await asyncio.gather(*(_send(t) for t in tasks))
    delivered = [esc(t["foreman_name"]) for t, ok in zip(tasks, results) if ok]
    failed = [esc(t["foreman_name"]) for t, ok in zip(tasks, results) if not ok]

    text = f"✅ <b>Задача отправлена</b> · {PRIORITY_LABEL[data['priority']]} · срок {PRIORITY_DUE[data['priority']]}"
    if media:
        text += f"\n{album_summary(items)}"
    if delivered:
        text += "\n👷 " + ", ".join(delivered)
    if failed:
        text += (
            "\n\n⚠️ Не удалось доставить: " + ", ".join(failed)
            + "\nПрораб, возможно, заблокировал бота. Задача сохранена и видна в «Активных задачах»."
        )
    await safe_edit(cb.message, text)
    await cb.answer()


@router.callback_query(NewTask.foremen, F.data == "nt_send")
async def nt_send(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, config: Config):
    await _deliver(cb, state, db, bot, config, to_all=False)


@router.callback_query(NewTask.foremen, F.data == "nt_sendall")
async def nt_send_all(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot, config: Config):
    await _deliver(cb, state, db, bot, config, to_all=True)


# =====================================================================
# Активные задачи: шеф сам отмечает результат
# =====================================================================
async def _render_list(db: Database, chief_id: int):
    tasks = await db.list_tasks(chief_id=chief_id, statuses=OPEN, limit=30)
    if not tasks:
        return "Активных задач нет. 🎉", None
    waiting = sum(1 for t in tasks if t["status"] == "reported")
    text = f"📋 <b>Активные задачи</b> ({len(tasks)})\nНажмите на задачу, чтобы открыть её и отметить результат."
    if waiting:
        text += f"\n☑️ — прораб отметил «сделал», ждёт вашего одобрения: {waiting}"
    return text, task_list_kb(tasks)


@router.message(F.text == BTN_ACTIVE)
async def show_active(message: Message, state: FSMContext, db: Database):
    await state.clear()
    text, kb = await _render_list(db, message.from_user.id)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("ct_view:"))
async def cb_view(cb: CallbackQuery, db: Database, bot: Bot, config: Config):
    t = await _own_task(db, int(cb.data.split(":")[1]), cb.from_user.id)
    if not t:
        return await cb.answer("Задача не найдена", show_alert=True)
    if t["status"] not in OPEN:
        text, kb = await _render_list(db, cb.from_user.id)
        await safe_edit(cb.message, text, kb)
        return await cb.answer("Эта задача уже закрыта", show_alert=True)
    await send_task(
        bot, cb.from_user.id, t, chief_header(t, config.tz), chief_actions_kb(t["id"], reported=t["status"] == "reported")
    )
    if t["status"] == "reported":  # то, что прораб прислал как результат, — следом, без кнопок
        reports = await db.reports_for_task(t["id"])
        if reports:
            last = reports[-1]
            await send_report(bot, cb.from_user.id, t, last, f"📸 <b>Отчёт прораба</b> · {fmt_local(last['created_at'], config.tz)}")
    await cb.answer()


async def _close(cb: CallbackQuery, db: Database, status: str, toast: str):
    t = await _own_task(db, int(cb.data.split(":")[1]), cb.from_user.id)
    if not t:
        return await cb.answer("Задача не найдена", show_alert=True)
    if not await db.transition(t["id"], status):
        await drop_keyboard(cb.message)
        return await cb.answer("Статус задачи уже изменён", show_alert=True)
    await drop_keyboard(cb.message)
    await cb.message.answer(
        f"{STATUS_ICON[status]} Задача #{t['id']} · {esc(t['foreman_name'])} — {STATUS_LABEL[status].split(' ', 1)[1].lower()}"
    )
    await cb.answer(toast)


@router.callback_query(F.data.startswith("ct_done:"))
async def ct_done(cb: CallbackQuery, db: Database):
    await _close(cb, db, "done", "Отмечено: выполнено")


@router.callback_query(F.data.startswith("ct_fail:"))
async def ct_fail(cb: CallbackQuery, db: Database):
    await _close(cb, db, "failed", "Отмечено: не выполнено")


@router.callback_query(F.data.startswith("ct_cancel:"))
async def ct_cancel(cb: CallbackQuery, db: Database):
    await _close(cb, db, "cancelled", "Задача отменена")


@router.callback_query(F.data.startswith("ct_reopen:"))
async def ct_reopen(cb: CallbackQuery, db: Database, bot: Bot):
    """Шеф не принял «Сделал» — задача снова в работе у прораба."""
    t = await _own_task(db, int(cb.data.split(":")[1]), cb.from_user.id)
    if not t:
        return await cb.answer("Задача не найдена", show_alert=True)
    if not await db.reopen(t["id"]):
        await drop_keyboard(cb.message)
        return await cb.answer("Статус задачи уже изменён", show_alert=True)
    await drop_keyboard(cb.message)
    await cb.message.answer(f"↩️ Задача #{t['id']} · {esc(t['foreman_name'])} — снова в работе")
    await safe_send(bot, t["foreman_id"], f"↩️ Шеф вернул задачу #{t['id']} в работу — она не принята как выполненная.")
    await cb.answer("Возвращена в работу")


# =====================================================================
# Дашборд (Telegram Mini App)
# =====================================================================
@router.message(Command("dashboard"))
async def cmd_dashboard(message: Message, config: Config):
    if not config.webapp_url:
        return await message.answer("Дашборд не настроен: задайте WEBAPP_URL в .env.")
    await message.answer("📊 Дашборд по участку:", reply_markup=dashboard_kb(config.webapp_url))


# =====================================================================
# Статистика
# =====================================================================
async def _render_stats(db: Database, config: Config, chief_id: int, days: int):
    rows = await db.stats(chief_id=chief_id, days=days or None)
    head = f"📊 <b>Статистика</b> — {PERIOD_LABEL[days]}\n"
    if not rows:
        return head + "\nУ вас пока нет прорабов.", stats_kb([], days, config.webapp_url)
    body = "\n\n".join(stat_block(r) for r in rows) + "\n\n" + total_block(rows)
    text = head + "\n" + body
    if len(text) > 3900:
        text = text[:3850] + "\n…\nПолный отчёт — в экспорте CSV."
    return text, stats_kb(rows, days, config.webapp_url)


@router.message(F.text == BTN_STATS)
async def show_stats(message: Message, state: FSMContext, db: Database, config: Config):
    await state.clear()
    text, kb = await _render_stats(db, config, message.from_user.id, 7)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("st:"))
async def cb_stats(cb: CallbackQuery, db: Database, config: Config):
    days = int(cb.data.split(":")[1])
    if days not in PERIOD_LABEL:
        return await cb.answer()
    text, kb = await _render_stats(db, config, cb.from_user.id, days)
    await safe_edit(cb.message, text, kb)
    await cb.answer()


@router.callback_query(F.data.startswith("stf:"))
async def cb_foreman_stats(cb: CallbackQuery, db: Database, config: Config):
    _, fid, days = cb.data.split(":")
    fid, days = int(fid), int(days)
    foreman = await db.get_user(fid)
    if not foreman or foreman["chief_id"] != cb.from_user.id:
        return await cb.answer("Прораб не найден", show_alert=True)
    rows, recent = await asyncio.gather(
        db.stats(foreman_id=fid, days=days or None),
        db.recent_tasks(fid, days or None, limit=10),
    )
    row = rows[0]
    prio = {"urgent": row["prio_urgent"], "high": row["prio_high"], "normal": row["prio_normal"]}

    lines = [f"🔎 <b>{esc(foreman['full_name'])}</b> — {PERIOD_LABEL[days]}", "", stat_block(row, with_name=False), ""]
    lines.append(
        "По важности: " + " · ".join(f"{PRIORITY_LABEL[p]}: {prio.get(p, 0)}" for p in ("urgent", "high", "normal"))
    )
    if recent:
        lines.append("\n<b>Последние задачи:</b>")
        lines += [task_line(t, config.tz) for t in recent]
    await safe_edit(cb.message, "\n".join(lines), stats_back_kb(days))
    await cb.answer()


@router.callback_query(F.data.startswith("stx:"))
async def cb_export(cb: CallbackQuery, db: Database, config: Config):
    days = int(cb.data.split(":")[1])
    rows = await db.export_rows(cb.from_user.id, days or None)
    if not rows:
        return await cb.answer("За этот период задач нет", show_alert=True)

    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["№", "Прораб", "Тип", "Текст", "Важность", "Статус", "Отправлена", "Закрыта"])
    for t in rows:
        w.writerow(
            [
                t["id"],
                t["foreman_name"],
                KIND_LABEL.get(t["kind"], t["kind"]),
                t["text"],
                PRIORITY_LABEL.get(t["priority"], t["priority"]),
                STATUS_LABEL.get(t["status"], t["status"]),
                fmt_local(t["created_at"], config.tz),
                fmt_local(t["closed_at"], config.tz),
            ]
        )
    data = buf.getvalue().encode("utf-8-sig")  # BOM — чтобы Excel открыл кириллицу
    name = f"tasks_{'all' if not days else str(days) + 'd'}.csv"
    await cb.message.answer_document(BufferedInputFile(data, filename=name), caption=f"Экспорт задач — {PERIOD_LABEL[days]}")
    await cb.answer()


# =====================================================================
# Прорабы: приглашение, заявки, отключение
# =====================================================================
async def _render_team(db: Database, bot: Bot, chief_id: int):
    active = await db.list_foremen(chief_id, "active")
    pending = await db.list_foremen(chief_id, "pending")
    me = await bot.me()
    link = f"https://t.me/{me.username}?start=ref_{chief_id}"

    lines = ["👷 <b>Ваши прорабы</b>"]
    if active:
        lines.append("")
        for a in active:
            lines.append(f"• {esc(a['full_name'])} — задач в работе: {a['active_cnt']}")
    else:
        lines.append("\nПока никого нет.")
    if pending:
        lines.append("\n⏳ <b>Ждут подтверждения:</b>")
        lines += [f"• {esc(p['full_name'])}" for p in pending]
    lines.append(f"\n🔗 Ссылка-приглашение для прорабов:\n{link}")
    return "\n".join(lines), team_kb(active, pending)


@router.message(F.text == BTN_TEAM)
async def show_team(message: Message, state: FSMContext, db: Database, bot: Bot):
    await state.clear()
    text, kb = await _render_team(db, bot, message.from_user.id)
    await message.answer(text, reply_markup=kb, disable_web_page_preview=True)


@router.callback_query(F.data.startswith(("fm_ok:", "fm_no:", "fm_blk:")))
async def cb_manage_foreman(cb: CallbackQuery, db: Database, bot: Bot):
    action, fid = cb.data.split(":")
    fid = int(fid)
    f = await db.get_user(fid)
    if not f or f["role"] != "foreman" or f["chief_id"] != cb.from_user.id:
        return await cb.answer("Прораб не найден", show_alert=True)

    if action == "fm_ok":
        await db.set_user_status(fid, "active")
        try:
            await bot.send_message(
                fid,
                "✅ Шеф подтвердил вашу заявку. Теперь вы будете получать задачи здесь.",
                reply_markup=foreman_menu(),
            )
        except TelegramAPIError:
            pass
        note = f"✅ {esc(f['full_name'])} добавлен(а)."
    elif action == "fm_no":
        await db.delete_user(fid)
        await safe_send(bot, fid, "❌ Шеф отклонил заявку.")
        note = f"❌ Заявка {esc(f['full_name'])} отклонена."
    else:
        await db.set_user_status(fid, "blocked")
        await safe_send(bot, fid, "🚫 Шеф отключил ваш доступ к боту.")
        note = f"🚫 {esc(f['full_name'])} отключён(а). Его прошлые задачи сохранены в статистике."

    # если нажали на кнопку в сообщении «Новый прораб просит доступ» — просто обновим текст
    if cb.message.text and cb.message.text.startswith("👷 Новый прораб"):
        await safe_edit(cb.message, note)
    else:
        text, kb = await _render_team(db, bot, cb.from_user.id)
        await safe_edit(cb.message, note + "\n\n" + text, kb)
    await cb.answer()
