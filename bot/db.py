from __future__ import annotations

import os
from datetime import timedelta

import aiosqlite

from utils import now_str, to_db, utcnow

ACTIVE = ("new",)
CLOSED = ("done", "failed", "cancelled")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    tg_id      INTEGER PRIMARY KEY,
    full_name  TEXT NOT NULL DEFAULT '',
    username   TEXT,
    role       TEXT NOT NULL CHECK (role IN ('chief', 'foreman')),
    status     TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('pending', 'active', 'blocked')),
    chief_id   INTEGER,
    created_at TEXT NOT NULL
);

-- Задача = то, что прислал шеф: текст, фото, голосовое и т.п.
CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chief_id    INTEGER NOT NULL,
    foreman_id  INTEGER NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'text',   -- text | photo | voice | video | document
    file_id     TEXT,
    text        TEXT NOT NULL DEFAULT '',        -- сообщение или подпись к файлу
    priority    TEXT NOT NULL DEFAULT 'normal',  -- normal | high | urgent
    status      TEXT NOT NULL DEFAULT 'new',     -- new | done | failed | cancelled
    created_at  TEXT NOT NULL,
    closed_at   TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_foreman ON tasks (foreman_id, status);
CREATE INDEX IF NOT EXISTS idx_tasks_chief   ON tasks (chief_id, status);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

_TASK_SELECT = """
SELECT t.*, f.full_name AS foreman_name
FROM tasks t
JOIN users f ON f.tg_id = t.foreman_id
"""

_PRIORITY_ORDER = "CASE t.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 ELSE 2 END"


def _in(values) -> str:
    return ",".join("?" for _ in values)


class Database:
    def __init__(self, path: str):
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        folder = os.path.dirname(self.path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.execute("PRAGMA foreign_keys=ON")
        await self._migrate_legacy_tasks()
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()

    async def _migrate_legacy_tasks(self) -> None:
        """База от прошлой версии (с названием и сроком): старые задачи сохраняем в tasks_legacy."""
        async with self.conn.execute("PRAGMA table_info(tasks)") as cur:
            cols = {r["name"] for r in await cur.fetchall()}
        if cols and "kind" not in cols:
            for idx in ("idx_tasks_foreman", "idx_tasks_chief", "idx_tasks_deadline"):
                await self.conn.execute(f"DROP INDEX IF EXISTS {idx}")
            await self.conn.execute("DROP TABLE IF EXISTS tasks_legacy")
            await self.conn.execute("ALTER TABLE tasks RENAME TO tasks_legacy")
            await self.conn.commit()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()

    # ---------- низкоуровневые помощники ----------
    async def _all(self, sql: str, params=()) -> list[aiosqlite.Row]:
        async with self.conn.execute(sql, params) as cur:
            return await cur.fetchall()

    async def _one(self, sql: str, params=()) -> aiosqlite.Row | None:
        async with self.conn.execute(sql, params) as cur:
            return await cur.fetchone()

    async def _exec(self, sql: str, params=()) -> aiosqlite.Cursor:
        cur = await self.conn.execute(sql, params)
        await self.conn.commit()
        return cur

    # ---------- пользователи ----------
    async def upsert_chief(self, tg_id: int, full_name: str = "Шеф", username: str | None = None) -> None:
        await self._exec(
            """
            INSERT INTO users (tg_id, full_name, username, role, status, chief_id, created_at)
            VALUES (?, ?, ?, 'chief', 'active', NULL, ?)
            ON CONFLICT(tg_id) DO UPDATE SET role='chief', status='active', chief_id=NULL
            """,
            (tg_id, full_name, username, now_str()),
        )

    async def touch_user(self, tg_id: int, full_name: str, username: str | None) -> None:
        await self._exec(
            "UPDATE users SET full_name=?, username=? WHERE tg_id=?",
            (full_name, username, tg_id),
        )

    async def get_user(self, tg_id: int):
        return await self._one("SELECT * FROM users WHERE tg_id=?", (tg_id,))

    async def is_chief(self, tg_id: int) -> bool:
        row = await self._one("SELECT 1 FROM users WHERE tg_id=? AND role='chief'", (tg_id,))
        return row is not None

    async def is_active_foreman(self, tg_id: int) -> bool:
        row = await self._one(
            "SELECT 1 FROM users WHERE tg_id=? AND role='foreman' AND status='active'", (tg_id,)
        )
        return row is not None

    async def register_foreman(self, tg_id: int, full_name: str, username: str | None, chief_id: int) -> None:
        await self._exec(
            """
            INSERT INTO users (tg_id, full_name, username, role, status, chief_id, created_at)
            VALUES (?, ?, ?, 'foreman', 'pending', ?, ?)
            """,
            (tg_id, full_name, username, chief_id, now_str()),
        )

    async def set_user_status(self, tg_id: int, status: str) -> None:
        await self._exec("UPDATE users SET status=? WHERE tg_id=?", (status, tg_id))

    async def delete_user(self, tg_id: int) -> None:
        await self._exec("DELETE FROM users WHERE tg_id=? AND role='foreman'", (tg_id,))

    async def list_foremen(self, chief_id: int, status: str = "active"):
        return await self._all(
            """
            SELECT u.*,
                   (SELECT COUNT(*) FROM tasks t
                     WHERE t.foreman_id = u.tg_id AND t.status='new') AS active_cnt
            FROM users u
            WHERE u.role='foreman' AND u.chief_id=? AND u.status=?
            ORDER BY u.full_name
            """,
            (chief_id, status),
        )

    async def list_chiefs(self):
        return await self._all("SELECT * FROM users WHERE role='chief' AND status='active'")

    # ---------- задачи ----------
    async def create_task(
        self,
        chief_id: int,
        foreman_id: int,
        kind: str,
        file_id: str | None,
        text: str,
        priority: str,
    ) -> int:
        cur = await self._exec(
            """
            INSERT INTO tasks (chief_id, foreman_id, kind, file_id, text, priority, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'new', ?)
            """,
            (chief_id, foreman_id, kind, file_id, text, priority, now_str()),
        )
        return cur.lastrowid

    async def get_task(self, task_id: int):
        return await self._one(_TASK_SELECT + " WHERE t.id=?", (task_id,))

    async def list_tasks(
        self,
        *,
        chief_id: int | None = None,
        foreman_id: int | None = None,
        statuses: tuple[str, ...] = ACTIVE,
        limit: int = 30,
    ):
        sql = _TASK_SELECT + f" WHERE t.status IN ({_in(statuses)})"
        params: list = list(statuses)
        if chief_id is not None:
            sql += " AND t.chief_id=?"
            params.append(chief_id)
        if foreman_id is not None:
            sql += " AND t.foreman_id=?"
            params.append(foreman_id)
        sql += f" ORDER BY {_PRIORITY_ORDER}, t.id LIMIT ?"
        params.append(limit)
        return await self._all(sql, params)

    async def recent_tasks(self, foreman_id: int, days: int | None, limit: int = 10):
        return await self._all(
            _TASK_SELECT + " WHERE t.foreman_id=? AND t.created_at>=? ORDER BY t.id DESC LIMIT ?",
            (foreman_id, self._since(days), limit),
        )

    async def transition(self, task_id: int, to: str, allowed_from: tuple[str, ...] = ACTIVE) -> bool:
        """Атомарно меняет статус. False — если задача уже в другом статусе."""
        sets, params = ["status=?"], [to]
        if to in CLOSED:
            sets.append("closed_at=?")
            params.append(now_str())
        params += [task_id, *allowed_from]
        cur = await self._exec(
            f"UPDATE tasks SET {', '.join(sets)} WHERE id=? AND status IN ({_in(allowed_from)})",
            params,
        )
        return cur.rowcount > 0

    # ---------- аналитика ----------
    @staticmethod
    def _since(days: int | None) -> str:
        if not days:
            return "0000-01-01 00:00:00"
        return to_db(utcnow() - timedelta(days=days))

    async def stats(
        self,
        *,
        chief_id: int | None = None,
        foreman_id: int | None = None,
        days: int | None = None,
    ):
        """Сводка по прорабам за период (по дате создания задачи)."""
        return await self._all(
            """
            SELECT u.tg_id, u.full_name,
                   COUNT(t.id)                              AS total,
                   COALESCE(SUM(t.status='done'), 0)        AS done,
                   COALESCE(SUM(t.status='failed'), 0)      AS failed,
                   COALESCE(SUM(t.status='cancelled'), 0)   AS cancelled,
                   COALESCE(SUM(t.status='new'), 0)         AS active,
                   AVG(CASE WHEN t.status='done'
                            THEN (julianday(t.closed_at) - julianday(t.created_at)) * 24 END) AS avg_hours
            FROM users u
            LEFT JOIN tasks t ON t.foreman_id = u.tg_id AND t.created_at >= :since
            WHERE u.role = 'foreman'
              AND (:chief IS NULL OR u.chief_id = :chief)
              AND (:fid IS NULL OR u.tg_id = :fid)
              AND (:fid IS NOT NULL OR u.status = 'active')
            GROUP BY u.tg_id
            ORDER BY total DESC, u.full_name
            """,
            {"since": self._since(days), "chief": chief_id, "fid": foreman_id},
        )

    async def priority_breakdown(self, foreman_id: int, days: int | None):
        return await self._all(
            "SELECT priority, COUNT(*) AS c FROM tasks WHERE foreman_id=? AND created_at>=? GROUP BY priority",
            (foreman_id, self._since(days)),
        )

    async def export_rows(self, chief_id: int, days: int | None):
        return await self._all(
            _TASK_SELECT + " WHERE t.chief_id=? AND t.created_at>=? ORDER BY t.id",
            (chief_id, self._since(days)),
        )

    async def workload(self, chief_id: int):
        """Сколько задач сейчас в работе у каждого прораба."""
        return await self._all(
            """
            SELECT u.tg_id, u.full_name, COALESCE(SUM(t.status='new'), 0) AS active
            FROM users u
            LEFT JOIN tasks t ON t.foreman_id = u.tg_id
            WHERE u.role='foreman' AND u.chief_id=? AND u.status='active'
            GROUP BY u.tg_id
            ORDER BY active DESC, u.full_name
            """,
            (chief_id,),
        )

    # ---------- служебное ----------
    async def meta_get(self, key: str) -> str | None:
        row = await self._one("SELECT value FROM meta WHERE key=?", (key,))
        return row["value"] if row else None

    async def meta_set(self, key: str, value: str) -> None:
        await self._exec(
            "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
