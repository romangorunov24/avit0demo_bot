from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import aiosqlite

from database.models import AvitoItem, BotSettings, ReplyLog, SearchTask

logger = logging.getLogger(__name__)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL;")
        await self._conn.execute("PRAGMA foreign_keys=ON;")
        await self._create_tables()
        logger.info("База данных SQLite подключена: %s", self.db_path)

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Соединение с базой данных не инициализировано.")
        return self._conn

    async def _create_tables(self) -> None:
        await self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS searches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                search_url TEXT NOT NULL,
                query TEXT DEFAULT '',
                region TEXT DEFAULT 'rossiya',
                min_price INTEGER,
                max_price INTEGER,
                include_words TEXT DEFAULT '',
                exclude_words TEXT DEFAULT '',
                reply_template TEXT DEFAULT '',
                auto_reply INTEGER DEFAULT 1,
                is_active INTEGER DEFAULT 1,
                initialized INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                last_checked_at TEXT
            );

            CREATE TABLE IF NOT EXISTS seen_items (
                item_id TEXT PRIMARY KEY,
                search_id INTEGER,
                title TEXT NOT NULL,
                price INTEGER DEFAULT 0,
                url TEXT NOT NULL,
                seller_id TEXT DEFAULT '',
                city TEXT DEFAULT '',
                notified INTEGER DEFAULT 0,
                replied INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_seen_items_seller ON seen_items(seller_id, created_at);

            CREATE TABLE IF NOT EXISTS reply_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id TEXT NOT NULL,
                seller_id TEXT DEFAULT '',
                channel_id TEXT DEFAULT '',
                message_text TEXT NOT NULL,
                status TEXT NOT NULL,
                error_message TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_reply_logs_created ON reply_logs(created_at, status);
            """
        )
        await self.conn.commit()

    # -------------------- SETTINGS --------------------

    async def get_setting(self, key: str, default: str = "") -> str:
        cursor = await self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row["value"] if row else default

    async def set_setting(self, key: str, value: Any) -> None:
        str_val = str(value)
        await self.conn.execute(
            """
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, str_val),
        )
        await self.conn.commit()

    async def get_bot_settings(self, default_proxy: str = "") -> BotSettings:
        defaults = BotSettings()
        cursor = await self.conn.execute("SELECT key, value FROM settings")
        rows = await cursor.fetchall()
        raw_map = {r["key"]: r["value"] for r in rows}

        def _int(k: str, fallback: int) -> int:
            try:
                return int(raw_map.get(k, fallback))
            except (TypeError, ValueError):
                return fallback

        def _bool(k: str, fallback: bool) -> bool:
            if k not in raw_map:
                return fallback
            return raw_map[k].lower() in ("1", "true", "yes", "on")

        proxy = raw_map.get("proxy_url", "") or default_proxy

        return BotSettings(
            avito_cookies_json=raw_map.get("avito_cookies_json", defaults.avito_cookies_json),
            guest_cookies_json=raw_map.get("guest_cookies_json", defaults.guest_cookies_json),
            proxy_url=proxy,
            user_agent=raw_map.get("user_agent", defaults.user_agent),
            auto_reply_enabled=_bool("auto_reply_enabled", defaults.auto_reply_enabled),
            default_template=raw_map.get("default_template", defaults.default_template),
            hourly_limit=_int("hourly_limit", defaults.hourly_limit),
            daily_limit=_int("daily_limit", defaults.daily_limit),
            reply_delay_min=_int("reply_delay_min", defaults.reply_delay_min),
            reply_delay_max=_int("reply_delay_max", defaults.reply_delay_max),
            dedup_seller_days=_int("dedup_seller_days", defaults.dedup_seller_days),
            scan_interval_sec=_int("scan_interval_sec", defaults.scan_interval_sec),
            account_user_id=raw_map.get("account_user_id", ""),
            account_name=raw_map.get("account_name", ""),
        )

    # -------------------- SEARCHES --------------------

    def _row_to_search(self, row: aiosqlite.Row) -> SearchTask:
        return SearchTask(
            id=row["id"],
            name=row["name"],
            search_url=row["search_url"],
            query=row["query"] or "",
            region=row["region"] or "rossiya",
            min_price=row["min_price"],
            max_price=row["max_price"],
            include_words=row["include_words"] or "",
            exclude_words=row["exclude_words"] or "",
            reply_template=row["reply_template"] or "",
            auto_reply=bool(row["auto_reply"]),
            is_active=bool(row["is_active"]),
            initialized=bool(row["initialized"]),
            created_at=row["created_at"],
            last_checked_at=row["last_checked_at"],
        )

    async def create_search(
        self,
        name: str,
        search_url: str,
        query: str = "",
        region: str = "rossiya",
        min_price: Optional[int] = None,
        max_price: Optional[int] = None,
        include_words: str = "",
        exclude_words: str = "",
        reply_template: str = "",
        auto_reply: bool = True,
    ) -> SearchTask:
        now = utc_now_iso()
        cursor = await self.conn.execute(
            """
            INSERT INTO searches (
                name, search_url, query, region, min_price, max_price,
                include_words, exclude_words, reply_template, auto_reply,
                is_active, initialized, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0, ?)
            """,
            (
                name,
                search_url,
                query,
                region,
                min_price,
                max_price,
                include_words,
                exclude_words,
                reply_template,
                1 if auto_reply else 0,
                now,
            ),
        )
        await self.conn.commit()
        search_id = cursor.lastrowid
        created = await self.get_search(search_id)
        assert created is not None
        return created

    async def get_search(self, search_id: int) -> Optional[SearchTask]:
        cursor = await self.conn.execute("SELECT * FROM searches WHERE id = ?", (search_id,))
        row = await cursor.fetchone()
        return self._row_to_search(row) if row else None

    async def list_searches(self, only_active: bool = False) -> list[SearchTask]:
        sql = "SELECT * FROM searches"
        if only_active:
            sql += " WHERE is_active = 1"
        sql += " ORDER BY id DESC"
        cursor = await self.conn.execute(sql)
        rows = await cursor.fetchall()
        return [self._row_to_search(r) for r in rows]

    async def toggle_search_active(self, search_id: int) -> Optional[SearchTask]:
        task = await self.get_search(search_id)
        if not task:
            return None
        new_val = 0 if task.is_active else 1
        await self.conn.execute("UPDATE searches SET is_active = ? WHERE id = ?", (new_val, search_id))
        await self.conn.commit()
        return await self.get_search(search_id)

    async def toggle_search_autoreply(self, search_id: int) -> Optional[SearchTask]:
        task = await self.get_search(search_id)
        if not task:
            return None
        new_val = 0 if task.auto_reply else 1
        await self.conn.execute("UPDATE searches SET auto_reply = ? WHERE id = ?", (new_val, search_id))
        await self.conn.commit()
        return await self.get_search(search_id)

    async def update_search_template(self, search_id: int, template: str) -> None:
        await self.conn.execute(
            "UPDATE searches SET reply_template = ? WHERE id = ?",
            (template, search_id),
        )
        await self.conn.commit()

    async def update_search_filters(
        self, search_id: int, include_words: str, exclude_words: str
    ) -> None:
        await self.conn.execute(
            "UPDATE searches SET include_words = ?, exclude_words = ? WHERE id = ?",
            (include_words, exclude_words, search_id),
        )
        await self.conn.commit()

    async def mark_search_checked(self, search_id: int, initialized: bool = True) -> None:
        now = utc_now_iso()
        await self.conn.execute(
            "UPDATE searches SET last_checked_at = ?, initialized = ? WHERE id = ?",
            (now, 1 if initialized else 0, search_id),
        )
        await self.conn.commit()

    async def delete_search(self, search_id: int) -> None:
        await self.conn.execute("DELETE FROM searches WHERE id = ?", (search_id,))
        await self.conn.commit()

    # -------------------- SEEN ITEMS & DEDUP --------------------

    async def is_item_seen(self, item_id: str) -> bool:
        cursor = await self.conn.execute(
            "SELECT 1 FROM seen_items WHERE item_id = ? LIMIT 1", (item_id,)
        )
        return (await cursor.fetchone()) is not None

    async def save_seen_item(
        self,
        item: AvitoItem,
        search_id: int,
        notified: bool = False,
        replied: bool = False,
    ) -> None:
        now = utc_now_iso()
        await self.conn.execute(
            """
            INSERT OR IGNORE INTO seen_items (
                item_id, search_id, title, price, url, seller_id, city, notified, replied, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.item_id,
                search_id,
                item.title,
                item.price,
                item.url,
                item.seller_id,
                item.city,
                1 if notified else 0,
                1 if replied else 0,
                now,
            ),
        )
        await self.conn.commit()

    async def mark_item_replied(self, item_id: str) -> None:
        await self.conn.execute(
            "UPDATE seen_items SET replied = 1 WHERE item_id = ?", (item_id,)
        )
        await self.conn.commit()

    async def has_replied_to_item(self, item_id: str) -> bool:
        cursor = await self.conn.execute(
            "SELECT 1 FROM reply_logs WHERE item_id = ? AND status = 'sent' LIMIT 1",
            (item_id,),
        )
        return (await cursor.fetchone()) is not None

    async def has_replied_to_seller_recently(self, seller_id: str, days: int) -> bool:
        if not seller_id or days <= 0:
            return False
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        cursor = await self.conn.execute(
            """
            SELECT 1 FROM reply_logs
            WHERE seller_id = ? AND status = 'sent' AND created_at >= ?
            LIMIT 1
            """,
            (seller_id, cutoff),
        )
        return (await cursor.fetchone()) is not None

    # -------------------- REPLY LOGS & STATS --------------------

    async def log_reply(
        self,
        item_id: str,
        seller_id: str,
        channel_id: str,
        message_text: str,
        status: str,
        error_message: str = "",
    ) -> None:
        now = utc_now_iso()
        await self.conn.execute(
            """
            INSERT INTO reply_logs (
                item_id, seller_id, channel_id, message_text, status, error_message, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (item_id, seller_id, channel_id, message_text, status, error_message, now),
        )
        if status == "sent":
            await self.conn.execute(
                "UPDATE seen_items SET replied = 1 WHERE item_id = ?", (item_id,)
            )
        await self.conn.commit()

    async def count_sent_replies_since(self, hours: int) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        cursor = await self.conn.execute(
            "SELECT COUNT(*) AS cnt FROM reply_logs WHERE status = 'sent' AND created_at >= ?",
            (cutoff,),
        )
        row = await cursor.fetchone()
        return int(row["cnt"]) if row else 0

    async def get_stats(self) -> dict[str, Any]:
        cur_searches = await self.conn.execute("SELECT COUNT(*) AS total, SUM(is_active) AS active FROM searches")
        s_row = await cur_searches.fetchone()

        cur_items = await self.conn.execute("SELECT COUNT(*) AS total FROM seen_items")
        i_row = await cur_items.fetchone()

        cur_replies = await self.conn.execute(
            "SELECT COUNT(*) AS total FROM reply_logs WHERE status = 'sent'"
        )
        r_row = await cur_replies.fetchone()

        sent_1h = await self.count_sent_replies_since(1)
        sent_24h = await self.count_sent_replies_since(24)

        cur_err = await self.conn.execute(
            """
            SELECT error_message, created_at FROM reply_logs
            WHERE status = 'error' AND error_message != ''
            ORDER BY id DESC LIMIT 1
            """
        )
        err_row = await cur_err.fetchone()

        return {
            "total_searches": int(s_row["total"] or 0),
            "active_searches": int(s_row["active"] or 0),
            "total_seen_items": int(i_row["total"] or 0),
            "total_sent_replies": int(r_row["total"] or 0),
            "sent_last_hour": sent_1h,
            "sent_last_24h": sent_24h,
            "last_error": f"{err_row['created_at']}: {err_row['error_message']}" if err_row else "Нет",
        }
