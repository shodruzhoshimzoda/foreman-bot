from __future__ import annotations

import html

from bot.utils import fmt_hours, fmt_local, fmt_short_date, utcnow

STATUS_LABEL = {
    "new": "🔧 В работе",
    "done": "✅ Выполнена",
    "failed": "❌ Не выполнена",
    "cancelled": "🚫 Отменена",
    "reported": "☑️ Сделано, ждёт одобрения",
}
STATUS_ICON = {"new": "🔧", "done": "✅", "failed": "❌", "cancelled": "🚫", "reported": "☑️"}

PRIORITY_LABEL = {"normal": "🟢 Обычная", "high": "🟡 Важная", "urgent": "🔴 Срочная"}
# срок выполнения по важности (должен совпадать с DUE_SQL в db.py)
PRIORITY_DUE = {"normal": "1 месяц", "high": "7 дней", "urgent": "1 день"}
PRIORITY_ICON = {"normal": "🟢", "high": "🟡", "urgent": "🔴"}

KIND_LABEL = {
    "text": "💬 Сообщение",
    "photo": "📷 Фото",
    "voice": "🎤 Голосовое",
    "video": "🎥 Видео",
    "document": "📎 Файл",
}

PERIOD_LABEL = {7: "7 дней", 30: "30 дней", 0: "всё время"}


def esc(s: str | None) -> str:
    return html.escape(s or "")


def short_name(name: str, limit: int = 16) -> str:
    return name if len(name) <= limit else name[: limit - 1] + "…"


def album_items(t) -> list:
    """Вложения задачи-альбома (несколько фото/видео); для обычной задачи — пустой список."""
    try:
        media = t["media"]
    except (KeyError, IndexError):
        return []
    return list(media) if media and len(media) > 1 else []


def album_summary(items: list) -> str:
    """«📷 Фото: 3 · 🎥 Видео: 1» — сколько чего в альбоме."""
    photos = sum(1 for i in items if i["kind"] == "photo")
    videos = len(items) - photos
    parts = ([f"📷 Фото: {photos}"] if photos else []) + ([f"🎥 Видео: {videos}"] if videos else [])
    return " · ".join(parts)


def preview(t, limit: int = 40) -> str:
    """Короткое описание задачи для списков."""
    txt = " ".join((t["text"] or "").split())
    if len(txt) > limit:
        txt = txt[: limit - 1] + "…"
    if t["kind"] == "text":
        return txt or "(пусто)"
    label = KIND_LABEL.get(t["kind"], "📎 Файл")
    n = len(album_items(t))
    if n:
        label += f" ×{n}"
    return f"{label}: {txt}" if txt else label


def _field(t, key):
    """Поле задачи или None — у старых записей и в тестах колонки может не быть."""
    try:
        return t[key]
    except (KeyError, IndexError):
        return None


def due_line(t, tz: str) -> str | None:
    """«⏰ Срок: до 23.10 14:51» (у просроченной задачи в работе — с пометкой)."""
    due = _field(t, "due_at")
    if not due:
        return None
    line = f"⏰ Срок: до {fmt_local(due, tz)}"
    if t["status"] == "new" and due < utcnow():
        line += " — 🔥 просрочена"
    return line


def foreman_header(t, new: bool = False, tz: str | None = None) -> str:
    title = "Новая задача" if new else "Задача"
    head = f"📌 <b>{title} #{t['id']}</b> · {PRIORITY_LABEL.get(t['priority'], t['priority'])}"
    due = due_line(t, tz) if tz else None
    return f"{head}\n{due}" if due else head


def chief_header(t, tz: str) -> str:
    lines = [
        f"<b>Задача #{t['id']}</b> · 👷 {esc(t['foreman_name'])}",
        f"{PRIORITY_LABEL.get(t['priority'], t['priority'])} · {STATUS_LABEL.get(t['status'], t['status'])}",
        f"🗓 Отправлена: {fmt_local(t['created_at'], tz)}",
    ]
    due = due_line(t, tz)
    if due:
        lines.append(due)
    accepted = _field(t, "accepted_at")
    if accepted:
        lines.append(f"👍 Принял: {fmt_local(accepted, tz)}")
    elif t["status"] == "new":
        lines.append("👀 Ещё не принял")
    reported = _field(t, "reported_at")
    if t["status"] == "reported" and reported:
        lines.append(f"☑️ Прораб отметил: {fmt_local(reported, tz)}")
    if t["closed_at"]:
        lines.append(f"🏁 Закрыта: {fmt_local(t['closed_at'], tz)}")
    return "\n".join(lines)


def task_line(t, tz: str) -> str:
    """Короткая строка для истории задач."""
    return f"{STATUS_ICON.get(t['status'], '•')} #{t['id']} {esc(preview(t))} — {fmt_short_date(t['created_at'], tz)}"


DIGEST_MAX_TASKS = 15  # строк с задачами в одной сводке прораба


def foreman_digest(tasks: list, now_local: str, tz: str) -> str | None:
    """Ежедневная сводка прорабу: что в работе, сроки, что ждёт одобрения. None — если показывать нечего."""
    if not tasks:
        return None
    active = [t for t in tasks if t["status"] == "new"]
    waiting = [t for t in tasks if t["status"] == "reported"]
    now = utcnow()
    late = sum(1 for t in active if t["due_at"] and t["due_at"] < now)
    fresh = sum(1 for t in active if not t["accepted_at"])

    lines = [f"☀️ <b>Ваши задачи на {now_local}</b>", ""]
    head = f"🔧 В работе: {len(active)}"
    if late:
        head += f" · 🔥 просрочено: {late}"
    lines.append(head)
    if fresh:
        lines.append(f"👀 Не принято: {fresh}")
    if waiting:
        lines.append(f"☑️ Ждут одобрения шефа: {len(waiting)}")
    lines.append("")

    for t in active[:DIGEST_MAX_TASKS]:
        row = f"{PRIORITY_ICON.get(t['priority'], '•')} #{t['id']} {esc(preview(t, 40))}"
        if t["due_at"]:
            row += f" · до {fmt_short_date(t['due_at'], tz)} {fmt_local(t['due_at'], tz)[-5:]}" + (" 🔥" if t["due_at"] < now else "")
        if not t["accepted_at"]:
            row += " · 👀"
        lines.append(row)
    if len(active) > DIGEST_MAX_TASKS:
        lines.append(f"…и ещё {len(active) - DIGEST_MAX_TASKS}")
    lines.append("\nОткрыть задачу и отметить «Сделал»: «📋 Мои задачи».")
    return "\n".join(lines)


def _pct(num: float, den: float) -> str:
    return f"{num / den * 100:.0f}%" if den else "—"


def stat_block(r, with_name: bool = True) -> str:
    closed = r["done"] + r["failed"]
    lines = []
    if with_name:
        lines.append(f"👷 <b>{esc(r['full_name'])}</b>")
    if r["total"] == 0:
        lines.append("   задач за период не было")
        return "\n".join(lines)
    counts = f"   Всего: {r['total']} · ✅ {r['done']} · ❌ {r['failed']} · 🔧 {r['active']}"
    if r["reported"]:
        counts += f" · ☑️ {r['reported']}"
    if r["cancelled"]:
        counts += f" · 🚫 {r['cancelled']}"
    lines.append(counts)
    lines.append(f"   Выполнение: {_pct(r['done'], closed)} · Среднее время: {fmt_hours(r['avg_hours'])}")
    return "\n".join(lines)


def total_block(rows) -> str:
    keys = ("total", "done", "failed", "cancelled", "active", "reported")
    s = {k: sum(r[k] for r in rows) for k in keys}
    done_rows = [r for r in rows if r["avg_hours"] is not None and r["done"]]
    avg = (
        sum(r["avg_hours"] * r["done"] for r in done_rows) / sum(r["done"] for r in done_rows)
        if done_rows
        else None
    )
    s.update(full_name="ИТОГО", avg_hours=avg)
    return stat_block(s).replace("👷 <b>ИТОГО</b>", "🧮 <b>ИТОГО по участку</b>")
