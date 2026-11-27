from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from urllib.parse import quote

from avito.messenger import render_reply_template
from avito.parser import build_search_url, filter_items, parse_search_page
from database.db import Database
from database.models import AvitoItem, SearchTask
from services.cookie_helper import parse_cookies_input
from services.proxy_helper import build_curl_proxies, mask_proxy, normalize_proxy


class TestAvitoBotSuite(unittest.IsolatedAsyncioTestCase):
    def test_proxy_normalization_and_masking(self) -> None:
        self.assertEqual(
            normalize_proxy("192.168.1.10:8080:myuser:mypass"),
            "http://myuser:mypass@192.168.1.10:8080",
        )
        self.assertEqual(
            normalize_proxy("socks5://user:secret@10.0.0.1:1080"),
            "socks5://user:secret@10.0.0.1:1080",
        )
        self.assertEqual(
            normalize_proxy("10.0.0.2:3128"),
            "http://10.0.0.2:3128",
        )
        self.assertEqual(
            mask_proxy("http://myuser:mypass@192.168.1.10:8080"),
            "http://myuser:***@192.168.1.10:8080",
        )
        proxies = build_curl_proxies("10.0.0.1:8000:u:p")
        self.assertEqual(proxies, {"http": "http://u:p@10.0.0.1:8000", "https": "http://u:p@10.0.0.1:8000"})

        with self.assertRaises(ValueError):
            normalize_proxy("invalid_proxy_string")

    def test_cookie_parser_formats(self) -> None:
        # 1. JSON array (Cookie-Editor)
        json_arr = json.dumps([
            {"name": "sessid", "value": "token_123", "domain": ".avito.ru"},
            {"name": "u", "value": "user_456", "domain": ".avito.ru"},
            {"name": "other", "value": "skip", "domain": ".google.com"},
        ])
        parsed1 = parse_cookies_input(json_arr)
        self.assertTrue(parsed1.is_authenticated)
        self.assertEqual(parsed1.count, 2)
        self.assertEqual(parsed1.cookies["sessid"], "token_123")

        # 2. Raw Cookie header
        raw = "Cookie: sessid=abc999; u=usr888; ft=hello"
        parsed2 = parse_cookies_input(raw)
        self.assertTrue(parsed2.is_authenticated)
        self.assertEqual(parsed2.cookies["u"], "usr888")

    def test_search_url_builder_and_parser(self) -> None:
        url1 = build_search_url("iPhone 15 Pro", region="Москва", min_price=50000, max_price=90000)
        self.assertIn("https://www.avito.ru/moskva?", url1)
        self.assertIn("s=104", url1)
        self.assertIn("pmin=50000", url1)
        self.assertIn("pmax=90000", url1)

        url2 = build_search_url("https://www.avito.ru/tuapse/noutbuki?q=macbook")
        self.assertIn("s=104", url2)

        # Тест парсинга embedded JSON (__initialData__)
        mock_state = {
            "catalog": {
                "items": [
                    {
                        "id": 3981234567,
                        "title": "iPhone 15 Pro 256GB",
                        "urlPath": "/moskva/telefony/iphone_15_pro_256gb_3981234567",
                        "priceDetailed": {"value": 78000, "string": "78 000 ₽"},
                        "geo": {"formattedAddress": "Москва, м. Тверская"},
                        "user": {"id": "seller_777", "name": "Алексей"},
                        "description": "Отличное состояние, полный комплект",
                    },
                    {
                        "id": 3981234568,
                        "title": "iPhone 15 Pro на разбор",
                        "urlPath": "/moskva/telefony/iphone_15_pro_razbor_3981234568",
                        "priceDetailed": {"value": 15000, "string": "15 000 ₽"},
                    },
                ]
            }
        }
        encoded = quote(json.dumps(mock_state, ensure_ascii=False))
        fake_html = f'<html><head><script>window.__initialData__ = "{encoded}";</script></head><body></body></html>'

        items = parse_search_page(fake_html)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].item_id, "3981234567")
        self.assertEqual(items[0].price, 78000)
        self.assertEqual(items[0].seller_id, "seller_777")

        # Проверка фильтрации стоп-слов
        task = SearchTask(
            id=1,
            name="Test",
            search_url=url1,
            min_price=20000,
            max_price=85000,
            exclude_words="разбор, разбитый",
        )
        filtered = filter_items(items, task)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].item_id, "3981234567")

    def test_template_rendering_safety(self) -> None:
        item = AvitoItem(
            item_id="1234567",
            title="Ноутбук {ASUS} ROG",
            price=65000,
            price_text="65 000 ₽",
            url="https://www.avito.ru/test_1234567",
            city="Туапсе",
            seller_name="Мирон",
        )
        tpl = "Привет, {seller}! Интересует {title} за {price} в г. {city}. {unknown_tag}"
        rendered = render_reply_template(tpl, item)
        self.assertIn("Мирон", rendered)
        self.assertIn("Ноутбук {ASUS} ROG", rendered)
        self.assertIn("{unknown_tag}", rendered)

    async def test_database_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db = Database(db_path)
            await db.connect()

            task = await db.create_search(
                name="Тест поиск",
                search_url="https://www.avito.ru/rossiya?q=test&s=104",
                query="test",
            )
            self.assertEqual(task.name, "Тест поиск")
            self.assertTrue(task.is_active)

            item = AvitoItem(
                item_id="999888777",
                title="Тестовый товар",
                price=5000,
                price_text="5 000 ₽",
                url="https://www.avito.ru/item_999888777",
                seller_id="seller_1",
            )
            self.assertFalse(await db.is_item_seen(item.item_id))
            await db.save_seen_item(item, search_id=task.id, notified=True, replied=False)
            self.assertTrue(await db.is_item_seen(item.item_id))

            await db.log_reply(
                item_id=item.item_id,
                seller_id="seller_1",
                channel_id="ch_123",
                message_text="Здравствуйте!",
                status="sent",
            )
            self.assertTrue(await db.has_replied_to_item(item.item_id))
            self.assertTrue(await db.has_replied_to_seller_recently("seller_1", days=7))
            self.assertEqual(await db.count_sent_replies_since(1), 1)

            stats = await db.get_stats()
            self.assertEqual(stats["total_sent_replies"], 1)
            await db.close()


if __name__ == "__main__":
    unittest.main()
