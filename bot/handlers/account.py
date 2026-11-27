from __future__ import annotations

import html
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from avito.client import AvitoHttpClient
from avito.messenger import AvitoMessengerService
from bot.keyboards import account_menu_kb, cancel_fsm_kb, proxy_menu_kb
from bot.states import AccountStates
from database.db import Database
from services.cookie_helper import cookies_from_json, parse_cookies_input
from services.proxy_helper import mask_proxy, normalize_proxy

router = Router()


# -------------------- АККАУНТ AVITO (COOKIES) --------------------


@router.callback_query(F.data == "menu:account")
async def cb_account_menu(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    await state.clear()
    settings = await db.get_bot_settings()
    cookies = cookies_from_json(settings.avito_cookies_json)

    status_block = (
        f"✅ <b>Cookies загружены:</b> {len(cookies)} шт.\n"
        f"🆔 <b>ID профиля:</b> <code>{html.escape(settings.account_user_id or 'не проверен')}</code>"
        if cookies
        else "❌ <b>Аккаунт не подключён</b> (cookies отсутствуют)"
    )

    text = (
        "👤 <b>Подключение аккаунта Avito</b>\n\n"
        f"{status_block}\n\n"
        "<b>Как подключить свой аккаунт:</b>\n"
        "1. Откройте <code>avito.ru</code> в браузере на ПК и войдите в свой аккаунт.\n"
        "2. Экспортируйте cookies через расширение <b>Cookie-Editor</b> (кнопка Export -> JSON) "
        "или скопируйте заголовок <code>Cookie</code> из DevTools (F12 -> Network).\n"
        "3. Нажмите кнопку ниже и отправьте скопированный текст боту."
    )
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=account_menu_kb(bool(cookies)),
    )
    await callback.answer()


@router.callback_query(F.data == "account:set_cookies")
async def cb_set_cookies(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AccountStates.waiting_cookies)
    await callback.message.edit_text(
        "🔑 <b>Отправьте Cookies вашего аккаунта Avito</b>\n\n"
        "Поддерживаются форматы:\n"
        "• JSON-массив из <b>Cookie-Editor / EditThisCookie</b>\n"
        "• Строка заголовка <code>sessid=...; u=...; ...</code> из DevTools\n"
        "• Формат Netscape <code>cookies.txt</code>\n\n"
        "<i>После сохранения сообщение с куками в чате будет автоматически удалено для безопасности.</i>",
        parse_mode="HTML",
        reply_markup=cancel_fsm_kb("menu:account"),
    )
    await callback.answer()


@router.message(AccountStates.waiting_cookies)
async def msg_save_cookies(
    message: Message,
    state: FSMContext,
    db: Database,
    client: AvitoHttpClient,
    messenger: AvitoMessengerService,
) -> None:
    raw_text = message.text or ""
    # Удаляем сообщение с чувствительными cookies из истории чата
    try:
        await message.delete()
    except Exception:
        pass

    try:
        parsed = parse_cookies_input(raw_text)
    except ValueError as exc:
        await message.answer(
            f"❌ <b>Ошибка формата cookies:</b> {html.escape(str(exc))}\nПопробуйте отправить ещё раз:",
            parse_mode="HTML",
            reply_markup=cancel_fsm_kb("menu:account"),
        )
        return

    await db.set_setting("avito_cookies_json", parsed.to_json())
    client.update_credentials(cookies=parsed.cookies)
    await state.clear()

    wait_msg = await message.answer("⏳ Cookies сохранены. Проверяю авторизацию в аккаунте Avito...")
    profile = await messenger.check_account()

    if profile.is_authorized:
        await db.set_setting("account_user_id", profile.user_id)
        await db.set_setting("account_name", profile.name)
        status_text = (
            f"✅ <b>Аккаунт Avito успешно подключён!</b>\n\n"
            f"• {html.escape(parsed.summary())}\n"
            f"• <b>Профиль:</b> {html.escape(profile.name)} (<code>{html.escape(profile.user_id)}</code>)\n"
            f"• {html.escape(profile.details)}"
        )
    else:
        status_text = (
            f"⚠️ <b>Cookies сохранены, но авторизация не подтверждена</b>\n\n"
            f"• {html.escape(parsed.summary())}\n"
            f"• <b>Причина:</b> {html.escape(profile.details)}"
        )

    await wait_msg.edit_text(
        status_text,
        parse_mode="HTML",
        reply_markup=account_menu_kb(True),
    )


@router.callback_query(F.data == "account:check")
async def cb_check_account(
    callback: CallbackQuery,
    db: Database,
    messenger: AvitoMessengerService,
) -> None:
    await callback.answer("Проверяю сессию Avito...")
    profile = await messenger.check_account()
    settings = await db.get_bot_settings()
    cookies = cookies_from_json(settings.avito_cookies_json)

    if profile.is_authorized:
        await db.set_setting("account_user_id", profile.user_id)
        await db.set_setting("account_name", profile.name)
        text = (
            "✅ <b>Сессия аккаунта активна</b>\n\n"
            f"• <b>Профиль:</b> {html.escape(profile.name)} (<code>{html.escape(profile.user_id)}</code>)\n"
            f"• <b>Загружено cookies:</b> {len(cookies)} шт.\n"
            f"• {html.escape(profile.details)}"
        )
    else:
        text = (
            "❌ <b>Сессия неактивна или истекла</b>\n\n"
            f"• <b>Детали:</b> {html.escape(profile.details)}\n"
            "• Нажмите «🔑 Загрузить / обновить Cookies», чтобы переподключить аккаунт."
        )

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=account_menu_kb(bool(cookies)),
    )


@router.callback_query(F.data == "account:clear_cookies")
async def cb_clear_cookies(
    callback: CallbackQuery,
    db: Database,
    client: AvitoHttpClient,
) -> None:
    await db.set_setting("avito_cookies_json", "{}")
    await db.set_setting("account_user_id", "")
    await db.set_setting("account_name", "")
    client.update_credentials(cookies={})
    await callback.message.edit_text(
        "🗑 <b>Cookies аккаунта Avito удалены из базы.</b>",
        parse_mode="HTML",
        reply_markup=account_menu_kb(False),
    )
    await callback.answer("Cookies удалены")


# -------------------- ПРОКСИ И ДИАГНОСТИКА СЕТИ --------------------


@router.callback_query(F.data == "menu:proxy")
async def cb_proxy_menu(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    await state.clear()
    settings = await db.get_bot_settings()
    masked = mask_proxy(settings.proxy_url)

    text = (
        "🌐 <b>Настройки прокси и сети</b>\n\n"
        f"• <b>Текущий прокси:</b> <code>{html.escape(masked)}</code>\n\n"
        "Рекомендуется использовать <b>мобильные или резидентские HTTP/SOCKS5 прокси РФ</b> "
        "для защиты от HTTP 429/439 и сохранения стабильности сессии аккаунта."
    )
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=proxy_menu_kb(bool(settings.proxy_url)),
    )
    await callback.answer()


@router.callback_query(F.data == "proxy:set")
async def cb_set_proxy(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AccountStates.waiting_proxy)
    await callback.message.edit_text(
        "🌐 <b>Отправьте данные прокси-сервера</b>\n\n"
        "Поддерживаемые форматы:\n"
        "• <code>http://user:pass@ip:port</code>\n"
        "• <code>socks5://user:pass@ip:port</code>\n"
        "• <code>ip:port:user:pass</code>\n"
        "• <code>ip:port</code>",
        parse_mode="HTML",
        reply_markup=cancel_fsm_kb("menu:proxy"),
    )
    await callback.answer()


@router.message(AccountStates.waiting_proxy)
async def msg_save_proxy(
    message: Message,
    state: FSMContext,
    db: Database,
    client: AvitoHttpClient,
) -> None:
    raw = (message.text or "").strip()
    try:
        await message.delete()
    except Exception:
        pass

    try:
        normalized = normalize_proxy(raw)
    except ValueError as exc:
        await message.answer(
            f"❌ <b>Ошибка формата прокси:</b> {html.escape(str(exc))}",
            parse_mode="HTML",
            reply_markup=cancel_fsm_kb("menu:proxy"),
        )
        return

    await db.set_setting("proxy_url", normalized or "")
    client.update_credentials(proxy_url=normalized or "")
    await state.clear()

    wait_msg = await message.answer("⏳ Прокси сохранён. Выполняю диагностику подключения к Avito...")
    diag = await client.diagnose()

    status_icon = "✅" if diag["avito_ok"] else "⚠️"
    text = (
        f"{status_icon} <b>Результат проверки прокси</b>\n\n"
        f"• <b>Прокси:</b> <code>{html.escape(diag['proxy'])}</code>\n"
        f"• <b>Внешний IP:</b> <code>{html.escape(str(diag['ip']))}</code> ({diag['ip_latency_ms'] or '-'} мс)\n"
        f"• <b>Ответ Avito:</b> HTTP {diag['avito_status'] or '-'} ({diag['avito_latency_ms'] or '-'} мс)\n"
        f"• <b>Статус:</b> {html.escape(diag['note'])}"
    )
    await wait_msg.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=proxy_menu_kb(bool(normalized)),
    )


@router.callback_query(F.data == "proxy:diagnose")
async def cb_diagnose_proxy(
    callback: CallbackQuery,
    db: Database,
    client: AvitoHttpClient,
) -> None:
    await callback.answer("Проверяю соединение и TLS-отпечаток...")
    settings = await db.get_bot_settings()
    diag = await client.diagnose()

    status_icon = "✅" if diag["avito_ok"] else "⚠️"
    text = (
        f"{status_icon} <b>Диагностика сети и Avito</b>\n\n"
        f"• <b>Прокси:</b> <code>{html.escape(diag['proxy'])}</code>\n"
        f"• <b>Внешний IP:</b> <code>{html.escape(str(diag['ip']))}</code> ({diag['ip_latency_ms'] or '-'} мс)\n"
        f"• <b>Ответ Avito:</b> HTTP {diag['avito_status'] or '-'} ({diag['avito_latency_ms'] or '-'} мс)\n"
        f"• <b>Вердикт:</b> {html.escape(diag['note'])}"
    )
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=proxy_menu_kb(bool(settings.proxy_url)),
    )


@router.callback_query(F.data == "proxy:clear")
async def cb_clear_proxy(
    callback: CallbackQuery,
    db: Database,
    client: AvitoHttpClient,
) -> None:
    await db.set_setting("proxy_url", "")
    client.update_credentials(proxy_url="")
    await callback.message.edit_text(
        "🗑 <b>Прокси отключён.</b> Бот использует прямое подключение сервера.",
        parse_mode="HTML",
        reply_markup=proxy_menu_kb(False),
    )
    await callback.answer("Прокси отключён")
