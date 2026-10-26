"""
Сроки задач и кнопка прораба «Сделал» (статус reported -> одобрение шефом).

    TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/postgres python -m tests.report_test
"""
import asyncio
import os
import uuid
from datetime import timedelta

import asyncpg
from aiohttp.test_utils import TestClient, TestServer

from bot.config import Config
from bot.db import Database
from bot.keyboards import chief_actions_kb, foreman_done_kb, priority_kb
from bot.texts import chief_header, foreman_digest, foreman_header
from bot.web.server import build_web_app
from tests.smoke_test import TOKEN, TZ, sign_init_data

CHIEF, F1, F2 = 7_113_457_025, 10, 20

OLD_SCHEMA = """
CREATE TABLE users (tg_id BIGINT PRIMARY KEY, full_name TEXT NOT NULL DEFAULT '', username TEXT,
    role TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', chief_id BIGINT, created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE tasks (id BIGSERIAL PRIMARY KEY, chief_id BIGINT NOT NULL, foreman_id BIGINT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'text', file_id TEXT, text TEXT NOT NULL DEFAULT '',
    priority TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('normal', 'high', 'urgent')),
    status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'done', 'failed', 'cancelled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), closed_at TIMESTAMPTZ);
INSERT INTO users (tg_id, full_name, role, chief_id) VALUES (1, 'Шеф', 'chief', NULL), (2, 'Прораб', 'foreman', 1);
INSERT INTO tasks (chief_id, foreman_id, priority) VALUES (1, 2, 'urgent'), (1, 2, 'high'), (1, 2, 'normal');
"""


async def main() -> None:
    dsn = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("Задайте TEST_DATABASE_URL")
    schemas = []

    async def fresh() -> Database:
        schema = "r_" + uuid.uuid4().hex[:8]
        schemas.append(schema)
        return schema

    try:
        await migration(dsn, await fresh())
        schema = await fresh()
        db = Database(dsn, schema=schema)
        await db.connect()
        try:
            await run(db, dsn)
        finally:
            await db.close()
    finally:
        c = await asyncpg.connect(dsn)
        for s in schemas:
            await c.execute(f'DROP SCHEMA IF EXISTS "{s}" CASCADE')
        await c.close()
    print("OK: сроки и кнопка «Сделал» работают")


async def migration(dsn: str, schema: str) -> None:
    """Старая база (без reported/due_at) обновляется на месте, данные сохраняются."""
    c = await asyncpg.connect(dsn)
    await c.execute(f'CREATE SCHEMA "{schema}"')
    await c.execute(f'SET search_path TO "{schema}"')
    await c.execute(OLD_SCHEMA)
    await c.close()

    for i in range(2):  # повторный запуск не должен ничего ломать
        db = Database(dsn, schema=schema)
        await db.connect()
        rows = await db._all("SELECT priority, due_at - created_at AS span FROM tasks ORDER BY id")
        spans = {r["priority"]: r["span"] for r in rows}
        assert spans["urgent"] == timedelta(days=1) and spans["high"] == timedelta(days=7), spans
        assert timedelta(days=28) <= spans["normal"] <= timedelta(days=31), spans
        assert await db.report_done(1, 2) == (i == 0)  # новый статус допустим и в старой таблице
        await db.close()


async def run(db: Database, dsn: str) -> None:
    await db.upsert_chief(CHIEF, "Шеф")
    for fid, name in ((F1, "Иванов"), (F2, "Петров")):
        await db.register_foreman(fid, name, None, CHIEF)
        await db.set_user_status(fid, "active")

    # ---- сроки: обычная — 1 месяц, важная — 7 дней, срочная — 1 день
    by = {}
    for pr in ("normal", "high", "urgent"):
        t = (await db.create_tasks(CHIEF, [F1], "text", None, pr, pr))[0]
        by[pr] = t
        span = t["due_at"] - t["created_at"]
        want = {"normal": (28, 31), "high": (7, 7), "urgent": (1, 1)}[pr]
        assert timedelta(days=want[0]) <= span <= timedelta(days=want[1]), (pr, span)
    # одна важность — один срок и для нескольких прорабов
    two = await db.create_tasks(CHIEF, [F1, F2], "text", None, "x", "urgent")
    assert all(t["due_at"] - t["created_at"] == timedelta(days=1) for t in two)

    # ---- кнопки показывают срок
    labels = [b.text for row in priority_kb().inline_keyboard for b in row]
    assert any("Обычная" in x and "1 месяц" in x for x in labels), labels
    assert any("Важная" in x and "7 дней" in x for x in labels), labels
    assert any("Срочная" in x and "1 день" in x for x in labels), labels
    assert "Срок" in foreman_header(by["urgent"], new=True, tz=TZ)
    assert "Срок" in chief_header(by["urgent"], TZ)
    assert "Срок" not in foreman_header(by["urgent"])        # без часового пояса — как раньше

    # ---- «Сделал»
    t = by["high"]["id"]
    assert not await db.report_done(t, F2)                    # чужая задача
    assert await db.report_done(t, F1)
    assert not await db.report_done(t, F1)                    # повторно нельзя
    got = await db.get_task(t)
    assert got["status"] == "reported" and got["reported_at"] and got["closed_at"] is None
    assert [r["id"] for r in await db.list_tasks(foreman_id=F1)] != []  # у прораба остальные в работе
    assert t not in [r["id"] for r in await db.list_tasks(foreman_id=F1)]  # а эта — уже нет
    from bot.db import OPEN
    assert t in [r["id"] for r in await db.list_tasks(chief_id=CHIEF, statuses=OPEN)]
    assert (await db.list_tasks(chief_id=CHIEF, statuses=OPEN))[0]["id"] == t  # ждущие одобрения — первыми
    assert await db.reported_count(CHIEF) == 1 and await db.active_count(CHIEF) == 4
    rows = await db.stats(chief_id=CHIEF, days=None)
    assert sum(r["reported"] for r in rows) == 1

    # шеф одобряет
    assert await db.transition(t, "done")
    got = await db.get_task(t)
    assert got["status"] == "done" and got["closed_at"]
    assert await db.reported_count(CHIEF) == 0

    # шеф возвращает в работу
    t2 = by["normal"]["id"]
    assert await db.report_done(t2, F1) and await db.reopen(t2)
    got = await db.get_task(t2)
    assert got["status"] == "new" and got["reported_at"] is None
    assert not await db.reopen(t2)

    # клавиатуры
    data = [b.callback_data for row in chief_actions_kb(5, reported=True).inline_keyboard for b in row]
    assert data == ["ct_done:5", "ct_reopen:5", "ct_fail:5"], data
    assert [b.callback_data for b in foreman_done_kb(5).inline_keyboard[0]] == ["fa:5", "fd:5"]

    # ---- «Принял»
    t5 = (await db.create_tasks(CHIEF, [F1], "text", None, "принять", "normal"))[0]["id"]
    assert (await db.get_task(t5))["accepted_at"] is None
    assert "Ещё не принял" in chief_header(await db.get_task(t5), TZ)
    assert not await db.accept(t5, F2)                        # чужая
    assert await db.accept(t5, F1)
    assert not await db.accept(t5, F1)                        # повторно — нет
    assert "Принял:" in chief_header(await db.get_task(t5), TZ)
    # «Сделал» без «Принял» тоже считает задачу принятой
    t6 = (await db.create_tasks(CHIEF, [F1], "text", None, "сразу сделал", "normal"))[0]["id"]
    assert await db.report_done(t6, F1) and (await db.get_task(t6))["accepted_at"]
    assert not await db.accept(t6, F1)                        # закрытую/сданную уже не принять
    # возврат в работу не сбрасывает «принял»
    assert await db.reopen(t6) and (await db.get_task(t6))["accepted_at"]
    assert [b.text for b in foreman_done_kb(1).inline_keyboard[0]] == ["👍 Принял", "✅ Сделал"]
    assert [b.text for b in foreman_done_kb(1, accepted=True).inline_keyboard[0]] == ["✅ Сделал"]

    # ---- ежедневная сводка прораба
    rows = [r for r in await db.foreman_digest_rows() if r["foreman_id"] == F1]
    assert rows and all(r["status"] in ("new", "reported") for r in rows)
    text = foreman_digest(rows, "24.10.2026", TZ)
    assert "Ваши задачи" in text and "В работе" in text and "👀" in text and "до " in text, text
    assert foreman_digest([], "24.10.2026", TZ) is None
    # планировщик: каждому прорабу — своя сводка, раз в день
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from bot.scheduler import _digest

    class FakeBot:
        def __init__(self):
            self.sent = []

        async def send_message(self, chat_id, text, reply_markup=None):
            self.sent.append((chat_id, text))

    hour = datetime.now(ZoneInfo(TZ)).hour
    cfg = Config(TOKEN, (CHIEF,), dsn, TZ, hour)
    bot = FakeBot()
    await _digest(bot, db, cfg)
    to = {chat for chat, _ in bot.sent}
    assert to == {CHIEF, F1, F2}, bot.sent                               # у обоих прорабов есть задачи
    mine = [txt for chat, txt in bot.sent if chat == F1][0]
    assert "Ваши задачи" in mine and "В работе" in mine
    chief_txt = [txt for chat, txt in bot.sent if chat == CHIEF][0]
    assert "Иванов" in chief_txt
    assert 30 not in to
    # прораб без задач сводку не получает
    await db.register_foreman(30, "Без задач", None, CHIEF)
    await db.set_user_status(30, "active")
    await _digest(bot, db, cfg)                                          # второй проход в тот же день — тишина
    assert len(bot.sent) == 3, bot.sent

    # шефская сводка: счётчики «ждёт одобрения» / «не принято»
    wl = {r["tg_id"]: r for r in await db.workload_all()}
    assert wl[F1]["active"] >= 1 and wl[F1]["reported"] == 0 and wl[F1]["not_accepted"] >= 1, dict(wl[F1])

    # ---- дашборд
    t3 = by["urgent"]["id"]
    assert await db.report_done(t3, F1)
    client = TestClient(TestServer(build_web_app(db, Config(TOKEN, (CHIEF,), dsn, TZ, 8))))
    await client.start_server()
    h = {"Authorization": "tma " + sign_init_data(CHIEF)}
    try:
        dash = await (await client.get("/api/dashboard?days=7", headers=h)).json()
        assert dash["summary"]["reported_now"] == 1 and dash["summary"]["reported"] == 1
        assert dash["daily"][-1]["reported"] == 1
        assert [x["id"] for x in dash["awaiting"]] == [t3]
        assert all("reported" in f for f in dash["foremen"])

        feed = await (await client.get("/api/tasks?status=reported", headers=h)).json()
        assert [x["id"] for x in feed["tasks"]] == [t3]
        task = feed["tasks"][0]
        assert task["status"] == "reported" and task["reported_at"] and task["due_at"]
        one = (await (await client.get("/api/tasks?status=new", headers=h)).json())["tasks"]
        by_id = {x["id"]: x for x in one}
        assert by_id[t5]["accepted_at"] and by_id[t6]["accepted_at"]


        # одобрение из дашборда
        r = await client.post(f"/api/tasks/{t3}/status", json={"status": "done"}, headers=h)
        body = await r.json()
        assert r.status == 200 and body["task"]["status"] == "done"
        # и возврат в работу того, что не принято
        t4 = (await db.create_tasks(CHIEF, [F1], "text", None, "ещё", "normal"))[0]["id"]
        await db.report_done(t4, F1)
        r = await client.post(f"/api/tasks/{t4}/status", json={"status": "new"}, headers=h)
        body = await r.json()
        assert r.status == 200 and body["task"]["status"] == "new" and body["task"]["reported_at"] is None
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
