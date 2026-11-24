import os
import aiosqlite
from config import settings

DB_FILE = settings.DB_PATH


async def _ensure_column(db: aiosqlite.Connection, table: str, column: str, definition: str) -> None:
    cur = await db.execute(f"PRAGMA table_info({table})")
    cols = [row[1] for row in await cur.fetchall()]
    if column not in cols:
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


async def init_db() -> None:
    db_dir = os.path.dirname(DB_FILE)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    default_admin = settings.admin_ids_list[0] if settings.admin_ids_list else 0

    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                avito_cookies TEXT,
                default_template TEXT DEFAULT '{Здравствуйте|Добрый день}! {Объявление ещё актуально|Ещё продаёте}? Готов забрать сегодня.',
                bargain_template TEXT DEFAULT '{Здравствуйте|Добрый день}! За {price_bargain} ₽ отдадите, если подъеду сегодня?',
                delivery_template TEXT DEFAULT '{Здравствуйте|Добрый день}! Авито Доставкой сможете отправить?',
                is_paused INTEGER DEFAULT 0,
                only_profitable INTEGER DEFAULT 0,
                min_discount_pct INTEGER DEFAULT 10,
                seller_filter TEXT DEFAULT 'all',
                quiet_hours TEXT,
                auto_reply_enabled INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS searches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 0,
                name TEXT NOT NULL,
                url TEXT NOT NULL,
                min_price INTEGER,
                max_price INTEGER,
                sniper_price INTEGER,
                plus_words TEXT,
                stop_words TEXT,
                seller_filter TEXT DEFAULT 'all',
                message_template TEXT,
                auto_reply INTEGER DEFAULT 0,
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
                user_id INTEGER NOT NULL DEFAULT 0,
                seller_id TEXT NOT NULL,
                PRIMARY KEY (user_id, seller_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS allowed_users (
                user_id INTEGER PRIMARY KEY,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS favorites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                item_id TEXT NOT NULL,
                title TEXT NOT NULL,
                price INTEGER,
                url TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, item_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS recent_items (
                item_id TEXT PRIMARY KEY,
                search_name TEXT,
                title TEXT,
                price INTEGER,
                url TEXT,
                location TEXT,
                seller_type TEXT,
                description TEXT,
                discount_pct INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Безопасная миграция существующей базы
        await _ensure_column(db, "users", "bargain_template", "TEXT DEFAULT '{Здравствуйте|Добрый день}! За {price_bargain} ₽ отдадите, если подъеду сегодня?'")
        await _ensure_column(db, "users", "delivery_template", "TEXT DEFAULT '{Здравствуйте|Добрый день}! Авито Доставкой сможете отправить?'")
        await _ensure_column(db, "users", "is_paused", "INTEGER DEFAULT 0")
        await _ensure_column(db, "users", "only_profitable", "INTEGER DEFAULT 0")
        await _ensure_column(db, "users", "min_discount_pct", "INTEGER DEFAULT 10")
        await _ensure_column(db, "users", "seller_filter", "TEXT DEFAULT 'all'")
        await _ensure_column(db, "users", "quiet_hours", "TEXT")
        await _ensure_column(db, "users", "auto_reply_enabled", "INTEGER DEFAULT 0")

        await _ensure_column(db, "searches", "user_id", f"INTEGER NOT NULL DEFAULT {default_admin}")
        await _ensure_column(db, "searches", "min_price", "INTEGER")
        await _ensure_column(db, "searches", "max_price", "INTEGER")
        await _ensure_column(db, "searches", "sniper_price", "INTEGER")
        await _ensure_column(db, "searches", "plus_words", "TEXT")
        await _ensure_column(db, "searches", "stop_words", "TEXT")
        await _ensure_column(db, "searches", "seller_filter", "TEXT DEFAULT 'all'")
        await _ensure_column(db, "searches", "message_template", "TEXT")
        await _ensure_column(db, "searches", "auto_reply", "INTEGER DEFAULT 0")
        await _ensure_column(db, "searches", "is_active", "INTEGER DEFAULT 1")
        await _ensure_column(db, "searches", "is_initialized", "INTEGER DEFAULT 0")
        await _ensure_column(db, "blacklist", "user_id", f"INTEGER NOT NULL DEFAULT {default_admin}")

        if default_admin:
            await db.execute("UPDATE searches SET user_id = ? WHERE user_id = 0 OR user_id IS NULL", (default_admin,))

        await db.commit()


async def is_user_allowed(user_id: int) -> bool:
    async with aiosqlite.connect(DB_FILE) as db:
        cur = await db.execute("SELECT 1 FROM allowed_users WHERE user_id = ?", (user_id,))
        return (await cur.fetchone()) is not None


async def grant_user_access(user_id: int) -> None:
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("INSERT OR IGNORE INTO allowed_users (user_id) VALUES (?)", (user_id,))
        await db.commit()


async def revoke_user_access(user_id: int) -> None:
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("DELETE FROM allowed_users WHERE user_id = ?", (user_id,))
        await db.commit()


async def get_user_settings(user_id: int) -> dict:
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        await db.commit()
        cur = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        return dict(row) if row else {"user_id": user_id}


async def update_user_field(user_id: int, field: str, value: object) -> None:
    allowed = {
        "avito_cookies",
        "default_template",
        "bargain_template",
        "delivery_template",
        "is_paused",
        "only_profitable",
        "min_discount_pct",
        "seller_filter",
        "quiet_hours",
        "auto_reply_enabled",
    }
    if field not in allowed:
        return
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        await db.execute(f"UPDATE users SET {field} = ? WHERE user_id = ?", (value, user_id))
        await db.commit()


async def add_search(
    user_id: int,
    name: str,
    url: str,
    min_price: int | None = None,
    max_price: int | None = None,
    sniper_price: int | None = None,
    plus_words: str | None = None,
    stop_words: str | None = None,
    message_template: str | None = None,
) -> int:
    async with aiosqlite.connect(DB_FILE) as db:
        cur = await db.execute(
            """
            INSERT INTO searches (
                user_id, name, url, min_price, max_price, sniper_price,
                plus_words, stop_words, message_template
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, name, url, min_price, max_price, sniper_price, plus_words, stop_words, message_template),
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
    allowed = {
        "name",
        "is_active",
        "auto_reply",
        "message_template",
        "plus_words",
        "stop_words",
        "min_price",
        "max_price",
        "sniper_price",
        "seller_filter",
        "is_initialized",
    }
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


async def save_recent_item(item: dict, search_name: str) -> None:
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO recent_items (
                item_id, search_name, title, price, url, location, seller_type, description, discount_pct
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(item["id"]),
                search_name,
                item.get("title", ""),
                item.get("price"),
                item.get("url", ""),
                item.get("location", "Не указано"),
                item.get("seller_type", "Частное лицо"),
                item.get("description", ""),
                item.get("discount_pct", 0),
            ),
        )
        await db.commit()


async def get_recent_item(item_id: str) -> dict | None:
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM recent_items WHERE item_id = ?", (str(item_id),))
        row = await cur.fetchone()
        return dict(row) if row else None


async def add_to_blacklist(user_id: int, seller_id: str) -> None:
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "INSERT OR IGNORE INTO blacklist (user_id, seller_id) VALUES (?, ?)",
            (user_id, str(seller_id)),
        )
        await db.commit()


async def remove_from_blacklist(user_id: int, seller_id: str) -> None:
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "DELETE FROM blacklist WHERE user_id = ? AND seller_id = ?",
            (user_id, str(seller_id)),
        )
        await db.commit()


async def get_blacklist(user_id: int) -> list[str]:
    async with aiosqlite.connect(DB_FILE) as db:
        cur = await db.execute("SELECT seller_id FROM blacklist WHERE user_id = ?", (user_id,))
        rows = await cur.fetchall()
        return [str(r[0]) for r in rows]


async def is_seller_blacklisted(user_id: int, seller_id: str) -> bool:
    async with aiosqlite.connect(DB_FILE) as db:
        cur = await db.execute(
            "SELECT 1 FROM blacklist WHERE user_id = ? AND seller_id = ?",
            (user_id, str(seller_id)),
        )
        return (await cur.fetchone()) is not None


async def add_favorite(user_id: int, item_id: str, title: str, price: int | None, url: str) -> None:
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO favorites (user_id, item_id, title, price, url)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, str(item_id), title, price, url),
        )
        await db.commit()


async def get_favorites(user_id: int, limit: int = 15) -> list[dict]:
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM favorites WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def remove_favorite(fav_id: int, user_id: int) -> None:
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("DELETE FROM favorites WHERE id = ? AND user_id = ?", (fav_id, user_id))
        await db.commit()