"""Перенос данных из старой SQLite-базы в PostgreSQL.

    python -m scripts.migrate_sqlite_to_pg path/to/bot.db            # DATABASE_URL берётся из .env
    python -m scripts.migrate_sqlite_to_pg path/to/bot.db --dsn postgresql://...

Безопасно запускать повторно: уже перенесённые строки пропускаются (ON CONFLICT DO NOTHING).
ID задач сохраняются, поэтому номера «#12» в уже отправленных сообщениях остаются верными.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
from datetime import datetime, timezone

from dotenv import load_dotenv

from bot.db import Database


def _ts(s: str | None) -> datetime | None:
    # в SQLite даты лежали как "YYYY-MM-DD HH:MM:SS" в UTC
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc) if s else None


async def migrate(sqlite_path: str, dsn: str, schema: str | None = None) -> dict[str, int]:
    src = sqlite3.connect(sqlite_path)
    src.row_factory = sqlite3.Row
    tables = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    report = {"users": 0, "tasks": 0, "tasks_skipped": 0, "meta": 0}

    db = Database(dsn, schema=schema)
    await db.connect()
    try:
        async with db.pool.acquire() as conn, conn.transaction():
            if "users" in tables:
                users = [
                    (r["tg_id"], r["full_name"] or "", r["username"], r["role"], r["status"], r["chief_id"], _ts(r["created_at"]))
                    for r in src.execute("SELECT * FROM users")
                ]
                await conn.executemany(
                    """INSERT INTO users (tg_id, full_name, username, role, status, chief_id, created_at)
                       VALUES ($1,$2,$3,$4,$5,$6,$7) ON CONFLICT (tg_id) DO NOTHING""",
                    users,
                )
                report["users"] = len(users)

            task_cols = {r[1] for r in src.execute("PRAGMA table_info(tasks)")} if "tasks" in tables else set()
            if "kind" in task_cols:
                known = {r["tg_id"] for r in await conn.fetch("SELECT tg_id FROM users")}
                rows, skipped = [], 0
                for r in src.execute("SELECT * FROM tasks ORDER BY id"):
                    if r["foreman_id"] not in known:
                        skipped += 1
                        continue
                    rows.append(
                        (r["id"], r["chief_id"], r["foreman_id"], r["kind"], r["file_id"], r["text"] or "",
                         r["priority"], r["status"], _ts(r["created_at"]), _ts(r["closed_at"]))
                    )
                await conn.executemany(
                    """INSERT INTO tasks (id, chief_id, foreman_id, kind, file_id, text, priority, status, created_at, closed_at)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) ON CONFLICT (id) DO NOTHING""",
                    rows,
                )
                report["tasks"], report["tasks_skipped"] = len(rows), skipped
                # последовательность id должна продолжаться после максимального перенесённого
                await conn.execute(
                    "SELECT setval(pg_get_serial_sequence('tasks', 'id'), GREATEST((SELECT COALESCE(MAX(id), 1) FROM tasks), 1))"
                )
            elif "tasks" in tables:
                print("! В SQLite старая схема задач (без поля kind) — они лежали в tasks_legacy и в статистику не входили; пропускаю.")

            if "meta" in tables:
                meta = [(r["key"], r["value"]) for r in src.execute("SELECT * FROM meta")]
                await conn.executemany(
                    "INSERT INTO meta (key, value) VALUES ($1,$2) ON CONFLICT (key) DO NOTHING", meta
                )
                report["meta"] = len(meta)
    finally:
        await db.close()
        src.close()
    return report


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sqlite_path")
    ap.add_argument("--dsn", default=os.getenv("DATABASE_URL", ""))
    args = ap.parse_args()
    if not args.dsn:
        raise SystemExit("Укажите --dsn или DATABASE_URL в .env")
    if not os.path.exists(args.sqlite_path):
        raise SystemExit(f"Файл не найден: {args.sqlite_path}")
    rep = asyncio.run(migrate(args.sqlite_path, args.dsn))
    print("Готово:", ", ".join(f"{k}={v}" for k, v in rep.items()))


if __name__ == "__main__":
    main()
