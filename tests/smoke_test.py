"""
Быстрая проверка логики без Telegram:  python -m tests.smoke_test
Проверяет БД, переходы статусов, статистику, миграцию старой базы и сборку диспетчера.
"""
import asyncio
import os
import sqlite3
import tempfile

from bot.config import Config
from bot.db import Database
from bot.main import build_dispatcher
from bot.texts import preview

TZ = "Asia/Dushanbe"


async def main() -> None:
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "t.db")
    db = Database(path)
    await db.connect()

    await db.upsert_chief(1, "Шеф")
    await db.register_foreman(10, "Иванов", None, 1)
    await db.register_foreman(11, "Петров", None, 1)
    assert not await db.is_active_foreman(10)
    await db.set_user_status(10, "active")
    await db.set_user_status(11, "active")
    assert await db.is_chief(1) and await db.is_active_foreman(10)

    t1 = await db.create_task(1, 10, "text", None, "Залить фундамент", "urgent")
    t2 = await db.create_task(1, 10, "photo", "FILE_PHOTO", "Армирование", "high")
    t3 = await db.create_task(1, 11, "voice", "FILE_VOICE", "", "normal")

    task = await db.get_task(t3)
    assert (task["kind"], task["file_id"], task["status"]) == ("voice", "FILE_VOICE", "new")
    assert preview(task) == "🎤 Голосовое"
    assert preview(await db.get_task(t2)) == "📷 Фото: Армирование"
    assert preview(await db.get_task(t1)) == "Залить фундамент"

    # сортировка: срочные выше
    order = [t["id"] for t in await db.list_tasks(chief_id=1)]
    assert order == [t1, t2, t3], order

    # переходы
    assert await db.transition(t1, "done")
    assert not await db.transition(t1, "failed")  # уже закрыта
    assert await db.transition(t3, "failed")
    assert (await db.get_task(t2))["status"] == "new"
    assert [t["id"] for t in await db.list_tasks(foreman_id=10)] == [t2]

    # статистика
    rows = {r["full_name"]: r for r in await db.stats(chief_id=1)}
    iv, pe = rows["Иванов"], rows["Петров"]
    assert (iv["total"], iv["done"], iv["failed"], iv["active"]) == (2, 1, 0, 1)
    assert (pe["total"], pe["done"], pe["failed"]) == (1, 0, 1)
    assert iv["avg_hours"] is not None and pe["avg_hours"] is None
    one = await db.stats(foreman_id=10, days=7)
    assert len(one) == 1 and one[0]["total"] == 2
    assert len(await db.export_rows(1, None)) == 3
    wl = {r["full_name"]: r for r in await db.workload(1)}
    assert wl["Иванов"]["active"] == 1 and wl["Петров"]["active"] == 0

    # meta
    assert await db.meta_get("k") is None
    await db.meta_set("k", "v")
    await db.meta_set("k", "v2")
    assert await db.meta_get("k") == "v2"

    # диспетчер собирается (проверяет сигнатуры фильтров и роутеры)
    build_dispatcher(db, Config("1:x", (1,), path, TZ, 8))
    await db.close()

    # миграция базы от прошлой версии (с названием и сроком)
    old = os.path.join(folder, "old.db")
    c = sqlite3.connect(old)
    c.executescript(
        """
        CREATE TABLE users (tg_id INTEGER PRIMARY KEY, full_name TEXT, username TEXT, role TEXT,
                            status TEXT, chief_id INTEGER, created_at TEXT);
        CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, chief_id INTEGER, foreman_id INTEGER,
                            title TEXT, description TEXT, priority TEXT, status TEXT, deadline TEXT,
                            created_at TEXT, closed_at TEXT);
        CREATE INDEX idx_tasks_foreman ON tasks (foreman_id, status);
        CREATE INDEX idx_tasks_deadline ON tasks (deadline);
        INSERT INTO tasks (chief_id, foreman_id, title, description, priority, status, created_at)
        VALUES (1, 10, 'старая', '', 'normal', 'new', '2026-10-01 00:00:00');
        """
    )
    c.commit()
    c.close()
    db2 = Database(old)
    await db2.connect()
    cols = {r["name"] for r in await db2._all("PRAGMA table_info(tasks)")}
    assert "kind" in cols and "title" not in cols
    assert (await db2._one("SELECT COUNT(*) AS c FROM tasks_legacy"))["c"] == 1
    await db2.upsert_chief(1)
    await db2.close()

    print("OK: все проверки пройдены")


if __name__ == "__main__":
    asyncio.run(main())
