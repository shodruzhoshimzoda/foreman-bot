"""
Быстрая проверка логики без Telegram:

    TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/postgres python -m tests.smoke_test

Каждый запуск работает в отдельной временной схеме PostgreSQL и удаляет её в конце —
рабочие данные не затрагиваются. Проверяет БД, переходы статусов, статистику,
кэш ролей, перенос из SQLite, подпись Telegram initData и JSON API дашборда.
"""
import asyncio
import hashlib
import hmac
import json
import os
import sqlite3
import tempfile
import time
import uuid
from urllib.parse import urlencode

import asyncpg
from aiohttp.test_utils import TestClient, TestServer

from bot.config import Config
from bot.db import Database
from bot.main import build_dispatcher
from bot.texts import preview
from bot.web.auth import AuthError, validate_init_data
from bot.web.server import build_web_app
from scripts.migrate_sqlite_to_pg import migrate

TZ = "Asia/Dushanbe"
TOKEN = "123456:TEST-TOKEN"
BIG = 7_113_457_025  # реальные Telegram ID не влезают в int32


def sign_init_data(user_id: int, token: str = TOKEN, auth_date: int | None = None) -> str:
    fields = {"auth_date": str(auth_date or int(time.time())), "query_id": "AAH", "user": json.dumps({"id": user_id, "first_name": "T"})}
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


async def main() -> None:
    dsn = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("Задайте TEST_DATABASE_URL (подойдёт любая база: тест создаёт и удаляет свою схему).")
    schema = "t_" + uuid.uuid4().hex[:8]
    db = Database(dsn, schema=schema)
    try:
        await run(db, dsn, schema)
    finally:
        await db.close()
        c = await asyncpg.connect(dsn)
        await c.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await c.execute(f'DROP SCHEMA IF EXISTS "{schema}_mig" CASCADE')
        await c.close()


async def run(db: Database, dsn: str, schema: str) -> None:
    await db.connect()

    await db.upsert_chief(BIG, "Шеф")
    await db.upsert_chief(2, "Другой шеф")
    await db.register_foreman(10, "Иванов", None, BIG)
    await db.register_foreman(11, "Петров", None, BIG)
    await db.register_foreman(20, "Чужой", None, 2)
    assert not await db.is_active_foreman(10)
    for f in (10, 11, 20):
        await db.set_user_status(f, "active")
    assert await db.is_chief(BIG) and await db.is_active_foreman(10)

    # кэш ролей: значение закэшировано, но запись его инвалидирует
    assert await db.get_role(10) == ("foreman", "active")
    await db.set_user_status(10, "blocked")
    assert not await db.is_active_foreman(10)
    await db.set_user_status(10, "active")
    assert await db.is_active_foreman(10)
    assert await db.get_role(999) is None

    t1 = await db.create_task(BIG, 10, "text", None, "Залить фундамент", "urgent")
    t2 = await db.create_task(BIG, 10, "photo", "FILE_PHOTO", "Армирование", "high")
    t3 = await db.create_task(BIG, 11, "voice", "FILE_VOICE", "", "normal")
    await db.create_task(2, 20, "text", None, "чужая", "normal")

    # массовая отправка одним запросом
    bulk = await db.create_tasks(BIG, [10, 11], "text", None, "всем", "normal")
    assert [r["foreman_name"] for r in bulk] == ["Иванов", "Петров"]
    await db.transition(bulk[0]["id"], "cancelled")
    await db.transition(bulk[1]["id"], "cancelled")

    task = await db.get_task(t3)
    assert (task["kind"], task["file_id"], task["status"]) == ("voice", "FILE_VOICE", "new")
    assert preview(task) == "🎤 Голосовое"
    assert preview(await db.get_task(t2)) == "📷 Фото: Армирование"
    assert preview(await db.get_task(t1)) == "Залить фундамент"

    assert [t["id"] for t in await db.list_tasks(chief_id=BIG)] == [t1, t2, t3]  # срочные выше

    assert await db.transition(t1, "done")
    assert not await db.transition(t1, "failed")  # уже закрыта
    assert await db.transition(t3, "failed")
    assert (await db.get_task(t2))["status"] == "new"
    assert (await db.get_task(t1))["closed_at"] is not None
    assert [t["id"] for t in await db.list_tasks(foreman_id=10)] == [t2]

    # статистика
    rows = {r["full_name"]: r for r in await db.stats(chief_id=BIG)}
    assert "Чужой" not in rows
    iv, pe = rows["Иванов"], rows["Петров"]
    assert (iv["total"], iv["done"], iv["failed"], iv["active"], iv["cancelled"]) == (3, 1, 0, 1, 1)
    assert (iv["prio_urgent"], iv["prio_high"], iv["kind_photo"], iv["kind_text"]) == (1, 1, 1, 2)
    assert (pe["total"], pe["done"], pe["failed"], pe["cancelled"]) == (2, 0, 1, 1)
    assert iv["avg_hours"] is not None and pe["avg_hours"] is None
    one = await db.stats(foreman_id=10, days=7)
    assert len(one) == 1 and one[0]["total"] == 3
    assert len(await db.export_rows(BIG, None)) == 5
    wl = {r["full_name"]: r for r in await db.workload_all()}
    assert wl["Иванов"]["active"] == 1 and wl["Петров"]["active"] == 0

    # заявку можно удалить, а прораба с историей — нет
    await db.register_foreman(30, "Новый", None, BIG)
    await db.delete_user(30)
    await db.delete_user(10)
    assert await db.get_user(30) is None and await db.get_user(10) is not None

    assert await db.meta_get("k") is None
    await db.meta_set("k", "v")
    await db.meta_set("k", "v2")
    assert await db.meta_get("k") == "v2"

    cfg = Config(TOKEN, (BIG, 2), dsn, TZ, 8)
    build_dispatcher(db, cfg)  # проверяет сигнатуры фильтров и роутеры

    # ------------------------------------------------ веб-API
    for bad in ("", "hash=abc", sign_init_data(BIG, token="other:token")):
        try:
            validate_init_data(bad, TOKEN)
            raise AssertionError("должно было отклонить")
        except AuthError:
            pass
    try:
        validate_init_data(sign_init_data(BIG, auth_date=int(time.time()) - 3 * 86400), TOKEN)
        raise AssertionError("просроченный initData должен отклоняться")
    except AuthError:
        pass
    assert validate_init_data(sign_init_data(BIG), TOKEN) == BIG

    client = TestClient(TestServer(build_web_app(db, cfg)))
    await client.start_server()
    try:
        h = lambda uid: {"Authorization": "tma " + sign_init_data(uid)}
        assert (await client.get("/api/dashboard")).status == 401
        assert (await client.get("/api/dashboard", headers={"Authorization": "tma garbage"})).status == 401
        assert (await client.get("/api/dashboard", headers=h(10))).status == 403          # прораб — не шеф
        assert (await client.get("/api/dashboard?days=5", headers=h(BIG))).status == 400
        assert (await client.get("/healthz")).status == 200

        r = await client.get("/api/dashboard?days=7", headers=h(BIG))
        assert r.status == 200
        d = await r.json()
        s = d["summary"]
        assert (s["total"], s["done"], s["failed"], s["active"], s["cancelled"], s["foremen"]) == (5, 1, 1, 1, 2, 2), s
        assert s["completion"] == 50 and s["active_now"] == 1
        assert d["by_priority"] == {"urgent": 1, "high": 1, "normal": 3}
        assert d["by_kind"]["photo"] == 1 and d["by_kind"]["voice"] == 1 and d["by_kind"]["text"] == 3
        assert {f["name"] for f in d["foremen"]} == {"Иванов", "Петров"}       # чужих прорабов нет
        assert len(d["daily"]) == 7 and sum(x["total"] for x in d["daily"]) == 5
        assert len(d["recent"]) == 5 and all(x["foreman"] != "Чужой" for x in d["recent"])
        assert [x["id"] for x in d["stale"]] == [t2]
        d_all = await (await client.get("/api/dashboard?days=0", headers=h(BIG))).json()
        assert len(d_all["daily"]) == 90 and d_all["summary"]["total"] == 5

        other = await (await client.get("/api/dashboard", headers=h(2))).json()
        assert other["summary"]["total"] == 1 and other["foremen"][0]["name"] == "Чужой"  # данные шефов изолированы
    finally:
        await client.close()

    await db.close()

    # ------------------------------------------------ миграция из SQLite (старая схема и новая)
    folder = tempfile.mkdtemp()
    new_db = os.path.join(folder, "new.db")
    c = sqlite3.connect(new_db)
    c.executescript(
        """
        CREATE TABLE users (tg_id INTEGER PRIMARY KEY, full_name TEXT, username TEXT, role TEXT,
                            status TEXT, chief_id INTEGER, created_at TEXT);
        CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, chief_id INTEGER, foreman_id INTEGER, kind TEXT,
                            file_id TEXT, text TEXT, priority TEXT, status TEXT, created_at TEXT, closed_at TEXT);
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        INSERT INTO users VALUES (7113457025,'Шеф',NULL,'chief','active',NULL,'2026-10-01 05:00:00');
        INSERT INTO users VALUES (5624300072,'Прораб',NULL,'foreman','active',7113457025,'2026-10-01 05:01:00');
        INSERT INTO tasks VALUES (41,7113457025,5624300072,'text',NULL,'a','normal','done','2026-10-01 06:00:00','2026-10-01 08:30:00');
        INSERT INTO tasks VALUES (42,7113457025,999,'text',NULL,'orphan','normal','new','2026-10-01 06:00:00',NULL);
        """
    )
    c.commit(); c.close()
    mig_schema = schema + "_mig"
    rep = await migrate(new_db, dsn, schema=mig_schema)
    assert rep == {"users": 2, "tasks": 1, "tasks_skipped": 1, "meta": 0}, rep
    db3 = Database(dsn, schema=mig_schema)
    await db3.connect()
    st = (await db3.stats(chief_id=7113457025))[0]
    assert (st["total"], st["done"]) == (1, 1) and abs(st["avg_hours"] - 2.5) < 1e-6
    assert await db3.create_task(7113457025, 5624300072, "text", None, "next", "normal") == 42  # id продолжается
    await db3.close()

    print("OK: все проверки пройдены")


if __name__ == "__main__":
    asyncio.run(main())
