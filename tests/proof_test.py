"""
Фото результата от прораба: хранение отчётов и показ в дашборде («Подробнее о задаче»).

    TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/postgres python -m tests.proof_test
"""
import asyncio
import os
import tempfile
import uuid

import asyncpg
from aiohttp.test_utils import TestClient, TestServer

from bot.config import Config
from bot.db import Database
from bot.web.media import MediaStore
from bot.web.server import build_web_app
from tests.media_test import FakeBot, make_ogg
from tests.smoke_test import TOKEN, TZ, sign_init_data

CHIEF, OTHER, F1, F2, F3 = 7_113_457_025, 2, 10, 11, 20


def photos(*ids):
    return [{"kind": "photo", "file_id": f, "thumb_id": f + "_T"} for f in ids]


async def main() -> None:
    dsn = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("Задайте TEST_DATABASE_URL")
    schema = "p_" + uuid.uuid4().hex[:8]
    db = Database(dsn, schema=schema)
    await db.connect()
    try:
        await run(db, dsn)
    finally:
        await db.close()
        c = await asyncpg.connect(dsn)
        await c.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await c.close()
    print("OK: фото результата сохраняются и показываются в дашборде")


async def run(db: Database, dsn: str) -> None:
    await db.upsert_chief(CHIEF, "Шеф")
    await db.upsert_chief(OTHER, "Другой")
    for fid, name, chief in ((F1, "Иванов", CHIEF), (F2, "Петров", CHIEF), (F3, "Чужой", OTHER)):
        await db.register_foreman(fid, name, None, chief)
        await db.set_user_status(fid, "active")
    mk = lambda chief, f, text: db.create_tasks(chief, [f], "text", None, text, "normal")

    # ---------------- база: submit_report
    a = (await mk(CHIEF, F1, "две фото"))[0]["id"]
    b = (await mk(CHIEF, F1, "одно фото"))[0]["id"]
    c = (await mk(CHIEF, F1, "только описание"))[0]["id"]
    d = (await mk(CHIEF, F1, "без ничего"))[0]["id"]
    e = (await mk(CHIEF, F2, "чужого прораба"))[0]["id"]
    o = (await mk(OTHER, F3, "задача другого шефа"))[0]["id"]

    assert await db.submit_report(e, F1, "x", []) == (False, None)                 # не его задача
    assert (await db.get_task(e))["status"] == "new"
    ok, ra = await db.submit_report(a, F1, "сделал два", photos("A1", "A2"))
    assert ok and ra
    assert await db.submit_report(a, F1, "ещё раз", photos("A3")) == (False, None)  # уже не «в работе»
    ok, rb = await db.submit_report(b, F1, "", photos("B1"))
    ok2, rc = await db.submit_report(c, F1, "всё хорошо", [])
    ok3, rd = await db.submit_report(d, F1, "", [])
    assert ok and ok2 and ok3 and rb and rc and rd is None                           # без фото и описания отчёта нет
    for t in (a, b, c, d):
        got = await db.get_task(t)
        assert got["status"] == "reported" and got["reported_at"] and got["accepted_at"]
    assert (await db.get_task(a))["has_report_photos"] and (await db.get_task(b))["has_report_photos"]
    assert not (await db.get_task(c))["has_report_photos"] and not (await db.get_task(d))["has_report_photos"]
    assert [r["id"] for r in await db.reports_for_task(a)] == [ra] and await db.reports_for_task(d) == []
    rep = await db.get_report(ra)
    assert rep["media"] == photos("A1", "A2") and rep["caption"] == "сделал два"      # JSONB читается как список

    # возврат в работу и повторный отчёт: отчёты копятся по порядку
    assert await db.reopen(a)
    ok, ra2 = await db.submit_report(a, F1, "переделал", photos("A9"))
    assert ok and [r["id"] for r in await db.reports_for_task(a)] == [ra, ra2]
    # откат транзакции: задача закрыта шефом — статус и отчёты не меняются
    assert await db.transition(c, "failed") and await db.reopen(c)
    await db.transition(c, "cancelled")
    assert await db.submit_report(c, F1, "поздно", photos("C1")) == (False, None)
    assert len(await db.reports_for_task(c)) == 1

    # ---------------- дашборд
    bot = FakeBot(make_ogg())
    cfg = Config(TOKEN, (CHIEF, OTHER), dsn, TZ, 8, media_cache_dir=tempfile.mkdtemp(), media_cache_mb=500)
    app = build_web_app(db, cfg, bot=bot)
    store = next(v for v in app.values() if isinstance(v, MediaStore))
    client = TestClient(TestServer(app))
    await client.start_server()
    h = lambda uid: {"Authorization": "tma " + sign_init_data(uid)}
    get = lambda path, uid=CHIEF: client.get(path, headers=h(uid))
    try:
        # карточки: пометка «есть фото результата»
        feed = {t["id"]: t for t in (await (await get("/api/tasks?limit=50")).json())["tasks"]}
        assert feed[a]["report_photos"] and feed[b]["report_photos"]
        assert not feed[c]["report_photos"] and not feed[d]["report_photos"]
        assert "reports" not in feed[a]                                      # в списке отчётов нет — они в «подробнее»

        # подробнее о задаче: отчёты, фото — по подписанным ссылкам с номером отчёта
        det = (await (await get(f"/api/tasks/{a}")).json())["task"]
        assert [r["id"] for r in det["reports"]] == [ra, ra2]
        first, second = det["reports"]
        assert first["caption"] == "сделал два" and first["created_at"]
        assert [i["kind"] for i in first["media"]["items"]] == ["photo", "photo"]
        assert first["media"]["url"].startswith(f"/api/media/{a}?exp=") and first["media"]["url"].endswith(f"&r={ra}")
        assert second["media"]["items"] is None and second["media"]["url"].endswith(f"&r={ra2}")   # одно фото — как у обычной задачи
        only_text = (await (await get(f"/api/tasks/{c}")).json())["task"]["reports"][0]
        assert only_text["caption"] == "всё хорошо" and only_text["media"] is None
        assert (await (await get(f"/api/tasks/{d}")).json())["task"]["reports"] == []
        assert (await get(f"/api/tasks/{a}", OTHER)).status == 404           # чужой шеф отчёт не увидит
        assert (await get(f"/api/tasks/{a}", F1)).status == 403              # прораб — не шеф

        # блок «ждут одобрения» на обзоре
        dash = await (await get("/api/dashboard?days=7")).json()
        assert {t["id"] for t in dash["awaiting"]} >= {b, d} and next(t for t in dash["awaiting"] if t["id"] == b)["report_photos"]

        # сами фото: полный размер, превью, номер фото в отчёте
        u = first["media"]["url"]
        r = await client.get(u)
        assert r.status == 200 and r.content_type == "image/jpeg" and (await r.read()).endswith(b"A1")
        r = await client.get(u + "&i=1")
        assert (await r.read()).endswith(b"A2")
        r = await client.get(u + "&i=1&v=thumb")
        assert (await r.read()).endswith(b"A2_T")                            # превью берётся из thumb_id
        assert (await client.get(u + "&i=2")).status == 404                  # такого фото в отчёте нет
        assert (await client.get(second["media"]["url"])).status == 200
        assert (await (await client.get(second["media"]["url"])).read()).endswith(b"A9")

        # защита: отчёт чужой задачи по ссылке другой задачи не отдаётся
        sig_b = det["reports"][0]["media"]["url"].replace(f"/api/media/{a}", f"/api/media/{b}")  # подпись от задачи a
        assert (await client.get(sig_b)).status == 403                       # подпись не подходит
        link_b = (await (await get(f"/api/tasks/{b}")).json())["task"]["reports"][0]["media"]["url"]
        assert (await client.get(link_b)).status == 200
        forged = link_b.split("&r=")[0] + f"&r={ra}"                         # ссылка задачи b + отчёт задачи a
        assert (await client.get(forged)).status == 404
        assert (await client.get(link_b.split("&r=")[0] + "&r=999999")).status == 404
        assert (await client.get(link_b.split("&r=")[0] + "&r=abc")).status == 404
        # у отчёта только с описанием фото запросить нельзя, даже с валидной подписью
        assert (await client.get(f"{store.url(c)}&r={rc}")).status == 404
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
