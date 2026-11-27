# Avito Hunter & Auto-Reply Telegram Bot

Полностью асинхронный Telegram-бот для мониторинга свежих объявлений на **Avito** и автоматической отправки сообщений продавцам с подключением вашего личного аккаунта.

## Архитектура проекта

```text
avito_hunter_bot/
├── main.py                  # Точка входа, инициализация БД, HTTP-клиента, планировщика и aiogram
├── config.py                # Загрузка и валидация настроек из .env
├── requirements.txt         # Зависимости Python
├── .env.example             # Пример файла конфигурации
├── Dockerfile               # Docker-образ
├── docker-compose.yml       # Запуск через Docker Compose
├── avito/
│   ├── client.py            # HTTP-клиент на curl-cffi (TLS-отпечатки Chrome, автообновление cookies, прокси)
│   ├── parser.py            # Парсинг выдачи Avito (embedded JSON + DOM fallback) и фильтрация
│   ├── messenger.py         # Работа с аккаунтом Avito и отправка сообщений в чат продавцу
│   └── exceptions.py        # Типизированные исключения (429/439, авторизация, прокси)
├── bot/
│   ├── handlers/            # Обработчики меню, поисков, аккаунта, прокси и настроек автоотклика
│   ├── keyboards.py         # Inline-клавиатуры
│   ├── states.py            # FSM-состояния диалогов
│   └── middlewares.py       # Защита доступа по ADMIN_IDS
├── database/
│   ├── db.py                # Асинхронный слой SQLite (aiosqlite, WAL-режим, дедупликация, логи)
│   └── models.py            # Модели данных
├── services/
│   ├── cookie_helper.py     # Парсинг cookies (JSON, DevTools Cookie header, Netscape)
│   ├── proxy_helper.py      # Нормализация прокси (HTTP/SOCKS5)
│   └── scheduler.py         # Фоновый мониторинг с джиттером и очередь автооткликов
└── tests/
    └── test_bot_suite.py    # Модульные и интеграционные тесты
```

---

## Быстрый запуск (Linux / VPS / Windows)

### 1. Подготовка `.env`
Скопируйте `.env.example` в `.env` и заполните:
```bash
cp .env.example .env
```
- `BOT_TOKEN` — токен вашего бота от `@BotFather`.
- `ADMIN_IDS` — ваш числовой Telegram ID (можно узнать у `@userinfobot`). Бот отвечает **только** пользователям из этого списка.

### 2. Запуск через Python (venv)
```bash
python3 -m venv venv
source venv/bin/activate        # Для Windows: venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

### 3. Запуск через Docker Compose
```bash
docker compose up -d --build
```

---

## Как подключить свой аккаунт Avito

1. Откройте `https://www.avito.ru` в браузере Google Chrome / Яндекс Браузере и авторизуйтесь в своём аккаунте.
2. Установите расширение **Cookie-Editor** (или откройте DevTools `F12` -> вкладка `Network` -> любой запрос к `avito.ru` -> заголовок `Cookie:`).
3. Скопируйте cookies в формате **JSON** (кнопка *Export -> JSON* в Cookie-Editor) или как строку `sessid=...; u=...`.
4. В Telegram-боте откройте **«👤 Аккаунт Avito» -> «🔑 Загрузить / обновить Cookies»** и вставьте скопированный текст.
5. Бот автоматически удалит ваше сообщение с куками из чата для безопасности, проверит сессию и отобразит статус профиля.

---

## Защита от блокировок (HTTP 429 / 439)

- Используется `curl-cffi` с TLS-отпечатком актуального Chrome (`chrome131` + автоматический fallback).
- Встроен парсер и диагностика **HTTP/SOCKS5 прокси** («🌐 Прокси и сеть» -> «🩺 Диагностика сети и IP»).
- Реализован случайный разброс интервалов сканирования (`±20%`), пауза перед отправкой отклика (`8–22 сек`), часовой/суточный лимиты и запрет повторных сообщений одному и тому же продавцу.
