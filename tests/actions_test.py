"""
Отметка результата из дашборда: POST /api/tasks/{id}/status.

    TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/postgres python -m tests.actions_test
"""
import asyncio
import os
import uuid

import asyncpg
from aiohttp.test_utils import TestClient, TestServer

from bot.config import Config
from bot.db import Database
from bot.web.server import build_web_app
from tests.smoke_test import TOKEN, TZ, sign_init_data

CHIEF, OTHER, F1, F2 = 7_113_457_025, 2, 10, 20


async def main() -> None:
    dsn = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("Задайте TEST_DATABASE_URL")
    schema = "a_" + uuid.uuid4().hex[:8]
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
    await db.upsert_chief(OTHER, "Другой")
    for fid, name, chief in ((F1, "Иванов", CHIEF), (F2, "Чужой", OTHER)):
        await db.register_foreman(fid, name, None, chief)
        await db.set_user_status(fid, "active")
    ids = [(await db.create_tasks(CHIEF, [F1], "text", None, f"задача {i}", "normal"))[0]["id"] for i in range(4)]
    foreign = (await db.create_tasks(OTHER, [F2], "text", None, "чужая", "normal"))[0]["id"]
    a, b, c, d = ids

    client = TestClient(TestServer(build_web_app(db, Config(TOKEN, (CHIEF, OTHER), dsn, TZ, 8))))
    await client.start_server()
    h = lambda uid: {"Authorization": "tma " + sign_init_data(uid)}
    post = lambda tid, body, uid=CHIEF: client.post(f"/api/tasks/{tid}/status", json=body, headers=h(uid))

    try:
        dash = lambda: client.get("/api/dashboard?days=7", headers=h(CHIEF))
        before = (await (await dash()).json())["summary"]
        assert (before["active_now"], before["done"]) == (4, 0)

        # ---- доступ
        r = await client.post(f"/api/tasks/{a}/status", json={"status": "done"})
        assert r.status == 401
        assert (await post(a, {"status": "done"}, uid=F1)).status == 403              # прораб — не шеф
        assert (await post(foreign, {"status": "done"})).status == 404                 # чужая задача
        assert (await get_status(db, foreign)) == "new"
        assert (await post(9999, {"status": "done"})).status == 404

        # ---- плохие запросы
        assert (await post(a, {"status": "wat"})).status == 400
        assert (await post(a, {})).status == 400
        r = await client.post(f"/api/tasks/{a}/status", data="не json", headers=h(CHIEF))
        assert r.status == 400
        assert (await client.post("/api/tasks/abc/status", json={"status": "done"}, headers=h(CHIEF))).status == 400

        # ---- выполнено / не выполнено / отменено
        r = await post(a, {"status": "done"})
        body = await r.json()
        assert r.status == 200 and body["task"]["status"] == "done" and body["task"]["closed_at"]
        assert (await post(b, {"status": "failed"})).status == 200
        r = await post(c, {"status": "cancelled"})
        assert (await r.json())["task"]["status"] == "cancelled"
        assert [await get_status(db, t) for t in (a, b, c, d)] == ["done", "failed", "cancelled", "new"]

        # дашборд сразу показывает новые цифры (серверный кэш сброшен)
        after = (await (await dash()).json())["summary"]
        assert (after["active_now"], after["done"], after["failed"], after["cancelled"]) == (1, 1, 1, 1), after
        assert after["completion"] == 50

        # ---- гонка: задачу уже закрыли (например, в боте) → 409 и актуальное состояние
        r = await post(a, {"status": "failed"})
        j = await r.json()
        assert r.status == 409 and j["error"] == "conflict" and j["task"]["status"] == "done"
        assert await get_status(db, a) == "done"

        # ---- вернуть в работу (исправление ошибочной отметки)
        r = await post(a, {"status": "new"})
        j = await r.json()
        assert r.status == 200 and j["task"]["status"] == "new" and j["task"]["closed_at"] is None
        assert (await (await dash()).json())["summary"]["active_now"] == 2
        assert (await post(a, {"status": "new"})).status == 409                         # уже в работе
        assert (await post(a, {"status": "done"})).status == 200                        # и снова можно закрыть
        # чужую задачу вернуть в работу тоже нельзя
        await db.transition(foreign, "done")
        assert (await post(foreign, {"status": "new"})).status == 404 and await get_status(db, foreign) == "done"

        # ---- лента задач отражает статус
        feed = await (await client.get("/api/tasks?status=done", headers=h(CHIEF))).json()
        assert [t["id"] for t in feed["tasks"]] == [a]
    finally:
        await client.close()

    # ---- db.reopen
    assert await db.reopen(d) is False                    # d в работе
    assert await db.transition(d, "failed") and await db.reopen(d) and await get_status(db, d) == "new"
    assert (await db.get_task(d))["closed_at"] is None
    print("OK: отметка результата из дашборда работает")


async def get_status(db: Database, task_id: int) -> str:
    return (await db.get_task(task_id))["status"]


if __name__ == "__main__":
    asyncio.run(main())
