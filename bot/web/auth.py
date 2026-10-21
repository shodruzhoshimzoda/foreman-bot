"""Проверка подписи Telegram Mini App (initData).

Алгоритм из документации Telegram:
  secret = HMAC_SHA256(key="WebAppData", msg=bot_token)
  hash   = HMAC_SHA256(key=secret, msg=data_check_string)
где data_check_string — все поля initData кроме `hash`, отсортированные по ключу, в виде "key=value" через "\\n".
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

MAX_AGE_SECONDS = 24 * 3600


class AuthError(Exception):
    pass


def validate_init_data(init_data: str, bot_token: str, max_age: int = MAX_AGE_SECONDS) -> int:
    """Возвращает Telegram ID пользователя или бросает AuthError."""
    if not init_data or len(init_data) > 4096:
        raise AuthError("empty initData")
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received = pairs.pop("hash", None)
    if not received:
        raise AuthError("no hash")

    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        raise AuthError("bad signature")

    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError:
        raise AuthError("bad auth_date")
    if time.time() - auth_date > max_age:
        raise AuthError("initData expired")

    try:
        return int(json.loads(pairs["user"])["id"])
    except (KeyError, ValueError, TypeError):
        raise AuthError("no user")
