from __future__ import annotations

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from db import Database
from keyboards import approve_kb, chief_menu, foreman_menu
from notify import safe_send
from texts import esc

router = Router()

CHIEF_HELP = (
    "<b>Как работать с ботом (шеф)</b>\n\n"
    "➕ <b>Новая задача</b> — отправьте боту текст, фото или голосовое, выберите важность "
    "и прорабов (одного, нескольких или всех). Задача придёт им и накопится в их панели.\n"
    "📋 <b>Активные задачи</b> — всё, что сейчас в работе. Здесь вы сами отмечаете результат: "
    "выполнено / не выполнено.\n"
    "📊 <b>Статистика</b> — кому сколько задач, процент выполнения, экспорт в CSV.\n"
    "👷 <b>Прорабы</b> — ссылка-приглашение, заявки и отключение прорабов.\n\n"
    "Каждое утро бот присылает сводку по участку. Отмена любого действия — /cancel."
)

FOREMAN_HELP = (
    "<b>Как работать с ботом (прораб)</b>\n\n"
    "Шеф отправляет вам задачи — они приходят сюда и копятся в вашей панели.\n\n"
    "📋 <b>Мои задачи</b> — все задачи в работе (нажмите, чтобы открыть).\n"
    "📈 <b>Моя статистика</b> — сколько задач выполнено, не выполнено и в работе.\n\n"
    "Результат по задачам отмечает шеф."
)


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, state: FSMContext, db: Database, bot: Bot):
    await state.clear()
    u = message.from_user
    user = await db.get_user(u.id)

    if user:
        await db.touch_user(u.id, u.full_name, u.username)

    if user and user["role"] == "chief":
        await message.answer(
            f"Здравствуйте, {esc(u.first_name)}! Вы вошли как <b>шеф</b>.\n\n" + CHIEF_HELP,
            reply_markup=chief_menu(),
        )
        return

    if user and user["role"] == "foreman":
        if user["status"] == "active":
            await message.answer(
                f"Здравствуйте, {esc(u.first_name)}! Здесь вы будете получать задачи от шефа.\n\n" + FOREMAN_HELP,
                reply_markup=foreman_menu(),
            )
        elif user["status"] == "pending":
            await message.answer("⏳ Заявка отправлена шефу. Как только он её подтвердит, я сообщу.")
        else:
            await message.answer("🚫 Доступ закрыт. Обратитесь к шефу.")
        return

    # новый пользователь: регистрация только по ссылке-приглашению шефа
    arg = command.args or ""
    if arg.startswith("ref_") and arg[4:].isdigit():
        chief = await db.get_user(int(arg[4:]))
        if chief and chief["role"] == "chief":
            await db.register_foreman(u.id, u.full_name, u.username, chief["tg_id"])
            await message.answer("✅ Заявка отправлена шефу. Как только он её подтвердит, вы начнёте получать задачи.")
            uname = f" (@{u.username})" if u.username else ""
            await safe_send(
                bot,
                chief["tg_id"],
                f"👷 Новый прораб просит доступ:\n<b>{esc(u.full_name)}</b>{esc(uname)}",
                approve_kb(u.id),
            )
            return

    await message.answer(
        "Это рабочий бот для распределения задач.\n"
        "Чтобы начать, попросите шефа прислать вам ссылку-приглашение и перейдите по ней."
    )


@router.message(Command("help"))
async def cmd_help(message: Message, db: Database):
    if await db.is_chief(message.from_user.id):
        await message.answer(CHIEF_HELP, reply_markup=chief_menu())
    elif await db.is_active_foreman(message.from_user.id):
        await message.answer(FOREMAN_HELP, reply_markup=foreman_menu())
    else:
        await message.answer("Попросите шефа прислать ссылку-приглашение.")


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext, db: Database):
    await state.clear()
    if await db.is_chief(message.from_user.id):
        await message.answer("Главное меню", reply_markup=chief_menu())
    elif await db.is_active_foreman(message.from_user.id):
        await message.answer("Главное меню", reply_markup=foreman_menu())


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, db: Database):
    await state.clear()
    kb = None
    if await db.is_chief(message.from_user.id):
        kb = chief_menu()
    elif await db.is_active_foreman(message.from_user.id):
        kb = foreman_menu()
    await message.answer("Действие отменено.", reply_markup=kb)
