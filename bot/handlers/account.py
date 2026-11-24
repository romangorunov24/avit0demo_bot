import io
import json
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from bot.keyboards import account_menu_kb, cancel_kb
from bot.states import AccountStates
from config import settings
from database import models
from services.spintax import render_spintax
from utils.helpers import parse_cookies_json

router = Router()


async def _render_account_screen() -> tuple[str, dict | None, bool, bool]:
    account = await models.get_account()
    auto_reply = await models.get_setting("auto_reply_enabled", "1") == "1"
    night_mode = await models.get_setting("night_mode", "0") == "1"
    spintax = await models.get_setting("spintax_template")
    limit = await models.get_setting("hourly_limit", "15")

    if settings.AVITO_ACCESS_TOKEN and settings.AVITO_USER_ID:
        status = "🟢 Официальный API подключен (.env)"
    elif account and account["is_valid"]:
        status = f"🟢 Активна (обновлена: {account['updated_at']})"
    elif account:
        status = "🔴 Недействительна — загрузите свежие cookies"
    else:
        status = "⚪ Не привязана"

    example = render_spintax(spintax, title="iPhone 13 Pro Max 256GB", price=42000)
    text = (
        "<b>👤 Настройки аккаунта Avito и Автоотклика</b>\n\n"
        f"• <b>Сессия Avito:</b> {status}\n"
        f"• <b>Лимит антибана:</b> не более {limit} сообщ./час\n"
        f"• <b>Текущий шаблон:</b>\n<code>{spintax}</code>\n\n"
        f"• <b>Пример сообщения:</b>\n<i>«{example}»</i>"
    )
    return text, account, auto_reply, night_mode


@router.callback_query(F.data == "account:menu")
async def cb_account_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    text, acc, ar, nm = await _render_account_screen()
    await callback.message.edit_text(
        text, reply_markup=account_menu_kb(acc, ar, nm), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "account:toggle_autoreply")
async def cb_toggle_autoreply(callback: CallbackQuery) -> None:
    cur = await models.get_setting("auto_reply_enabled", "1")
    await models.set_setting("auto_reply_enabled", "0" if cur == "1" else "1")
    text, acc, ar, nm = await _render_account_screen()
    await callback.message.edit_text(text, reply_markup=account_menu_kb(acc, ar, nm), parse_mode="HTML")
    await callback.answer("Настройка автоответа изменена")


@router.callback_query(F.data == "account:toggle_night")
async def cb_toggle_night(callback: CallbackQuery) -> None:
    cur = await models.get_setting("night_mode", "0")
    await models.set_setting("night_mode", "0" if cur == "1" else "1")
    text, acc, ar, nm = await _render_account_screen()
    await callback.message.edit_text(text, reply_markup=account_menu_kb(acc, ar, nm), parse_mode="HTML")
    await callback.answer("Ночной режим переключен")


@router.callback_query(F.data == "account:cookies")
async def cb_account_cookies(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AccountStates.waiting_cookies)
    await callback.message.edit_text(
        "🍪 <b>Привязка аккаунта Avito</b>\n\n"
        "1. Авторизуйтесь на <code>avito.ru</code> в браузере.\n"
        "2. Откройте расширение <b>Cookie-Editor</b> → нажмите <b>Export → JSON</b>.\n"
        "3. Отправьте скопированный текст сюда сообщением или прикрепите <code>.json</code> файлом:",
        reply_markup=cancel_kb("account:menu"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AccountStates.waiting_cookies)
async def msg_account_cookies(message: Message, state: FSMContext) -> None:
    raw_json = ""
    if message.document:
        buf = io.BytesIO()
        await message.bot.download(message.document, destination=buf)
        raw_json = buf.getvalue().decode("utf-8", errors="ignore")
    elif message.text:
        raw_json = message.text.strip()

    try:
        cookies_dict = parse_cookies_json(raw_json)
        await models.save_cookies(json.dumps(cookies_dict, ensure_ascii=False), is_valid=1)
    except Exception as e:
        await message.answer(f"❌ Ошибка чтения cookies: {e}\nПроверьте формат JSON и отправьте снова:")
        return

    await state.clear()
    text, acc, ar, nm = await _render_account_screen()
    await message.answer(
        f"✅ Загружено {len(cookies_dict)} cookies! Сессия сохранена.\n\n" + text,
        reply_markup=account_menu_kb(acc, ar, nm),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "account:spintax")
async def cb_account_spintax(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AccountStates.waiting_spintax)
    await callback.message.edit_text(
        "✍️ <b>Настройка шаблона первого сообщения</b>\n\n"
        "Используйте конструкции <code>{вариант 1|вариант 2|вариант 3}</code> для рандомизации текста (защита от спам-фильтра) "
        "и переменные <code>{title}</code> (название товара) и <code>{price}</code> (цена).\n\n"
        "Отправьте новый шаблон:",
        reply_markup=cancel_kb("account:menu"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AccountStates.waiting_spintax)
async def msg_account_spintax(message: Message, state: FSMContext) -> None:
    tpl = (message.text or "").strip()
    if len(tpl) < 5:
        await message.answer("Шаблон слишком короткий. Введите нормальный текст:")
        return
    await models.set_setting("spintax_template", tpl)
    await state.clear()
    text, acc, ar, nm = await _render_account_screen()
    await message.answer(text, reply_markup=account_menu_kb(acc, ar, nm), parse_mode="HTML")


@router.callback_query(F.data == "account:limit")
async def cb_account_limit(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AccountStates.waiting_hourly_limit)
    await callback.message.edit_text(
        "⏱ Введите максимальное количество автоматических сообщений в час (рекомендуется <code>10–20</code>):",
        reply_markup=cancel_kb("account:menu"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AccountStates.waiting_hourly_limit)
async def msg_account_limit(message: Message, state: FSMContext) -> None:
    val = (message.text or "").strip()
    if not val.isdigit() or int(val) < 1 or int(val) > 100:
        await message.answer("Введите число от 1 до 100:")
        return
    await models.set_setting("hourly_limit", val)
    await state.clear()
    text, acc, ar, nm = await _render_account_screen()
    await message.answer(text, reply_markup=account_menu_kb(acc, ar, nm), parse_mode="HTML")
