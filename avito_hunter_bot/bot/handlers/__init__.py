from __future__ import annotations

from aiogram import Router

from bot.handlers.account import router as account_router
from bot.handlers.autoreply import router as autoreply_router
from bot.handlers.searches import router as searches_router
from bot.handlers.start import router as start_router


def get_main_router() -> Router:
    root = Router()
    root.include_router(start_router)
    root.include_router(searches_router)
    root.include_router(account_router)
    root.include_router(autoreply_router)
    return root
