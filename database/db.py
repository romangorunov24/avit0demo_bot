import os
import aiosqlite
from config import settings

DB_FILE = settings.DB_PATH


async def init_db() -> None:
    db_dir = os.path.dirname(DB_FILE)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                avito_cookies TEXT,
                default_template TEXT DEFAULT 'Здравствуйте! Объявление ещё актуально?',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS searches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                url TEXT NOT NULL,
                min_price INTEGER,
                max_price INTEGER,
                stop_words TEXT,
                message_template TEXT,
                auto_reply INTEGER DEFAULT 1,
                is_active INTEGER DEFAULT 1,
                is_initialized INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS seen_items (
                search_id INTEGER NOT NULL,
                item_id TEXT NOT NULL,
                PRIMARY KEY (search_id, item_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS blacklist (
                user_id INTEGER NOT NULL,
                seller_id TEXT NOT NULL,
                PRIMARY KEY (user_id, seller_id)
            )
        """)
        await db.commit()


async def get_user_settings(user_id: int) -> dict:
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        await db.commit()
        cur = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        return dict(row) if row else {"user_id": user_id}


async def save_user_cookies(user_id: int, cookies_json: str | None) -> None:
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        await db.execute("UPDATE users SET avito_cookies = ? WHERE user_id = ?", (cookies_json, user_id))
        await db.commit()


async def save_default_template(user_id: int, template: str) -> None:
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        await db.execute("UPDATE users SET default_template = ? WHERE user_id = ?", (template, user_id))
        await db.commit()


async def add_search(
    user_id: int,
    name: str,
    url: str,
    min_price: int | None = None,
    max_price: int | None = None,
    stop_words: str | None = None,
    message_template: str | None = None,
) -> int:
    async with aiosqlite.connect(DB_FILE) as db:
        cur = await db.execute(
            """
            INSERT INTO searches (user_id, name, url, min_price, max_price, stop_words, message_template)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, name, url, min_price, max_price, stop_words, message_template),
        )
        await db.commit()
        return cur.lastrowid


async def get_user_searches(user_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM searches WHERE user_id = ? ORDER BY id DESC", (user_id,))
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_active_searches() -> list[dict]:
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM searches WHERE is_active = 1")
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_search_by_id(search_id: int) -> dict | None:
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM searches WHERE id = ?", (search_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def update_search_field(search_id: int, field: str, value: object) -> None:
    allowed = {"is_active", "auto_reply", "message_template", "stop_words", "min_price", "max_price", "is_initialized"}
    if field not in allowed:
        return
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(f"UPDATE searches SET {field} = ? WHERE id = ?", (value, search_id))
        await db.commit()


async def delete_search(search_id: int) -> None:
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("DELETE FROM searches WHERE id = ?", (search_id,))
        await db.execute("DELETE FROM seen_items WHERE search_id = ?", (search_id,))
        await db.commit()


async def is_search_initialized(search_id: int) -> bool:
    async with aiosqlite.connect(DB_FILE) as db:
        cur = await db.execute("SELECT is_initialized FROM searches WHERE id = ?", (search_id,))
        row = await cur.fetchone()
        return bool(row and row[0])


async def is_item_seen(search_id: int, item_id: str) -> bool:
    async with aiosqlite.connect(DB_FILE) as db:
        cur = await db.execute(
            "SELECT 1 FROM seen_items WHERE search_id = ? AND item_id = ?",
            (search_id, str(item_id)),
        )
        return (await cur.fetchone()) is not None


async def mark_item_seen(search_id: int, item_id: str) -> None:
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "INSERT OR IGNORE INTO seen_items (search_id, item_id) VALUES (?, ?)",
            (search_id, str(item_id)),
        )
        await db.commit()


async def add_to_blacklist(user_id: int, seller_id: str) -> None:
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "INSERT OR IGNORE INTO blacklist (user_id, seller_id) VALUES (?, ?)",
            (user_id, str(seller_id)),
        )
        await db.commit()


async def is_seller_blacklisted(user_id: int, seller_id: str) -> bool:
    async with aiosqlite.connect(DB_FILE) as db:
        cur = await db.execute(
            "SELECT 1 FROM blacklist WHERE user_id = ? AND seller_id = ?",
            (user_id, str(seller_id)),
        )
        return (await cur.fetchone()) is not None