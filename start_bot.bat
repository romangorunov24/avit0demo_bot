@echo off
chcp 65001 >nul
title Avito Sniper Pro - Local Runner
cd /d "%~dp0"

if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo [!] Файл .env создан из шаблона.
    echo [!] Впишите ваш BOT_TOKEN в файл .env и запустите start_bot.bat снова!
    notepad ".env"
    pause
    exit /b
)

if not exist ".venv" (
    echo [*] Создаю виртуальное окружение Python...
    python -m venv .venv
)

call .venv\Scripts\activate.bat
echo [*] Проверяю и устанавливаю зависимости...
pip install -r requirements.txt --quiet

echo [*] Запускаю Avito Sniper Pro...
python main.py
pause