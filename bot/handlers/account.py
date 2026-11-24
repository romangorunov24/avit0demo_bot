import asyncio
import json
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from bot.keyboards import account_menu_kb, cancel_kb, main_menu_kb
from bot.states import AccountStates
from database import db
from services.avito_messenger import AvitoMessenger, normalize_cookies

router = Router()


def _format_account_text(user_data: dict | None) -> str:
    cookies_raw = (user_data or {}).get("avito_cookies")
    template = (user_data or {}).get("default_template") or "Здравствуйте! Объявление ещё актуально?"
    cookies = normalize_cookies(cookies_raw or "")

    if cookies:
        status = f"🟢 <b>Подключён</b> (ключей: <code>{', '.join(cookies.keys())}</code>)"
    else:
        status = "⚪️ <b>Не привязан</b> (парсинг работает, автоотклик выключен)"

    return (
        "👤 <b>Управление аккаунтом Avito</b>\n\n"
        f"Статус: {status}\n"
        f"Шаблон по умолчанию:\n<i>«{template}»</i>\n\n"
        "Выберите удобный способ подключения ниже:"
    )


@router.message(F.text == "👤 Мой Avito")
async def show_account_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    user_data = await db.get_user_settings(message.from_user.id)
    has_acc = bool(normalize_cookies((user_data or {}).get("avito_cookies") or ""))
    await message.answer(_format_account_text(user_data), parse_mode="HTML", reply_markup=account_menu_kb(has_acc))


@router.callback_query(F.data == "acc_menu_open")
async def open_account_from_card(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    user_data = await db.get_user_settings(callback.from_user.id)
    has_acc = bool(normalize_cookies((user_data or {}).get("avito_cookies") or ""))
    await callback.message.answer(_format_account_text(user_data), parse_mode="HTML", reply_markup=account_menu_kb(has_acc))
    await callback.answer()


@router.callback_query(F.data == "cancel_fsm")
async def cancel_fsm_handler(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Действие отменено.")
    await callback.answer()


@router.callback_query(F.data == "acc_connect_pc")
async def connect_pc_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(AccountStates.waiting_cookies_pc)
    text = (
        "💻 <b>Подключение через компьютер (3 шага)</b>\n\n"
        "1. Откройте <b>avito.ru</b> в браузере (Chrome / Яндекс) и войдите в аккаунт.\n"
        "2. Установите расширение <b>Cookie-Editor</b>, нажмите на него на странице Авито → "
        "<b>Export → Export as JSON</b>.\n"
        "3. Вставьте скопированный текст прямо в этот чат (я сам склею все части и вырежу лишнее) "
        "или отправьте файлом <code>cookies.json</code>.\n\n"
        "⚠️ <i>После экспорта не нажимайте «Выйти» на сайте Авито, просто закройте вкладку.</i>"
    )
    await callback.message.answer(text, parse_mode="HTML", reply_markup=cancel_kb())
    await callback.answer()


@router.message(AccountStates.waiting_cookies_pc)
async def process_pc_cookies(message: Message, state: FSMContext) -> None:
    raw_text = ""

    if message.document:
        if message.document.file_size and message.document.file_size > 512 * 1024:
            await message.answer("❌ Файл слишком большой (максимум 512 КБ).")
            return
        file = await message.bot.get_file(message.document.file_id)
        downloaded = await message.bot.download_file(file.file_path)
        raw_text = downloaded.read().decode("utf-8", errors="ignore")
    elif message.text:
        raw_text = message.text
    else:
        await message.answer("Отправьте файл <code>cookies.json</code> или вставьте текст JSON.", parse_mode="HTML")
        return

    cleaned = normalize_cookies(raw_text)

    # Накапливаем ключи из всех частей, если Telegram разрезал длинное сообщение на несколько кусков
    data = await state.get_data()
    seq = data.get("cookie_seq", 0) + 1
    accumulated = dict(data.get("acc_cookies", {}))
    accumulated.update(cleaned)
    await state.update_data(cookie_seq=seq, acc_cookies=accumulated)

    if not message.document:
        await asyncio.sleep(1.2)
        latest_data = await state.get_data()
        if latest_data.get("cookie_seq") != seq:
            return
        accumulated = dict(latest_data.get("acc_cookies", {}))

    if not accumulated or ("sessid" not in accumulated and "u" not in accumulated):
        await state.update_data(acc_cookies={})
        await message.answer(
            "❌ Не удалось найти ключи Авито (<code>sessid</code> и <code>u</code>).\n"
            "Убедитесь, что вы экспортировали cookies со страницы <b>avito.ru</b> после входа в аккаунт, "
            "и отправьте их повторно:",
            parse_mode="HTML",
            reply_markup=cancel_kb(),
        )
        return

    compact_json = json.dumps(accumulated, ensure_ascii=False)
    await db.save_user_cookies(message.from_user.id, compact_json)
    await state.clear()

    wait_msg = await message.answer("⏳ Проверяю сессию Avito через прокси...")
    messenger = AvitoMessenger()
    ok, info = await messenger.check_session(compact_json)

    prefix = "✅" if ok else "⚠️"
    await wait_msg.edit_text(
        f"{prefix} <b>Готово!</b> {info}\n"
        f"Сохранены компактные ключи: <code>{', '.join(accumulated.keys())}</code>",
        parse_mode="HTML",
    )


@router.callback_query(F.data == "acc_connect_mobile")
async def connect_mobile_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(AccountStates.waiting_mobile_session)
    text = (
        "📱 <b>Подключение с телефона (без компьютера)</b>\n\n"
        "1. Установите браузер <b>Kiwi Browser</b> (Android) или <b>Orion Browser</b> (iPhone).\n"
        "2. Войдите в нём на сайт <b>avito.ru</b>.\n"
        "3. Установите расширение <b>Cookie-Editor</b>, нажмите <b>Export</b> и вставьте скопированный текст сюда "
        "(или отправьте строку вида <code>sessid=...; u=...; v=...</code>).\n\n"
        "Отправьте данные сессии в ответном сообщении:"
    )
    await callback.message.answer(text, parse_mode="HTML", reply_markup=cancel_kb())
    await callback.answer()


@router.message(AccountStates.waiting_mobile_session)
async def process_mobile_session(message: Message, state: FSMContext) -> None:
    await process_pc_cookies(message, state)


@router.callback_query(F.data == "acc_check")
async def check_account_handler(callback: CallbackQuery) -> None:
    user_data = await db.get_user_settings(callback.from_user.id)
    cookies_raw = (user_data or {}).get("avito_cookies")
    messenger = AvitoMessenger()
    _, info = await messenger.check_session(cookies_raw)
    await callback.answer(info[:190], show_alert=True)


@router.callback_query(F.data == "acc_disconnect")
async def disconnect_account_handler(callback: CallbackQuery) -> None:
    await db.save_user_cookies(callback.from_user.id, None)
    user_data = await db.get_user_settings(callback.from_user.id)
    await callback.message.edit_text(_format_account_text(user_data), parse_mode="HTML", reply_markup=account_menu_kb(False))
    await callback.answer("Аккаунт Avito отвязан")


@router.callback_query(F.data == "acc_set_template")
async def set_template_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AccountStates.waiting_default_template)
    await callback.message.answer(
        "✏️ Введите текст сообщения по умолчанию.\n"
        "Поддерживается спинтакс: <code>{Здравствуйте|Добрый день}! {Актуально|Ещё продаёте}?</code>",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(AccountStates.waiting_default_template)
async def save_template_handler(message: Message, state: FSMContext) -> None:
    if not message.text:
        return
    await db.save_default_template(message.from_user.id, message.text.strip())
    await state.clear()
    await message.answer("✅ Шаблон автоотклика обновлён!", reply_markup=main_menu_kb())
