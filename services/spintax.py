import random
import re


def render_spintax(text: str, title: str = "", price: int | None = None) -> str:
    # Сначала раскрываем спинтакс вида {вариант 1|вариант 2} (обязательно с символом |)
    pattern = re.compile(r"\{([^{}|]+\|[^{}]+)\}")
    while True:
        match = pattern.search(text)
        if not match:
            break
        options = match.group(1).split("|")
        text = text[: match.start()] + random.choice(options) + text[match.end() :]

    # Затем подставляем динамические переменные товара
    price_str = f"{price:,}".replace(",", " ") if price else "договорную цену"
    if price and price > 500:
        raw_bargain = int(round(price * 0.9 / 100.0) * 100)
        bargain_str = f"{raw_bargain:,}".replace(",", " ")
    else:
        bargain_str = price_str

    text = text.replace("{title}", title or "товар")
    text = text.replace("{price}", price_str)
    text = text.replace("{price_bargain}", bargain_str)
    return text.strip()