@echo off
chcp 65001 >nul
title Avito Sniper Pro - Local Runner
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [!] Python не найден. Установите Python 3.11 или новее с python.org
    echo     и поставьте галочку "Add Python to PATH", затем запустите файл снова.
    pause
    exit /b 1
)

if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo [!] Файл .env создан из шаблона.
    echo [!] Впишите BOT_TOKEN и ADMIN_IDS в файл .env и запустите start_bot.bat снова!
    notepad ".env"
    pause
    exit /b
)

if not exist ".venv" (
    echo [*] Создаю виртуальное окружение Python...
    python -m venv .venv
    if errorlevel 1 (
        echo [!] Не удалось создать виртуальное окружение.
        pause
        exit /b 1
    )
)

call .venv\Scripts\activate.bat
echo [*] Проверяю и устанавливаю зависимости...
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [!] Не удалось установить зависимости. Проверьте интернет и запустите снова.
    pause
    exit /b 1
)

echo [*] Запускаю Avito Sniper Pro...
python main.py
echo.
echo [!] Бот остановился. Если выше есть ошибка, пришлите её разработчику.
pause
