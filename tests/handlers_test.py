"""
Прогон хендлеров бота через настоящий Dispatcher с подменённой сессией Telegram (без сети):

    TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/postgres python -m tests.handlers_test
"""
import asyncio
import os
import uuid
from datetime import datetime

import asyncpg
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import CallbackQuery, Chat, Message, PhotoSize, Update, User, Voice

from bot.config import Config
from bot.db import Database
from bot.main import build_dispatcher

CHIEF, F1, F2, TOKEN = 7_113_457_025, 5_624_300_072, 6_523_328_505, "123456:TEST"


class FakeSession(BaseSession):
    """Ничего не отправляет в сеть; запоминает вызовы и возвращает правдоподобные ответы."""

    def __init__(self):
        super().__init__()
        self.calls: list[TelegramMethod] = []

    async def close(self): ...
    async def stream_content(self, *a, **k): yield b""

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        name = type(method).__name__
        if name == "GetMe":
            return User(id=1, is_bot=True, first_name="bot", username="foreman_test_bot")
        returning = getattr(method, "__returning__", bool)
        if returning is bool:
            return True
        chat_id = getattr(method, "chat_id", CHIEF)
        return Message(message_id=len(self.calls), date=datetime.now(), chat=Chat(id=chat_id, type="private"), text="x")

    def sent(self, name: str):
        return [c for c in self.calls if type(c).__name__ == name]


class Harness:
    def __init__(self, dp, bot, session):
        self.dp, self.bot, self.session, self.uid = dp, bot, session, 0

    def _user(self, uid):
        return User(id=uid, is_bot=False, first_name="U", username=None)

    async def say(self, uid, text):
        self.uid += 1
        msg = Message(message_id=self.uid, date=datetime.now(), chat=Chat(id=uid, type="private"), from_user=self._user(uid), text=text)
        await self.dp.feed_update(self.bot, Update(update_id=self.uid, message=msg))

    async def send(self, uid, **content):
        """Сообщение с произвольным содержимым (фото, голосовое…)."""
        self.uid += 1
        msg = Message(message_id=self.uid, date=datetime.now(), chat=Chat(id=uid, type="private"), from_user=self._user(uid), **content)
        await self.dp.feed_update(self.bot, Update(update_id=self.uid, message=msg))

    async def press(self, uid, data):
        self.uid += 1
        msg = Message(message_id=self.uid, date=datetime.now(), chat=Chat(id=uid, type="private"), text="old", from_user=User(id=1, is_bot=True, first_name="b"))
        cb = CallbackQuery(id=str(self.uid), from_user=self._user(uid), chat_instance="c", message=msg, data=data)
        await self.dp.feed_update(self.bot, Update(update_id=self.uid, callback_query=cb))


async def main() -> None:
    dsn = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("Задайте TEST_DATABASE_URL")
    schema = "h_" + uuid.uuid4().hex[:8]
    db = Database(dsn, schema=schema)
    await db.connect()
    try:
        await run(db, dsn)
    finally:
        await db.close()
        c = await asyncpg.connect(dsn)
        await c.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await c.close()


async def run(db: Database, dsn: str) -> None:
    await db.upsert_chief(CHIEF, "Шеф")
    await db.register_foreman(F1, "Иванов", None, CHIEF)
    await db.register_foreman(F2, "Петров", None, CHIEF)
    await db.set_user_status(F1, "active")
    await db.set_user_status(F2, "active")

    cfg = Config(TOKEN, (CHIEF,), dsn, "Asia/Dushanbe", 8, webapp_url="https://dash.example.com")
    session = FakeSession()
    bot = Bot(TOKEN, session=session)
    h = Harness(build_dispatcher(db, cfg), bot, session)

    # /start шефа: меню + кнопка дашборда
    await h.say(CHIEF, "/start")
    assert session.sent("SetChatMenuButton"), "кнопка дашборда не установлена"
    assert "Вы вошли как" in session.sent("SendMessage")[0].text

    # создание задачи: текст -> важность -> выбор прораба (тумблеры без БД) -> отправка
    await h.say(CHIEF, "➕ Новая задача")
    await h.say(CHIEF, "Залить фундамент")
    await h.press(CHIEF, "nt_pr:urgent")
    n_before = len(session.calls)
    await h.press(CHIEF, f"nt_f:{F1}")
    await h.press(CHIEF, f"nt_f:{F2}")
    await h.press(CHIEF, f"nt_f:{F2}")          # снял выбор
    assert [type(c).__name__ for c in session.calls[n_before:]] == ["EditMessageReplyMarkup", "AnswerCallbackQuery"] * 3
    session.calls.clear()
    await h.press(CHIEF, "nt_send")
    tasks = await db.list_tasks(chief_id=CHIEF)
    assert [t["foreman_id"] for t in tasks] == [F1] and tasks[0]["priority"] == "urgent"
    assert [c.chat_id for c in session.sent("SendMessage") if "Новая задача" in c.text] == [F1]

    # «отправить всем»
    await h.say(CHIEF, "➕ Новая задача")
    await h.say(CHIEF, "Проверить арматуру")
    await h.press(CHIEF, "nt_pr:normal")
    session.calls.clear()
    await h.press(CHIEF, "nt_sendall")
    assert {c.chat_id for c in session.sent("SendMessage") if "Новая задача" in c.text} == {F1, F2}
    assert len(await db.list_tasks(chief_id=CHIEF)) == 3, 'после «отправить всем»'

    # фото (с превью) и голосовое (с длительностью) сохраняются для дашборда
    await h.say(CHIEF, "➕ Новая задача")
    sizes = [PhotoSize(file_id=f"P{i}", file_unique_id=f"u{i}", width=100 * (i + 1), height=100 * (i + 1)) for i in range(4)]
    await h.send(CHIEF, photo=sizes, caption="Армирование")
    await h.press(CHIEF, "nt_pr:high")
    await h.press(CHIEF, "nt_sendall")
    await h.say(CHIEF, "➕ Новая задача")
    await h.send(CHIEF, voice=Voice(file_id="V1", file_unique_id="uv", duration=12))
    await h.press(CHIEF, "nt_pr:normal")
    await h.press(CHIEF, f"nt_f:{F1}")
    await h.press(CHIEF, "nt_send")
    media = {t["kind"]: t for t in await db.list_tasks(chief_id=CHIEF, limit=50) if t["kind"] != "text"}
    assert (media["photo"]["file_id"], media["photo"]["thumb_id"], media["photo"]["text"]) == ("P3", "P2", "Армирование")
    assert (media["voice"]["file_id"], media["voice"]["duration"], media["voice"]["thumb_id"]) == ("V1", 12, None)
    assert session.sent("SendPhoto") and session.sent("SendVoice")
    await db.pool.execute("UPDATE tasks SET status='cancelled' WHERE kind <> 'text'")  # не мешаем проверкам ниже

    # шеф закрывает задачу
    t = (await db.list_tasks(chief_id=CHIEF))[0]
    await h.press(CHIEF, f"ct_done:{t['id']}")
    assert (await db.get_task(t["id"]))["status"] == "done"
    await h.press(CHIEF, f"ct_fail:{t['id']}")  # повторно — уже закрыта, без ошибки
    assert (await db.get_task(t["id"]))["status"] == "done"

    # статистика, карточка прораба, экспорт, /dashboard
    session.calls.clear()
    await h.say(CHIEF, "📊 Статистика")
    stat_msg = session.sent("SendMessage")[0]
    assert "Статистика" in stat_msg.text
    assert any(b.web_app for row in stat_msg.reply_markup.inline_keyboard for b in row), "нет кнопки дашборда в статистике"
    await h.press(CHIEF, "st:30")
    await h.press(CHIEF, f"stf:{F1}:7")
    card = session.sent("EditMessageText")[-1].text
    assert "По важности" in card and "Срочная: 1" in card
    await h.press(CHIEF, "stx:0")
    assert session.sent("SendDocument")
    await h.say(CHIEF, "/dashboard")
    assert session.sent("SendMessage")[-1].reply_markup.inline_keyboard[0][0].web_app.url == "https://dash.example.com"

    # прораб: свои задачи и статистика
    session.calls.clear()
    await h.say(F1, "📋 Мои задачи")
    await h.say(F1, "📈 Моя статистика")
    assert "Ваша статистика" in session.sent("SendMessage")[-1].text
    # посторонний не получает доступа
    await h.say(999, "📊 Статистика")
    assert "только по ссылке" in session.sent("SendMessage")[-1].text

    # заявка нового прораба по ссылке и подтверждение
    session.calls.clear()
    await h.say(777, f"/start ref_{CHIEF}")
    assert (await db.get_user(777))["status"] == "pending"
    await h.press(CHIEF, "fm_ok:777")
    assert await db.is_active_foreman(777)

    # ---------------- несколько фото в одной задаче ----------------
    def photo(tag: int):
        return [PhotoSize(file_id=f"{tag}_{j}", file_unique_id=f"u{tag}{j}", width=100 * (j + 1), height=100 * (j + 1)) for j in range(4)]

    async def prompts():
        return [c for c in session.sent("SendMessage") if "важность" in (c.text or "")]

    await db.pool.execute("UPDATE tasks SET status='cancelled' WHERE status='new'")

    # 1) альбом из 3 фото приходит ОДНОВРЕМЕННО (так и ломалось: на каждое фото — свой выбор «для кого»)
    session.calls.clear()
    await h.say(CHIEF, "➕ Новая задача")
    await asyncio.gather(
        h.send(CHIEF, photo=photo(1), media_group_id="alb1"),
        h.send(CHIEF, photo=photo(2), media_group_id="alb1", caption="Армирование, 3 фото"),
        h.send(CHIEF, photo=photo(3), media_group_id="alb1"),
    )
    assert len(await prompts()) == 1, "на альбом должен быть ОДИН запрос важности"
    assert len(session.sent("EditMessageText")) == 2, "остальные фото обновляют счётчик, а не создают новые сообщения"
    assert "Фото: 3" in session.sent("EditMessageText")[-1].text
    await h.press(CHIEF, "nt_pr:high")
    session.calls.clear()
    await h.press(CHIEF, "nt_sendall")
    album_tasks = [t for t in await db.list_tasks(chief_id=CHIEF, limit=50) if t["text"] == "Армирование, 3 фото"]
    assert len(album_tasks) == 3                      # «отправить всем»: F1, F2 и подтверждённый выше прораб 777
    for t in album_tasks:
        assert t["kind"] == "photo" and t["file_id"] == "1_3" and [m["file_id"] for m in t["media"]] == ["1_3", "2_3", "3_3"]
        assert all(set(m) == {"kind", "file_id", "thumb_id", "duration"} for m in t["media"])  # служебное поле mid не сохраняется
    groups = session.sent("SendMediaGroup")
    assert {g.chat_id for g in groups} == {F1, F2, 777} and all(len(g.media) == 3 for g in groups)
    assert "Новая задача" in groups[0].media[0].caption and "Армирование" in groups[0].media[0].caption
    assert groups[0].media[1].caption is None          # подпись только у первого фото
    assert not session.sent("SendPhoto")
    assert "Фото: 3" in session.sent("EditMessageText")[-1].text

    # 2) фото пересылаются по одному (не альбом) — тоже собираются в одну задачу
    await db.pool.execute("UPDATE tasks SET status='cancelled' WHERE status='new'")
    session.calls.clear()
    await h.say(CHIEF, "➕ Новая задача")
    await asyncio.gather(*(h.send(CHIEF, photo=photo(10 + i)) for i in range(3)))
    assert len(await prompts()) == 1
    await h.press(CHIEF, "nt_pr:normal")
    await h.press(CHIEF, f"nt_f:{F1}")
    await h.press(CHIEF, "nt_send")
    t = (await db.list_tasks(chief_id=CHIEF, limit=50))[0]
    assert [m["file_id"] for m in t["media"]] == ["10_3", "11_3", "12_3"]

    # 3) хвост альбома, дошедший ПОСЛЕ выбора важности, не теряется; одиночное фото после — отклоняется
    await db.pool.execute("UPDATE tasks SET status='cancelled' WHERE status='new'")
    session.calls.clear()
    await h.say(CHIEF, "➕ Новая задача")
    await h.send(CHIEF, photo=photo(20), media_group_id="alb3")
    await h.press(CHIEF, "nt_pr:normal")
    await h.send(CHIEF, photo=photo(21), media_group_id="alb3")        # тот же альбом — дописывается молча
    n_msgs = len(session.sent("SendMessage"))
    await h.send(CHIEF, photo=photo(22))                               # другое фото — уже поздно
    assert "уже принята" in session.sent("SendMessage")[-1].text and len(session.sent("SendMessage")) == n_msgs + 1
    await h.press(CHIEF, f"nt_f:{F1}")
    await h.press(CHIEF, "nt_send")
    t = (await db.list_tasks(chief_id=CHIEF, limit=50))[0]
    assert [m["file_id"] for m in t["media"]] == ["20_3", "21_3"]

    # 4) голосовое + фото — не склеивается; одиночное фото остаётся обычной задачей без списка
    await db.pool.execute("UPDATE tasks SET status='cancelled' WHERE status='new'")
    await h.say(CHIEF, "➕ Новая задача")
    await h.send(CHIEF, voice=Voice(file_id="V9", file_unique_id="uv9", duration=3))
    await h.send(CHIEF, photo=photo(30))
    assert "уже принята" in session.sent("SendMessage")[-1].text
    await h.press(CHIEF, "nt_pr:normal")
    await h.press(CHIEF, f"nt_f:{F1}")
    await h.press(CHIEF, "nt_send")
    assert (await db.list_tasks(chief_id=CHIEF, limit=50))[0]["media"] is None
    await db.pool.execute("UPDATE tasks SET status='cancelled' WHERE status='new'")
    await h.say(CHIEF, "➕ Новая задача")
    await h.send(CHIEF, photo=photo(40), caption="одно фото")
    await h.press(CHIEF, "nt_pr:normal")
    session.calls.clear()
    await h.press(CHIEF, f"nt_f:{F1}")
    await h.press(CHIEF, "nt_send")
    assert session.sent("SendPhoto") and not session.sent("SendMediaGroup")
    single = (await db.list_tasks(chief_id=CHIEF, limit=50))[0]
    assert single["media"] is None and single["file_id"] == "40_3"

    # 5) шеф открывает задачу-альбом в «Активных»: альбом + отдельное сообщение с кнопками результата
    album = album_tasks[0]
    await db.pool.execute("UPDATE tasks SET status='new' WHERE id=$1", album["id"])
    session.calls.clear()
    await h.press(CHIEF, f"ct_view:{album['id']}")
    assert session.sent("SendMediaGroup") and "Отметьте результат" in session.sent("SendMessage")[-1].text
    assert session.sent("SendMessage")[-1].reply_markup is not None

    # ---------------- сроки в кнопках и «Сделал» у прораба ----------------
    await db.pool.execute("UPDATE tasks SET status='cancelled' WHERE status='new'")
    session.calls.clear()
    await h.say(CHIEF, "➕ Новая задача")
    await h.say(CHIEF, "Убрать мусор")
    prio_kb = session.sent("SendMessage")[-1].reply_markup.inline_keyboard
    labels = [b.text for row in prio_kb for b in row]
    assert any("Срочная" in x and "1 день" in x for x in labels) and any("Важная" in x and "7 дней" in x for x in labels)
    assert any("Обычная" in x and "1 месяц" in x for x in labels)
    await h.press(CHIEF, "nt_pr:urgent")
    await h.press(CHIEF, f"nt_f:{F1}")
    session.calls.clear()
    await h.press(CHIEF, "nt_send")
    sent = [c for c in session.sent("SendMessage") if c.chat_id == F1][0]
    assert "Срок: до" in sent.text and sent.reply_markup.inline_keyboard[0][0].text == "✅ Сделал"
    tid = (await db.list_tasks(chief_id=CHIEF))[0]["id"]

    # чужой прораб не может отметить чужую задачу
    await h.press(F2, f"fd:{tid}")
    assert (await db.get_task(tid))["status"] == "new"

    session.calls.clear()
    await h.press(F1, f"fd:{tid}")
    assert (await db.get_task(tid))["status"] == "reported"
    to_chief = [c for c in session.sent("SendMessage") if c.chat_id == CHIEF]
    assert to_chief and "отметил" in to_chief[0].text
    assert [b.callback_data for row in to_chief[0].reply_markup.inline_keyboard for b in row] == [
        f"ct_done:{tid}", f"ct_reopen:{tid}", f"ct_fail:{tid}"]
    await h.press(F1, f"fd:{tid}")                      # повторное нажатие ничего не ломает
    assert (await db.get_task(tid))["status"] == "reported"
    assert tid not in [t["id"] for t in await db.list_tasks(foreman_id=F1)]   # из списка прораба ушла

    # у шефа задача в «Активных» с пометкой ☑️; открывается с кнопками «Одобрить / Вернуть»
    session.calls.clear()
    await h.say(CHIEF, "📋 Активные задачи")
    lst = session.sent("SendMessage")[-1]
    assert any("☑️" in b.text for row in lst.reply_markup.inline_keyboard for b in row)
    session.calls.clear()
    await h.press(CHIEF, f"ct_view:{tid}")
    assert any(b.callback_data == f"ct_reopen:{tid}" for c in session.sent("SendMessage") if c.reply_markup
               for row in c.reply_markup.inline_keyboard for b in row)

    # шеф возвращает в работу -> прораб видит снова, шеф потом одобряет
    session.calls.clear()
    await h.press(CHIEF, f"ct_reopen:{tid}")
    assert (await db.get_task(tid))["status"] == "new"
    assert any(c.chat_id == F1 and "вернул" in c.text for c in session.sent("SendMessage"))
    await h.press(F1, f"fd:{tid}")
    await h.press(CHIEF, f"ct_done:{tid}")
    done = await db.get_task(tid)
    assert done["status"] == "done" and done["closed_at"]

    print("OK: хендлеры отработали без ошибок")
    await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
