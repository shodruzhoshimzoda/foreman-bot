from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.texts import PERIOD_LABEL, PRIORITY_ICON, PRIORITY_LABEL, preview, short_name

# ---- кнопки главного меню ----
BTN_NEW = "➕ Новая задача"
BTN_ACTIVE = "📋 Активные задачи"
BTN_STATS = "📊 Статистика"
BTN_TEAM = "👷 Прорабы"

BTN_MY = "📋 Мои задачи"
BTN_MYSTATS = "📈 Моя статистика"

MENU_BUTTONS = (BTN_NEW, BTN_ACTIVE, BTN_STATS, BTN_TEAM, BTN_MY, BTN_MYSTATS)


def chief_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_NEW)],
            [KeyboardButton(text=BTN_ACTIVE)],
            [KeyboardButton(text=BTN_STATS), KeyboardButton(text=BTN_TEAM)],
        ],
        resize_keyboard=True,
    )


def foreman_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_MY), KeyboardButton(text=BTN_MYSTATS)]],
        resize_keyboard=True,
    )


def _kb(b: InlineKeyboardBuilder) -> InlineKeyboardMarkup:
    return b.as_markup()


# ---- создание задачи ----
def cancel_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✖️ Отмена", callback_data="nt_cancel")
    return _kb(b)


def priority_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for code, label in PRIORITY_LABEL.items():
        b.button(text=label, callback_data=f"nt_pr:{code}")
    b.adjust(3)
    b.row(InlineKeyboardButton(text="✖️ Отмена", callback_data="nt_cancel"))
    return _kb(b)


def foremen_pick_kb(foremen, selected: set[int]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for f in foremen:
        mark = "☑️" if f["tg_id"] in selected else "⬜️"
        b.button(text=f"{mark} {short_name(f['full_name'], 28)}", callback_data=f"nt_f:{f['tg_id']}")
    b.adjust(1)
    n = len(selected)
    b.row(InlineKeyboardButton(text=f"📤 Отправить выбранным ({n})" if n else "📤 Отправить выбранным", callback_data="nt_send"))
    b.row(InlineKeyboardButton(text="👥 Отправить всем", callback_data="nt_sendall"))
    b.row(InlineKeyboardButton(text="✖️ Отмена", callback_data="nt_cancel"))
    return _kb(b)


# ---- отметка результата шефом ----
def chief_actions_kb(task_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Выполнено", callback_data=f"ct_done:{task_id}")
    b.button(text="❌ Не выполнено", callback_data=f"ct_fail:{task_id}")
    b.button(text="🚫 Отменить задачу", callback_data=f"ct_cancel:{task_id}")
    b.adjust(2, 1)
    return _kb(b)


def task_list_kb(tasks) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for t in tasks:
        text = f"{PRIORITY_ICON.get(t['priority'], '•')} #{t['id']} · {short_name(t['foreman_name'], 12)} · {preview(t, 24)}"
        b.button(text=text, callback_data=f"ct_view:{t['id']}")
    b.adjust(1)
    return _kb(b)


def foreman_list_kb(tasks) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for t in tasks:
        b.button(text=f"{PRIORITY_ICON.get(t['priority'], '•')} #{t['id']} · {preview(t, 34)}", callback_data=f"fv:{t['id']}")
    b.adjust(1)
    return _kb(b)


# ---- статистика ----
def dashboard_btn(url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text="📱 Открыть дашборд", web_app=WebAppInfo(url=url))


def dashboard_kb(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[dashboard_btn(url)]])


def stats_kb(rows, days: int, webapp_url: str = "") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for d, label in PERIOD_LABEL.items():
        b.button(text=("• " if d == days else "") + label, callback_data=f"st:{d}")
    b.adjust(3)
    for r in rows:
        b.row(
            InlineKeyboardButton(
                text=f"🔎 {short_name(r['full_name'], 22)}", callback_data=f"stf:{r['tg_id']}:{days}"
            )
        )
    b.row(InlineKeyboardButton(text="📥 Экспорт CSV", callback_data=f"stx:{days}"))
    if webapp_url:
        b.row(dashboard_btn(webapp_url))
    return _kb(b)


def stats_back_kb(days: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="⬅️ К сводке", callback_data=f"st:{days}")
    return _kb(b)


# ---- прорабы ----
def approve_kb(foreman_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Принять", callback_data=f"fm_ok:{foreman_id}")
    b.button(text="❌ Отклонить", callback_data=f"fm_no:{foreman_id}")
    b.adjust(2)
    return _kb(b)


def team_kb(active, pending) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for p in pending:
        b.row(
            InlineKeyboardButton(text=f"✅ {short_name(p['full_name'], 18)}", callback_data=f"fm_ok:{p['tg_id']}"),
            InlineKeyboardButton(text="❌", callback_data=f"fm_no:{p['tg_id']}"),
        )
    for a in active:
        b.row(InlineKeyboardButton(text=f"🚫 Отключить: {short_name(a['full_name'], 20)}", callback_data=f"fm_blk:{a['tg_id']}"))
    return _kb(b)
