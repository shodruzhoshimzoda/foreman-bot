"""HTTP-часть: JSON API для дашборда + раздача собранного React-приложения.

Работает в том же event loop, что и бот, и использует тот же пул соединений к PostgreSQL.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiohttp import web

from bot.config import Config
from bot.db import Database
from bot.web.auth import AuthError, validate_init_data
from bot.web.media import MediaError, MediaStore, MediaUnavailable

log = logging.getLogger(__name__)

PERIODS = (7, 30, 0)          # 0 — всё время
CHART_MAX_DAYS = 90           # график по дням не длиннее 90 дней
CACHE_TTL = 5.0               # секунд: защита от «дёрганья» обновления
KINDS = ("text", "photo", "voice", "video", "document")
STATUSES = ("new", "reported", "done", "failed", "cancelled")

DB = web.AppKey("db", Database)
CFG = web.AppKey("config", Config)
CACHE = web.AppKey("cache", dict)
MEDIA = web.AppKey("media", MediaStore)

TASKS_PAGE = 20
RECENT_ON_OVERVIEW = 6
MEDIA_KINDS = ("photo", "voice")


def _pct(done: int, failed: int) -> int | None:
    closed = done + failed
    return round(done / closed * 100) if closed else None


def _task(t, media: MediaStore | None = None, full: bool = False) -> dict:
    # в списках текст сжат до одной строки и обрезан; в панели задачи — целиком и с переносами строк
    text = (t["text"] or "").strip() if full else " ".join((t["text"] or "").split())
    out = {
        "id": t["id"],
        "foreman_id": t["foreman_id"],
        "foreman": t["foreman_name"],
        "kind": t["kind"],
        "priority": t["priority"],
        "status": t["status"],
        "text": text if full else text[:600] + ("…" if len(text) > 600 else ""),
        "created_at": t["created_at"].isoformat(),
        "closed_at": t["closed_at"].isoformat() if t["closed_at"] else None,
        "due_at": t["due_at"].isoformat() if t["due_at"] else None,
        "reported_at": t["reported_at"].isoformat() if t["reported_at"] else None,
        "accepted_at": t["accepted_at"].isoformat() if t["accepted_at"] else None,
        "media": None,
        "album": 0,
    }
    items = t["media"] if t["media"] and len(t["media"]) > 1 else None
    if items:
        out["album"] = len(items)
    if media and items:
        # альбом: у всех вложений одна подписанная ссылка, нужное выбирается параметром ?i=<номер>
        if any(i["kind"] == "photo" for i in items):
            out["media"] = {"url": media.url(t["id"]), "duration": None, "items": [{"kind": i["kind"]} for i in items]}
    elif media and t["kind"] in MEDIA_KINDS and t["file_id"]:
        out["media"] = {"url": media.url(t["id"]), "duration": t["duration"], "items": None}
    return out


def _foreman(r) -> dict:
    return {
        "id": r["tg_id"],
        "name": r["full_name"],
        "total": r["total"],
        "done": r["done"],
        "failed": r["failed"],
        "cancelled": r["cancelled"],
        "active": r["active"],
        "reported": r["reported"],
        "completion": _pct(r["done"], r["failed"]),
        "avg_hours": r["avg_hours"],
        "priority": {"urgent": r["prio_urgent"], "high": r["prio_high"], "normal": r["prio_normal"]},
        "kinds": {k: r[f"kind_{k}"] for k in KINDS},
    }


def _fill_days(rows, first, last) -> list[dict]:
    by_day = {r["day"]: r for r in rows}
    out, d = [], first
    while d <= last:
        r = by_day.get(d)
        out.append(
            {
                "date": d.isoformat(),
                "total": r["total"] if r else 0,
                "done": r["done"] if r else 0,
                "failed": r["failed"] if r else 0,
                "cancelled": r["cancelled"] if r else 0,
                "active": r["active"] if r else 0,
                "reported": r["reported"] if r else 0,
            }
        )
        d += timedelta(days=1)
    return out


async def build_dashboard(
    db: Database, config: Config, chief_id: int, days: int, media: MediaStore | None = None
) -> dict:
    tz = ZoneInfo(config.tz)
    chart_days = min(days or CHART_MAX_DAYS, CHART_MAX_DAYS)
    today = datetime.now(tz).date()
    first_day = today - timedelta(days=chart_days - 1)
    chart_start = datetime.combine(first_day, datetime.min.time(), tzinfo=tz)

    # независимые запросы идут параллельно, каждый на своём соединении из пула
    stats, daily, recent, stale, active_now, reported_now, awaiting = await asyncio.gather(
        db.stats(chief_id=chief_id, days=days or None),
        db.daily_series(chief_id, chart_start, config.tz),
        db.recent_for_chief(chief_id, days or None, limit=RECENT_ON_OVERVIEW),
        db.stale_active(chief_id, limit=5),
        db.active_count(chief_id),
        db.reported_count(chief_id),
        db.tasks_page(chief_id, status="reported", limit=5),
    )

    foremen = [_foreman(r) for r in stats]
    totals = {k: sum(f[k] for f in foremen) for k in ("total", "done", "failed", "cancelled", "active", "reported")}
    done_w = sum(f["done"] for f in foremen if f["avg_hours"] is not None)
    avg = (
        sum(f["avg_hours"] * f["done"] for f in foremen if f["avg_hours"] is not None) / done_w if done_w else None
    )
    return {
        "tz": config.tz,
        "days": days,
        "generated_at": datetime.now(tz).isoformat(),
        "summary": {
            **totals,
            "completion": _pct(totals["done"], totals["failed"]),
            "avg_hours": avg,
            "foremen": len(foremen),
            "active_now": active_now,
            "reported_now": reported_now,
        },
        "by_priority": {p: sum(f["priority"][p] for f in foremen) for p in ("urgent", "high", "normal")},
        "by_kind": {k: sum(f["kinds"][k] for f in foremen) for k in KINDS},
        "foremen": foremen,
        "daily": _fill_days(daily, first_day, today),
        "daily_days": chart_days,
        "recent": [_task(t, media) for t in recent],
        "stale": [_task(t, media) for t in stale],
        "awaiting": [_task(t, media) for t in awaiting],
        "media_enabled": media is not None,
    }


# ------------------------------------------------------------------ handlers
async def _auth_chief(request: web.Request) -> int:
    header = request.headers.get("Authorization", "")
    if not header.startswith("tma "):
        raise web.HTTPUnauthorized(text="missing Telegram credentials")
    try:
        user_id = validate_init_data(header[4:], request.app[CFG].bot_token)
    except AuthError as e:
        log.info("Отклонён вход в дашборд: %s", e)
        raise web.HTTPUnauthorized(text="invalid Telegram credentials")
    if not await request.app[DB].is_chief(user_id):
        raise web.HTTPForbidden(text="dashboard is for chiefs only")
    return user_id


async def dashboard(request: web.Request) -> web.Response:
    chief_id = await _auth_chief(request)
    try:
        days = int(request.query.get("days", "7"))
    except ValueError:
        days = -1
    if days not in PERIODS:
        raise web.HTTPBadRequest(text="days must be one of 7, 30, 0")

    cache = request.app[CACHE]
    key = (chief_id, days)
    hit = cache.get(key)
    if hit and hit[0] > time.monotonic():
        data = hit[1]
    else:
        data = await build_dashboard(request.app[DB], request.app[CFG], chief_id, days, request.app.get(MEDIA))
        if len(cache) > 200:
            cache.clear()
        cache[key] = (time.monotonic() + CACHE_TTL, data)

    resp = web.json_response(data, headers={"Cache-Control": "no-store"})
    resp.enable_compression()
    return resp


async def tasks_feed(request: web.Request) -> web.Response:
    """Лента задач: GET /api/tasks?status=done&foreman=123&before=<id>&limit=20 (новые сверху)."""
    chief_id = await _auth_chief(request)
    q = request.query
    status = q.get("status") or None
    if status in ("all", ""):
        status = None
    if status is not None and status not in STATUSES:
        raise web.HTTPBadRequest(text="bad status")
    try:
        foreman = int(q["foreman"]) if q.get("foreman") else None
        before = int(q["before"]) if q.get("before") else None
        limit = min(max(int(q.get("limit", TASKS_PAGE)), 1), 50)
    except ValueError:
        raise web.HTTPBadRequest(text="bad number")

    # берём на одну больше, чтобы узнать, есть ли следующая страница
    rows = await request.app[DB].tasks_page(
        chief_id, status=status, foreman_id=foreman, before_id=before, limit=limit + 1
    )
    more = len(rows) > limit
    rows = rows[:limit]
    media = request.app.get(MEDIA)
    resp = web.json_response(
        {"tasks": [_task(t, media) for t in rows], "next": rows[-1]["id"] if more else None},
        headers={"Cache-Control": "no-store"},
    )
    resp.enable_compression()
    return resp


CLOSING = ("done", "failed", "cancelled")


async def task_detail(request: web.Request) -> web.Response:
    """Одна задача целиком (для панели задачи): полный текст и все вложения. Чужие задачи — 404."""
    chief_id = await _auth_chief(request)
    try:
        task_id = int(request.match_info["task_id"])
    except ValueError:
        raise web.HTTPNotFound()
    task = await request.app[DB].get_task(task_id)
    if not task or task["chief_id"] != chief_id:
        raise web.HTTPNotFound(text="task not found")
    resp = web.json_response({"task": _task(task, request.app.get(MEDIA), full=True)}, headers={"Cache-Control": "no-store"})
    resp.enable_compression()
    return resp


async def set_task_status(request: web.Request) -> web.Response:
    """Шеф отмечает результат прямо из дашборда: POST /api/tasks/{id}/status {"status": "done|failed|cancelled|new"}.

    Те же правила, что у кнопок в боте: закрыть можно задачу «в работе» или ту, что прораб отметил «сделал»
    (так шеф её одобряет). Дополнительно — «new»: вернуть в работу закрытую или не принятую задачу.
    Прорабу, как и в боте, ничего не отправляется.
    """
    chief_id = await _auth_chief(request)
    try:
        task_id = int(request.match_info["task_id"])
        to = (await request.json()).get("status")
    except (ValueError, TypeError, AttributeError):
        raise web.HTTPBadRequest(text="bad request")
    if to not in CLOSING + ("new",):
        raise web.HTTPBadRequest(text="bad status")

    db = request.app[DB]
    task = await db.get_task(task_id)
    if not task or task["chief_id"] != chief_id:      # чужие задачи — «не найдено», а не «запрещено»
        raise web.HTTPNotFound(text="task not found")

    changed = await (db.reopen(task_id) if to == "new" else db.transition(task_id, to))
    task = await db.get_task(task_id)
    payload = {"task": _task(task, request.app.get(MEDIA))}
    if not changed:                                   # статус уже изменили (например, из бота) — отдаём актуальный
        return web.json_response({"error": "conflict", **payload}, status=409)

    cache = request.app[CACHE]                        # данные дашборда изменились — не отдаём устаревший кэш
    for key in [k for k in cache if k[0] == chief_id]:
        del cache[key]
    return web.json_response(payload, headers={"Cache-Control": "no-store"})


def _media_item(t, index: int):
    """(вид, file_id, превью) вложения №index: у альбома — из списка, у обычной задачи есть только №0."""
    items = t["media"]
    if items and len(items) > 1:
        if not 0 <= index < len(items):
            return None
        it = items[index]
        return it["kind"], it["file_id"], it.get("thumb_id")
    if index != 0 or not t["file_id"]:
        return None
    return t["kind"], t["file_id"], t["thumb_id"]


async def media_file(request: web.Request) -> web.StreamResponse:
    """Фото / голосовое задачи. Доступ — по подписанной ссылке из данных дашборда."""
    store = request.app.get(MEDIA)
    if store is None:
        raise web.HTTPNotFound()
    try:
        task_id = int(request.match_info["task_id"])
    except ValueError:
        raise web.HTTPNotFound()
    if not store.verify(task_id, request.query.get("exp", ""), request.query.get("sig", "")):
        raise web.HTTPForbidden(text="link expired")

    try:
        index = int(request.query.get("i", "0"))
    except ValueError:
        raise web.HTTPNotFound()
    t = await request.app[DB].get_task(task_id)
    item = _media_item(t, index) if t else None
    if item is None or item[0] not in MEDIA_KINDS:        # нет такого вложения, либо это видео
        raise web.HTTPNotFound()
    kind, full_id, thumb_id = item

    thumb = request.query.get("v") == "thumb" and kind == "photo"
    file_id = (thumb_id or full_id) if thumb else full_id
    try:
        if kind == "voice" and request.query.get("fmt") == "m4a":
            path, ctype = await store.fetch_m4a(file_id), "audio/mp4"
        else:
            path = await store.fetch(file_id, kind)
            ctype = "image/jpeg" if kind == "photo" else "audio/ogg"
    except MediaUnavailable as e:
        log.info("Медиа задачи %s недоступно: %s", task_id, e)
        raise web.HTTPNotFound()
    except MediaError as e:
        log.warning("Сбой загрузки медиа задачи %s: %s", task_id, e)
        raise web.HTTPBadGateway()

    # FileResponse умеет Range (нужен iOS для <audio>), ETag и Last-Modified
    resp = web.FileResponse(path, headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"})
    resp.content_type = ctype
    return resp


async def healthz(request: web.Request) -> web.Response:
    await request.app[DB].pool.fetchval("SELECT 1")
    return web.json_response({"ok": True})


def _static_handler(root: Path):
    root = root.resolve()
    index = root / "index.html"

    async def handle(request: web.Request) -> web.StreamResponse:
        rel = request.match_info.get("path", "")
        target = (root / rel).resolve()
        if rel and target.is_file() and root in target.parents:
            immutable = rel.startswith("assets/")  # имена файлов Vite содержат хеш содержимого
            cc = "public, max-age=31536000, immutable" if immutable else "no-cache"
            return web.FileResponse(target, headers={"Cache-Control": cc, "X-Content-Type-Options": "nosniff"})
        # SPA: всё остальное — index.html
        return web.FileResponse(index, headers={"Cache-Control": "no-cache"})

    return handle


def build_web_app(
    db: Database, config: Config, static_dir: Path | None = None, bot: Bot | None = None
) -> web.Application:
    app = web.Application()
    app[DB], app[CFG], app[CACHE] = db, config, {}
    if bot is not None:
        store = MediaStore(bot, config.media_cache_dir, config.media_cache_mb, config.bot_token)
        app[MEDIA] = store
        if not store.ffmpeg:
            log.warning("ffmpeg не найден: голосовые не будут играть на iOS (apt install ffmpeg)")
        app.on_startup.append(lambda _: asyncio.to_thread(store.prune))
    app.router.add_get("/api/dashboard", dashboard)
    app.router.add_get("/api/tasks", tasks_feed)
    app.router.add_get("/api/tasks/{task_id}", task_detail)
    app.router.add_post("/api/tasks/{task_id}/status", set_task_status)
    app.router.add_get("/api/media/{task_id}", media_file)
    app.router.add_get("/healthz", healthz)
    if static_dir and (static_dir / "index.html").is_file():
        app.router.add_get("/{path:.*}", _static_handler(static_dir))
    else:
        log.warning("Сборка дашборда не найдена (%s). Выполните: cd webapp && npm ci && npm run build", static_dir)
    return app


async def start_web(app: web.Application, host: str, port: int) -> web.AppRunner:
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    log.info("Дашборд слушает http://%s:%s", host, port)
    return runner

