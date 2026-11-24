import os
import aiosqlite
from config import settings

DEFAULT_SETTINGS = {
    "spintax_template": (
        "{Привет|Здравствуйте|Добрый день}! "
        "{Заинтересовал|Хочу забрать} {title}. "
        "{Готов приехать сегодня забрать|Когда можно посмотреть?}"
    ),
    "hourly_limit": "15",
    "auto_reply_enabled": "1",
    "night_mode": "0",
}


async def init_db() -> None:
    db_dir = os.path.dirname(os.path.abspath(settings.DB_PATH))
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    async with aiosqlite.connect(settings.DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS searches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                url TEXT NOT NULL,
                min_price INTEGER DEFAULT 0,
                max_price INTEGER DEFAULT 0,
                sniper_price INTEGER DEFAULT 0,
                stop_words TEXT DEFAULT '',
                plus_words TEXT DEFAULT '',
                only_private INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS seen_items (
                item_id TEXT PRIMARY KEY,
                search_id INTEGER,
                price INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS avito_account (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                cookies_json TEXT DEFAULT '',
                is_valid INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS blacklist (
                seller_id TEXT PRIMARY KEY,
                reason TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sent_messages_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id TEXT,
                seller_id TEXT,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        for key, value in DEFAULT_SETTINGS.items():
            await db.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )
        await db.commit()
