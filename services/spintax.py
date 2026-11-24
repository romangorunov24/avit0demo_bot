import random
import re

_SPINTAX_PATTERN = re.compile(r"\{([^{}]+)\}")


def render_spintax(template: str, title: str = "", price: int = 0) -> str:
    """Раскрывает конструкции {вариант 1|вариант 2} и подставляет переменные объявления."""
    text = template.replace("{title}", title).replace("{price}", f"{price:,}".replace(",", " "))
    while True:
        match = _SPINTAX_PATTERN.search(text)
        if not match:
            break
        options = match.group(1).split("|")
        chosen = random.choice(options)
        text = text[: match.start()] + chosen + text[match.end() :]
    return text.strip()
