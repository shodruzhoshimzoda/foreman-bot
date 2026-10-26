from __future__ import annotations

import json
import time

import asyncpg

from bot.utils import since

ACTIVE = ("new",)                      # в работе у прораба
REPORTED = ("reported",)               # прораб нажал «Сделал», шеф ещё не одобрил
OPEN = ACTIVE + REPORTED               # всё, что шеф ещё может закрыть
CLOSED = ("done", "failed", "cancelled")

# Срок выполнения по важности: обычная — 1 месяц, важная — 7 дней, срочная — 1 день.
# Считается при создании задачи и хранится в tasks.due_at.
DUE_SQL = "CASE {p} WHEN 'urgent' THEN interval '1 day' WHEN 'high' THEN interval '7 days' ELSE interval '1 month' END"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    tg_id      BIGINT PRIMARY KEY,
    full_name  TEXT NOT NULL DEFAULT '',
    username   TEXT,
    role       TEXT NOT NULL CHECK (role IN ('chief', 'foreman')),
    status     TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('pending', 'active', 'blocked')),
    chief_id   BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_users_chief ON users (chief_id, status) WHERE role = 'foreman';

-- Задача = то, что прислал шеф: текст, фото, голосовое и т.п.
CREATE TABLE IF NOT EXISTS tasks (
    id          BIGSERIAL PRIMARY KEY,
    chief_id    BIGINT NOT NULL,
    foreman_id  BIGINT NOT NULL REFERENCES users (tg_id),
    kind        TEXT NOT NULL DEFAULT 'text'   CHECK (kind IN ('text', 'photo', 'voice', 'video', 'document')),
    file_id     TEXT,
    text        TEXT NOT NULL DEFAULT '',
    priority    TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('normal', 'high', 'urgent')),
    status      TEXT NOT NULL DEFAULT 'new'    CHECK (status IN ('new', 'reported', 'done', 'failed', 'cancelled')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at   TIMESTAMPTZ
);

-- превью фото (маленький размер) и длительность голосового — для дашборда; у старых задач пусты
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS thumb_id TEXT;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS duration INTEGER;
-- несколько фото/видео в одной задаче (альбом): [{kind, file_id, thumb_id, duration}, ...]; у обычных задач NULL
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS media JSONB;

-- срок выполнения (зависит от важности) и момент, когда прораб нажал «Сделал»
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS due_at TIMESTAMPTZ;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS reported_at TIMESTAMPTZ;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS accepted_at TIMESTAMPTZ;   -- прораб нажал «Принял»
UPDATE tasks SET due_at = created_at + CASE priority
        WHEN 'urgent' THEN interval '1 day' WHEN 'high' THEN interval '7 days' ELSE interval '1 month' END
    WHERE due_at IS NULL;

-- новый статус 'reported' в уже существующей базе: пересоздаём проверку, только если в ней его ещё нет
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'tasks'::regclass AND conname = 'tasks_status_check'
          AND pg_get_constraintdef(oid) LIKE '%reported%'
    ) THEN
        ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_status_check;
        ALTER TABLE tasks ADD CONSTRAINT tasks_status_check
            CHECK (status IN ('new', 'reported', 'done', 'failed', 'cancelled'));
    END IF;
END $$;

-- выборки по периоду (статистика, экспорт, дашборд)
CREATE INDEX IF NOT EXISTS idx_tasks_chief_created   ON tasks (chief_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_foreman_created ON tasks (foreman_id, created_at DESC);
-- лента задач в дашборде: постраничный просмотр «от новых к старым»
CREATE INDEX IF NOT EXISTS idx_tasks_chief_id        ON tasks (chief_id, id DESC);
-- «горячие» списки: задач в работе всегда мало, индекс по ним крошечный
CREATE INDEX IF NOT EXISTS idx_tasks_active_chief    ON tasks (chief_id, id) WHERE status = 'new';
CREATE INDEX IF NOT EXISTS idx_tasks_active_foreman  ON tasks (foreman_id)   WHERE status = 'new';
CREATE INDEX IF NOT EXISTS idx_tasks_reported_chief  ON tasks (chief_id, id) WHERE status = 'reported';

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

# сначала то, что ждёт одобрения шефа, затем по важности
_PRIORITY_ORDER = "(t.status = 'reported') DESC, CASE t.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 ELSE 2 END"

# Все счётчики за один проход по задачам: статусы, важность и вид сообщения.
_STATS_COLUMNS = """
    COUNT(t.id)                                     AS total,
    COUNT(*) FILTER (WHERE t.status = 'done')       AS done,
    COUNT(*) FILTER (WHERE t.status = 'failed')     AS failed,
    COUNT(*) FILTER (WHERE t.status = 'cancelled')  AS cancelled,
    COUNT(*) FILTER (WHERE t.status = 'new')        AS active,
    COUNT(*) FILTER (WHERE t.status = 'reported')   AS reported,
    (AVG(EXTRACT(EPOCH FROM (t.closed_at - t.created_at)) / 3600)
        FILTER (WHERE t.status = 'done'))::float8   AS avg_hours,
    COUNT(*) FILTER (WHERE t.priority = 'urgent')   AS prio_urgent,
    COUNT(*) FILTER (WHERE t.priority = 'high')     AS prio_high,
    COUNT(*) FILTER (WHERE t.priority = 'normal')   AS prio_normal,
    COUNT(*) FILTER (WHERE t.kind = 'text')         AS kind_text,
    COUNT(*) FILTER (WHERE t.kind = 'photo')        AS kind_photo,
    COUNT(*) FILTER (WHERE t.kind = 'voice')        AS kind_voice,
    COUNT(*) FILTER (WHERE t.kind = 'video')        AS kind_video,
    COUNT(*) FILTER (WHERE t.kind = 'document')     AS kind_document
"""


async def _init_connection(conn: asyncpg.Connection) -> None:
    # jsonb <-> объекты Python (по умолчанию asyncpg отдаёт строки)
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


class _RoleCache:
    """Кэш (роль, статус) пользователя: фильтры хендлеров спрашивают роль на каждый апдейт.

    Бот работает одним процессом и сам же меняет роли, поэтому достаточно
    точечной инвалидации при записи; TTL — страховка на случай правок в БД руками.
    """

    def __init__(self, ttl: float = 60.0, max_size: int = 5000):
        self._ttl = ttl
        self._max = max_size
        self._data: dict[int, tuple[float, tuple[str, str] | None]] = {}

    def get(self, key: int):
        hit = self._data.get(key)
        if hit and hit[0] > time.monotonic():
            return True, hit[1]
        return False, None

    def put(self, key: int, value) -> None:
        if len(self._data) >= self._max:
            self._data.clear()
        self._data[key] = (time.monotonic() + self._ttl, value)

    def drop(self, key: int) -> None:
        self._data.pop(key, None)


class Database:
    def __init__(self, dsn: str, schema: str | None = None, max_size: int = 10):
        self.dsn = dsn
        self.schema = schema  # отдельная схема — для тестов; в проде None (public)
        self.max_size = max_size
        self.pool: asyncpg.Pool | None = None
        self._roles = _RoleCache()

    async def connect(self) -> None:
        settings = None
        if self.schema:
            admin = await asyncpg.connect(self.dsn)
            try:
                await admin.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')
            finally:
                await admin.close()
            settings = {"search_path": self.schema}
        self.pool = await asyncpg.create_pool(
            self.dsn,
            min_size=1,
            max_size=self.max_size,
            command_timeout=30,
            server_settings=settings,
            init=_init_connection,
        )
        await self.pool.execute(SCHEMA)

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()

    # ---------- низкоуровневые помощники ----------
    async def _all(self, sql: str, *args) -> list[asyncpg.Record]:
        return await self.pool.fetch(sql, *args)

    async def _one(self, sql: str, *args) -> asyncpg.Record | None:
        return await self.pool.fetchrow(sql, *args)

    async def _exec(self, sql: str, *args) -> str:
        return await self.pool.execute(sql, *args)

    # ---------- пользователи ----------
    async def upsert_chief(self, tg_id: int, full_name: str = "Шеф", username: str | None = None) -> None:
        await self._exec(
            """
            INSERT INTO users (tg_id, full_name, username, role, status, chief_id)
            VALUES ($1, $2, $3, 'chief', 'active', NULL)
            ON CONFLICT (tg_id) DO UPDATE SET role='chief', status='active', chief_id=NULL
            """,
            tg_id, full_name, username,
        )
        self._roles.drop(tg_id)

    async def touch_user(self, tg_id: int, full_name: str, username: str | None) -> None:
        # не пишем в базу, если ничего не изменилось (/start нажимают часто)
        await self._exec(
            """
            UPDATE users SET full_name=$2, username=$3
            WHERE tg_id=$1 AND (full_name IS DISTINCT FROM $2 OR username IS DISTINCT FROM $3)
            """,
            tg_id, full_name, username,
        )

    async def get_user(self, tg_id: int):
        return await self._one("SELECT * FROM users WHERE tg_id=$1", tg_id)

    async def get_role(self, tg_id: int) -> tuple[str, str] | None:
        """(role, status) или None — с кэшем."""
        found, value = self._roles.get(tg_id)
        if found:
            return value
        row = await self._one("SELECT role, status FROM users WHERE tg_id=$1", tg_id)
        value = (row["role"], row["status"]) if row else None
        self._roles.put(tg_id, value)
        return value

    async def is_chief(self, tg_id: int) -> bool:
        role = await self.get_role(tg_id)
        return role is not None and role[0] == "chief"

    async def is_active_foreman(self, tg_id: int) -> bool:
        return await self.get_role(tg_id) == ("foreman", "active")

    async def register_foreman(self, tg_id: int, full_name: str, username: str | None, chief_id: int) -> None:
        await self._exec(
            """
            INSERT INTO users (tg_id, full_name, username, role, status, chief_id)
            VALUES ($1, $2, $3, 'foreman', 'pending', $4)
            """,
            tg_id, full_name, username, chief_id,
        )
        self._roles.drop(tg_id)

    async def set_user_status(self, tg_id: int, status: str) -> None:
        await self._exec("UPDATE users SET status=$2 WHERE tg_id=$1", tg_id, status)
        self._roles.drop(tg_id)

    async def delete_user(self, tg_id: int) -> None:
        # удаляем только неподтверждённые заявки — у активных прорабов есть история задач
        await self._exec("DELETE FROM users WHERE tg_id=$1 AND role='foreman' AND status='pending'", tg_id)
        self._roles.drop(tg_id)

    async def list_foremen(self, chief_id: int, status: str = "active"):
        return await self._all(
            """
            SELECT u.*, COUNT(t.id) AS active_cnt
            FROM users u
            LEFT JOIN tasks t ON t.foreman_id = u.tg_id AND t.status = 'new'
            WHERE u.role = 'foreman' AND u.chief_id = $1 AND u.status = $2
            GROUP BY u.tg_id
            ORDER BY u.full_name
            """,
            chief_id, status,
        )

    async def list_chiefs(self):
        return await self._all("SELECT * FROM users WHERE role='chief' AND status='active'")

    # ---------- задачи ----------
    async def create_tasks(
        self,
        chief_id: int,
        foreman_ids: list[int],
        kind: str,
        file_id: str | None,
        text: str,
        priority: str,
        thumb_id: str | None = None,
        duration: int | None = None,
        media: list[dict] | None = None,
    ) -> list[asyncpg.Record]:
        """Создаёт по задаче на каждого прораба одним запросом и возвращает их сразу с именами."""
        return await self._all(
            """
            WITH ins AS (
                INSERT INTO tasks (chief_id, foreman_id, kind, file_id, text, priority, thumb_id, duration, media, due_at)
                SELECT $1, fid, $3, $4, $5, $6, $7, $8, $9::jsonb, now() + """ + DUE_SQL.format(p="$6::text") + """
                FROM unnest($2::bigint[]) AS fid
                RETURNING *
            )
            SELECT t.*, f.full_name AS foreman_name
            FROM ins t JOIN users f ON f.tg_id = t.foreman_id
            ORDER BY t.id
            """,
            chief_id, foreman_ids, kind, file_id, text, priority, thumb_id, duration, media or None,
        )

    async def create_task(
        self, chief_id: int, foreman_id: int, kind: str, file_id: str | None, text: str, priority: str
    ) -> int:
        rows = await self.create_tasks(chief_id, [foreman_id], kind, file_id, text, priority)
        return rows[0]["id"]

    async def get_task(self, task_id: int):
        return await self._one(_TASK_SELECT + " WHERE t.id=$1", task_id)

    async def list_tasks(
        self,
        *,
        chief_id: int | None = None,
        foreman_id: int | None = None,
        statuses: tuple[str, ...] = ACTIVE,
        limit: int = 30,
    ):
        sql = _TASK_SELECT + " WHERE t.status = ANY($1::text[])"
        params: list = [list(statuses)]
        if chief_id is not None:
            params.append(chief_id)
            sql += f" AND t.chief_id=${len(params)}"
        if foreman_id is not None:
            params.append(foreman_id)
            sql += f" AND t.foreman_id=${len(params)}"
        params.append(limit)
        sql += f" ORDER BY {_PRIORITY_ORDER}, t.id LIMIT ${len(params)}"
        return await self._all(sql, *params)

    async def recent_tasks(self, foreman_id: int, days: int | None, limit: int = 10):
        return await self._all(
            _TASK_SELECT + " WHERE t.foreman_id=$1 AND t.created_at>=$2 ORDER BY t.id DESC LIMIT $3",
            foreman_id, since(days), limit,
        )

    async def transition(self, task_id: int, to: str, allowed_from: tuple[str, ...] = OPEN) -> bool:
        """Атомарно меняет статус (по умолчанию закрыть может шеф: из «в работе» или «ждёт одобрения»).
        False — если задача уже в другом статусе."""
        row = await self._one(
            """
            UPDATE tasks
            SET status = $2,
                closed_at = CASE WHEN $2 = ANY($4::text[]) THEN now() ELSE closed_at END
            WHERE id = $1 AND status = ANY($3::text[])
            RETURNING id
            """,
            task_id, to, list(allowed_from), list(CLOSED),
        )
        return row is not None

    async def reopen(self, task_id: int) -> bool:
        """Возвращает в работу закрытую задачу (исправление ошибочной отметки) или ту, что прораб отметил
        «сделал», а шеф не принял. False — если она уже в работе."""
        row = await self._one(
            """
            UPDATE tasks SET status='new', closed_at=NULL, reported_at=NULL
            WHERE id=$1 AND status = ANY($2::text[]) RETURNING id
            """,
            task_id, list(CLOSED + REPORTED),
        )
        return row is not None

    async def accept(self, task_id: int, foreman_id: int) -> bool:
        """Прораб нажал «Принял». False — задачи нет, она не его, уже принята или уже не «в работе»."""
        row = await self._one(
            """
            UPDATE tasks SET accepted_at=now()
            WHERE id=$1 AND foreman_id=$2 AND status='new' AND accepted_at IS NULL RETURNING id
            """,
            task_id, foreman_id,
        )
        return row is not None

    async def report_done(self, task_id: int, foreman_id: int) -> bool:
        """Прораб нажал «Сделал»: задача ждёт одобрения шефа. False — задачи нет, она не его или уже не «в работе»."""
        row = await self._one(
            """
            UPDATE tasks SET status='reported', reported_at=now(), accepted_at=COALESCE(accepted_at, now())
            WHERE id=$1 AND foreman_id=$2 AND status='new' RETURNING id
            """,
            task_id, foreman_id,
        )
        return row is not None

    # ---------- аналитика ----------
    async def stats(
        self,
        *,
        chief_id: int | None = None,
        foreman_id: int | None = None,
        days: int | None = None,
    ):
        """Сводка по прорабам за период (по дате создания задачи)."""
        params: list = [since(days)]
        where = ["u.role = 'foreman'"]
        if chief_id is not None:
            params.append(chief_id)
            where.append(f"u.chief_id = ${len(params)}")
        if foreman_id is not None:
            params.append(foreman_id)
            where.append(f"u.tg_id = ${len(params)}")
        else:
            where.append("u.status = 'active'")
        return await self._all(
            f"""
            SELECT u.tg_id, u.full_name, {_STATS_COLUMNS}
            FROM users u
            LEFT JOIN tasks t ON t.foreman_id = u.tg_id AND t.created_at >= $1
            WHERE {' AND '.join(where)}
            GROUP BY u.tg_id
            ORDER BY total DESC, u.full_name
            """,
            *params,
        )

    async def export_rows(self, chief_id: int, days: int | None):
        return await self._all(
            _TASK_SELECT + " WHERE t.chief_id=$1 AND t.created_at>=$2 ORDER BY t.id",
            chief_id, since(days),
        )

    async def workload_all(self):
        """Сколько задач в работе у каждого прораба — по всем шефам сразу (для утренней сводки)."""
        return await self._all(
            """
            SELECT u.chief_id, u.tg_id, u.full_name,
                   COUNT(t.id) FILTER (WHERE t.status = 'new')                           AS active,
                   COUNT(t.id) FILTER (WHERE t.status = 'reported')                      AS reported,
                   COUNT(t.id) FILTER (WHERE t.status = 'new' AND t.accepted_at IS NULL) AS not_accepted
            FROM users u
            LEFT JOIN tasks t ON t.foreman_id = u.tg_id AND t.status IN ('new', 'reported')
            WHERE u.role = 'foreman' AND u.status = 'active' AND u.chief_id IS NOT NULL
            GROUP BY u.tg_id
            ORDER BY u.chief_id, active DESC, u.full_name
            """
        )

    async def foreman_digest_rows(self):
        """Незакрытые задачи (в работе и ждущие одобрения) всех активных прорабов — для их ежедневной сводки."""
        return await self._all(
            """
            SELECT t.id, t.foreman_id, t.kind, t.text, t.media, t.priority, t.status, t.created_at, t.due_at, t.accepted_at,
                   f.full_name AS foreman_name
            FROM tasks t
            JOIN users f ON f.tg_id = t.foreman_id
            WHERE t.status IN ('new', 'reported') AND f.role = 'foreman' AND f.status = 'active'
            ORDER BY t.foreman_id, (t.status = 'reported'),
                     CASE t.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 ELSE 2 END, t.due_at NULLS LAST, t.id
            """
        )

    # ---------- данные для дашборда ----------
    async def daily_series(self, chief_id: int, start, tz: str):
        """Задачи по дням (локальная дата), начиная с момента `start`."""
        return await self._all(
            """
            SELECT (t.created_at AT TIME ZONE $3)::date AS day,
                   COUNT(*)                                       AS total,
                   COUNT(*) FILTER (WHERE t.status = 'done')      AS done,
                   COUNT(*) FILTER (WHERE t.status = 'failed')    AS failed,
                   COUNT(*) FILTER (WHERE t.status = 'cancelled') AS cancelled,
                   COUNT(*) FILTER (WHERE t.status = 'new')       AS active,
                   COUNT(*) FILTER (WHERE t.status = 'reported')  AS reported
            FROM tasks t
            WHERE t.chief_id = $1 AND t.created_at >= $2
            GROUP BY 1
            ORDER BY 1
            """,
            chief_id, start, tz,
        )

    async def recent_for_chief(self, chief_id: int, days: int | None, limit: int = 20):
        return await self._all(
            _TASK_SELECT + " WHERE t.chief_id=$1 AND t.created_at>=$2 ORDER BY t.id DESC LIMIT $3",
            chief_id, since(days), limit,
        )

    async def tasks_page(
        self,
        chief_id: int,
        *,
        status: str | None = None,
        foreman_id: int | None = None,
        before_id: int | None = None,
        limit: int = 20,
    ):
        """Лента задач шефа, новые сверху. Постраничность по id (keyset): не замедляется на глубоких страницах."""
        params: list = [chief_id]
        where = ["t.chief_id = $1"]
        for cond, value in (
            ("t.status = ${}", status),
            ("t.foreman_id = ${}", foreman_id),
            ("t.id < ${}", before_id),
        ):
            if value is not None:
                params.append(value)
                where.append(cond.format(len(params)))
        params.append(limit)
        return await self._all(
            _TASK_SELECT + f" WHERE {' AND '.join(where)} ORDER BY t.id DESC LIMIT ${len(params)}",
            *params,
        )

    async def active_count(self, chief_id: int) -> int:
        """Сколько задач в работе сейчас — независимо от выбранного периода (частичный индекс)."""
        return await self.pool.fetchval("SELECT COUNT(*) FROM tasks WHERE chief_id=$1 AND status='new'", chief_id)

    async def reported_count(self, chief_id: int) -> int:
        """Сколько задач прораб уже сделал, но шеф ещё не одобрил — независимо от периода."""
        return await self.pool.fetchval("SELECT COUNT(*) FROM tasks WHERE chief_id=$1 AND status='reported'", chief_id)

    async def stale_active(self, chief_id: int, limit: int = 5):
        """Дольше всего висящие задачи в работе."""
        return await self._all(
            _TASK_SELECT + " WHERE t.chief_id=$1 AND t.status='new' ORDER BY t.id LIMIT $2",
            chief_id, limit,
        )

    # ---------- служебное ----------
    async def meta_get(self, key: str) -> str | None:
        row = await self._one("SELECT value FROM meta WHERE key=$1", key)
        return row["value"] if row else None

    async def meta_set(self, key: str, value: str) -> None:
        await self._exec(
            "INSERT INTO meta (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value",
            key, value,
        )
