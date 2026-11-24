from typing import Any
import aiosqlite
from config import settings

ALLOWED_SEARCH_FIELDS = {
    "name",
    "url",
    "min_price",
    "max_price",
    "sniper_price",
    "stop_words",
    "plus_words",
    "only_private",
    "is_active",
}


def _connect():
    return aiosqlite.connect(settings.DB_PATH)


# --- Поиски ---

async def add_search(name: str, url: str) -> int:
    async with _connect() as db:
        cursor = await db.execute(
            "INSERT INTO searches (name, url) VALUES (?, ?)",
            (name, url),
        )
        await db.commit()
        return cursor.lastrowid


async def get_searches(only_active: bool = False) -> list[dict[str, Any]]:
    query = "SELECT * FROM searches"
    if only_active:
        query += " WHERE is_active = 1"
    query += " ORDER BY id DESC"
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(query)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_search(search_id: int) -> dict[str, Any] | None:
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM searches WHERE id = ?", (search_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def update_search_field(search_id: int, field: str, value: Any) -> None:
    if field not in ALLOWED_SEARCH_FIELDS:
        raise ValueError(f"Invalid field: {field}")
    async with _connect() as db:
        await db.execute(f"UPDATE searches SET {field} = ? WHERE id = ?", (value, search_id))
        await db.commit()


async def delete_search(search_id: int) -> None:
    async with _connect() as db:
        await db.execute("DELETE FROM searches WHERE id = ?", (search_id,))
        await db.commit()


# --- История объявлений и рыночная цена ---

async def has_seen_items_for_search(search_id: int) -> bool:
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT 1 FROM seen_items WHERE search_id = ? LIMIT 1",
            (search_id,),
        )
        return (await cursor.fetchone()) is not None


async def is_item_seen(item_id: str) -> bool:
    async with _connect() as db:
        cursor = await db.execute("SELECT 1 FROM seen_items WHERE item_id = ?", (item_id,))
        return (await cursor.fetchone()) is not None


async def add_seen_item(item_id: str, search_id: int, price: int) -> None:
    async with _connect() as db:
        await db.execute(
            "INSERT OR IGNORE INTO seen_items (item_id, search_id, price) VALUES (?, ?, ?)",
            (item_id, search_id, price),
        )
        await db.commit()


async def get_average_price(search_id: int, limit: int = 50) -> float | None:
    async with _connect() as db:
        cursor = await db.execute(
            """
            SELECT AVG(price) FROM (
                SELECT price FROM seen_items
                WHERE search_id = ? AND price > 0
                ORDER BY created_at DESC LIMIT ?
            )
            """,
            (search_id, limit),
        )
        row = await cursor.fetchone()
        return float(row[0]) if row and row[0] is not None else None


# --- Аккаунт Авито ---

async def save_cookies(cookies_json: str, is_valid: int = 1) -> None:
    async with _connect() as db:
        await db.execute(
            """
            INSERT INTO avito_account (id, cookies_json, is_valid, updated_at)
            VALUES (1, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                cookies_json = excluded.cookies_json,
                is_valid = excluded.is_valid,
                updated_at = CURRENT_TIMESTAMP
            """,
            (cookies_json, is_valid),
        )
        await db.commit()


async def get_account() -> dict[str, Any] | None:
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM avito_account WHERE id = 1")
        row = await cursor.fetchone()
        return dict(row) if row else None


async def set_account_validity(is_valid: int) -> None:
    async with _connect() as db:
        await db.execute("UPDATE avito_account SET is_valid = ? WHERE id = 1", (is_valid,))
        await db.commit()


# --- Настройки и лимиты ---

async def get_setting(key: str, default: str = "") -> str:
    async with _connect() as db:
        cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row[0] if row else default


async def set_setting(key: str, value: str) -> None:
    async with _connect() as db:
        await db.execute(
            """
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        await db.commit()


async def log_sent_message(item_id: str, seller_id: str) -> None:
    async with _connect() as db:
        await db.execute(
            "INSERT INTO sent_messages_log (item_id, seller_id) VALUES (?, ?)",
            (item_id, seller_id),
        )
        await db.commit()


async def get_sent_count_last_hour() -> int:
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM sent_messages_log WHERE sent_at >= datetime('now', '-1 hour')"
        )
        row = await cursor.fetchone()
        return int(row[0]) if row else 0


# --- Черный список продавцов ---

async def add_to_blacklist(seller_id: str, reason: str = "Добавлен вручную") -> None:
    async with _connect() as db:
        await db.execute(
            "INSERT OR IGNORE INTO blacklist (seller_id, reason) VALUES (?, ?)",
            (seller_id, reason),
        )
        await db.commit()


async def is_blacklisted(seller_id: str) -> bool:
    async with _connect() as db:
        cursor = await db.execute("SELECT 1 FROM blacklist WHERE seller_id = ?", (seller_id,))
        return (await cursor.fetchone()) is not None


async def get_blacklist_count() -> int:
    async with _connect() as db:
        cursor = await db.execute("SELECT COUNT(*) FROM blacklist")
        row = await cursor.fetchone()
        return int(row[0]) if row else 0
