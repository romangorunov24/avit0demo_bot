from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from bot.keyboards import guide_menu_kb, main_menu_kb
from config import settings
from database import db

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await db.get_user_settings(message.from_user.id)
    await message.answer(
        "🦅 <b>Avito Sniper Pro — Автоматический выкуп лотов</b>\n\n"
        "Я проверяю выдачу Авито примерно раз в полторы минуты и умею <b>сам писать продавцу первым</b> "
        "с вашего аккаунта, как только появится подходящий новый лот.\n\n"
        "<b>С чего начать за 2 минуты:</b>\n"
        "1️⃣ Нажмите <b>«➕ Добавить поиск»</b> — задайте ссылку с Авито, мин/макс цену и стоп-слова.\n"
        "2️⃣ Откройте <b>«🤖 Автоотклик и Аккаунт»</b> — привяжите сессию Avito и включите автоотклик. Бот напишет только по <b>новым</b> лотам, появившимся после создания поиска.\n"
        "3️⃣ Загляните в <b>«📖 Инструкция и Защита»</b> — там расписано, как работать <b>без прокси</b> и снизить риск блокировки (полной гарантии от неё нет).",
        parse_mode="HTML",
        reply_markup=main_menu_kb(),
    )


@router.message(F.text == "📖 Инструкция и Защита")
async def show_guide_menu(message: Message) -> None:
    await message.answer(
        "📖 <b>Справочник по работе и защите аккаунта</b>\n\n"
        "Выберите раздел, чтобы узнать, как всё устроено и как снизить риск блокировки аккаунта:",
        parse_mode="HTML",
        reply_markup=guide_menu_kb(),
    )


@router.callback_query(F.data == "guide_menu")
async def cb_guide_menu(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "📖 <b>Справочник по работе и защите аккаунта</b>\n\n"
        "Выберите раздел:",
        parse_mode="HTML",
        reply_markup=guide_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "guide_noproxy")
async def cb_guide_noproxy(callback: CallbackQuery) -> None:
    text = (
        "🆓 <b>Как работать БЕЗ прокси и без затрат (0 ₽)</b>\n\n"
        "<b>Почему облако (Railway) требует прокси:</b> серверы Railway находятся в США/Европе, а Авито блокирует заходы с зарубежных дата-центров.\n\n"
        "<b>Как обойтись вообще без прокси:</b>\n"
        "1. Запустите бота прямо на своём Windows-ПК или ноутбуке двойным кликом по файлу <code>start_bot.bat</code> (в файле <code>.env</code> строчка <code>PROXY_URL=</code> должна быть пустой).\n"
        "2. Ваш домашний интернет в России уже имеет чистый резидентский IP.\n"
        "3. Если вы экспортируете cookies с этого же компьютера, IP браузера и IP бота совпадают, поэтому риск «подозрительного входа» ниже."
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=guide_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "guide_cookies")
async def cb_guide_cookies(callback: CallbackQuery) -> None:
    text = (
        "🔑 <b>Как безопасно подключить аккаунт Avito</b>\n\n"
        "1. Установите в браузер (Chrome / Яндекс / Edge) бесплатное расширение <b>Cookie-Editor</b>.\n"
        "2. Откройте <b>avito.ru</b>, войдите в свой профиль.\n"
        "3. Нажмите на иконку Cookie-Editor → <b>Export → Export as JSON</b>.\n"
        "4. Перейдите в боте в <b>«🤖 Автоотклик и Аккаунт» → «💻 Подключить Avito с ПК»</b> и вставьте скопированный текст (даже если Telegram разобьёт его на 3–4 части, бот сам склеит нужные ключи).\n\n"
        "⚠️ <b>Важно:</b> после экспорта не нажимайте «Выйти» на сайте Авито — просто закройте вкладку. Если бот запущен на Railway, входите в аккаунт Авито через тот же прокси, что указан в <code>PROXY_URL</code>."
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=guide_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "guide_antiban")
async def cb_guide_antiban(callback: CallbackQuery) -> None:
    text = (
        "🛡 <b>Какие меры снижают риск блокировки</b> (гарантии нет: Авито запрещает автоматические рассылки, аккаунт могут ограничить)\n\n"
        "• <b>Разделение сессий:</b> парсер ищет объявления анонимно, не светя ваш аккаунт. Ваши cookies подключаются только на секунду отправки сообщения.\n"
        "• <b>Имитация человека:</b> перед отправкой бот ждёт 4–10 сек., открывает страницу товара (прогрев) и только потом пишет продавцу.\n"
        "• <b>Антиспам-фильтры:</b> бот никогда не напишет дважды по одному лоту и не будет спамить одному продавцу по разным объявлениям.\n"
        "• <b>Лимиты:</b> по умолчанию не более 8 откликов в час и 30 в сутки (настраивается).\n"
        "• <b>Предохранитель:</b> при ответах Авито 401/403 автоотклик сам отключается."
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=guide_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "guide_spintax")
async def cb_guide_spintax(callback: CallbackQuery) -> None:
    text = (
        "💬 <b>Спинтакс и умные переменные в шаблонах</b>\n\n"
        "Чтобы Авито не считало сообщения рассылкой, каждый текст должен отличаться. Используйте фигурные скобки с чертой <code>|</code>:\n\n"
        "<code>{Здравствуйте|Добрый день|Привет}! {Актуально|Ещё продаёте}? Готов забрать {title} сегодня.</code>\n\n"
        "<b>Доступные переменные:</b>\n"
        "• <code>{title}</code> — подставит название товара\n"
        "• <code>{price}</code> — цена из объявления\n"
        "• <code>{price_bargain}</code> — цена автоматически на 10% ниже (удобно для торга)"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=guide_menu_kb())
    await callback.answer()


@router.message(Command("grant"))
async def cmd_grant(message: Message) -> None:
    if message.from_user.id not in settings.admin_ids_list:
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Использование: <code>/grant 123456789</code>", parse_mode="HTML")
        return
    target_id = int(parts[1])
    await db.grant_user_access(target_id)
    await message.answer(f"✅ Доступ к боту выдан пользователю <code>{target_id}</code>.", parse_mode="HTML")


@router.message(Command("revoke"))
async def cmd_revoke(message: Message) -> None:
    if message.from_user.id not in settings.admin_ids_list:
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Использование: <code>/revoke 123456789</code>", parse_mode="HTML")
        return
    target_id = int(parts[1])
    await db.revoke_user_access(target_id)
    await message.answer(f"🚫 Доступ отозван у пользователя <code>{target_id}</code>.", parse_mode="HTML")