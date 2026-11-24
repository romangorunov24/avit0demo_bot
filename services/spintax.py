import random
import re


def render_spintax(text: str) -> str:
    pattern = re.compile(r"\{([^{}]+)\}")
    while True:
        match = pattern.search(text)
        if not match:
            break
        options = match.group(1).split("|")
        text = text[: match.start()] + random.choice(options) + text[match.end() :]
    return text.strip()