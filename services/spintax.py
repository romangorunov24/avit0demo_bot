import random
import re


def render_spintax(text: str, title: str = "", price: int | None = None) -> str:
    pattern = re.compile(r"\{([^{}|]+\|[^{}]+)\}")
    while True:
        match = pattern.search(text)
        if not match:
            break
        options = match.group(1).split("|")
        text = text[: match.start()] + random.choice(options) + text[match.end() :]

    if price:
        price_str = f"{price:,}".replace(",", " ")
        if price > 500:
            raw_bargain = int(round(price * 0.9 / 100.0) * 100)
            bargain_str = f"{raw_bargain:,}".replace(",", " ")
        else:
            bargain_str = price_str
        # Если шаблон сам пишет «₽» после переменной, оставляем как есть
    else:
        # Цена в объявлении не указана: «за ₽» звучало бы нелепо, поэтому подставляем нейтральную фразу вместе со знаком валюты
        text = text.replace("{price_bargain} ₽", "{price_bargain}").replace("{price} ₽", "{price}")
        price_str = "договорную цену"
        bargain_str = "вашу цену"

    text = text.replace("{title}", title or "товар")
    text = text.replace("{price}", price_str)
    text = text.replace("{price_bargain}", bargain_str)
    return text.strip()