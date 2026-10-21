from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, InputMediaPhoto, InputMediaVideo, MenuButtonWebApp, Message, WebAppInfo

from bot.texts import album_items, esc

log = logging.getLogger(__name__)

# вид задачи -> (метод бота, имя аргумента с файлом)
_MEDIA_SENDERS = {
    "photo": ("send_photo", "photo"),
    "voice": ("send_voice", "voice"),
    "video": ("send_video", "video"),
    "document": ("send_document", "document"),
}
_CAPTION_TEXT_LIMIT = 800  # подпись в Telegram — до 1024 символов вместе с заголовком
_TEXT_LIMIT = 3500


async def safe_send(bot: Bot, chat_id: int, text: str, kb: InlineKeyboardMarkup | None = None) -> bool:
    """Отправка, которая не роняет бота, если пользователь заблокировал его или не нажимал /start."""
    try:
        await bot.send_message(chat_id, text, reply_markup=kb)
        return True
    except TelegramAPIError as e:
        log.warning("Не удалось отправить сообщение %s: %s", chat_id, e)
        return False


async def send_task(bot: Bot, chat_id: int, t, header: str, kb: InlineKeyboardMarkup | None = None) -> bool:
    """Отправляет задачу в её исходном виде (текст, фото, голосовое...) с заголовком."""
    text = t["text"] or ""
    kind = t["kind"]
    items = album_items(t)
    try:
        if items:
            return await _send_album(bot, chat_id, t, items, header, kb)
        if kind == "text" or kind not in _MEDIA_SENDERS:
            body = f"\n\n{esc(text[:_TEXT_LIMIT])}" if text else ""
            await bot.send_message(chat_id, header + body, reply_markup=kb)
            return True

        method, arg = _MEDIA_SENDERS[kind]
        long_text = len(text) > _CAPTION_TEXT_LIMIT
        caption = header if (long_text or not text) else f"{header}\n\n{esc(text)}"
        await getattr(bot, method)(chat_id, **{arg: t["file_id"]}, caption=caption, reply_markup=kb)
        if long_text:
            await bot.send_message(chat_id, esc(text[:_TEXT_LIMIT]))
        return True
    except TelegramAPIError as e:
        log.warning("Не удалось отправить задачу %s в чат %s: %s", t["id"], chat_id, e)
        return False


async def _send_album(bot: Bot, chat_id: int, t, items: list, header: str, kb: InlineKeyboardMarkup | None) -> bool:
    """Несколько фото/видео одним альбомом; заголовок и текст — в подписи к первому."""
    text = t["text"] or ""
    long_text = len(text) > _CAPTION_TEXT_LIMIT
    caption = header if (long_text or not text) else f"{header}\n\n{esc(text)}"
    media = [
        (InputMediaVideo if it["kind"] == "video" else InputMediaPhoto)(media=it["file_id"], caption=caption if i == 0 else None)
        for i, it in enumerate(items)
    ]
    try:
        await bot.send_media_group(chat_id, media=media)
        if long_text:
            await bot.send_message(chat_id, esc(text[:_TEXT_LIMIT]))
        if kb:  # к альбому кнопки не прикрепить — отдельным сообщением
            await bot.send_message(chat_id, "Отметьте результат:", reply_markup=kb)
        return True
    except TelegramAPIError as e:
        log.warning("Не удалось отправить альбом задачи %s в чат %s: %s", t["id"], chat_id, e)
        return False


async def safe_edit(message: Message, text: str, kb: InlineKeyboardMarkup | None = None) -> None:
    try:
        await message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            return
        await message.answer(text, reply_markup=kb)


async def drop_keyboard(message: Message) -> None:
    """Убирает кнопки под сообщением (подходит и для текста, и для фото/голосового)."""
    try:
        await message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError:
        pass


async def set_dashboard_menu(bot: Bot, chat_id: int, url: str) -> None:
    """Кнопка «📊 Дашборд» рядом с полем ввода — открывает Mini App (с подписанным initData)."""
    try:
        await bot.set_chat_menu_button(
            chat_id=chat_id,
            menu_button=MenuButtonWebApp(text="📊 Дашборд", web_app=WebAppInfo(url=url)),
        )
    except TelegramAPIError as e:  # чат ещё не создан (шеф не нажимал /start) — не страшно
        log.info("Кнопка дашборда для %s не установлена: %s", chat_id, e)
