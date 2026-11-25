"""Шифрование cookies Авито в базе (Fernet). Ключ берётся из COOKIES_KEY или создаётся в data/cookies.key."""
import logging
import os

from cryptography.fernet import Fernet, InvalidToken

from config import settings

PREFIX = "enc:"
_fernet: Fernet | None = None


def _get() -> Fernet:
    global _fernet
    if _fernet is not None:
        return _fernet
    key = settings.COOKIES_KEY
    if not key:
        directory = os.path.dirname(settings.DB_PATH) or "."
        path = os.path.join(directory, "cookies.key")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                key = f.read().strip()
        else:
            os.makedirs(directory, exist_ok=True)
            key = Fernet.generate_key().decode()
            with open(path, "w", encoding="utf-8") as f:
                f.write(key)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
    _fernet = Fernet(key.encode())
    return _fernet


def encrypt(value: str | None) -> str | None:
    if not value or value.startswith(PREFIX):
        return value
    return PREFIX + _get().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt(value: str | None) -> str | None:
    if not value or not value.startswith(PREFIX):
        return value
    try:
        return _get().decrypt(value[len(PREFIX):].encode("utf-8")).decode("utf-8")
    except InvalidToken:
        logging.getLogger(__name__).error(
            "Не удалось расшифровать cookies: ключ шифрования изменился или потерян (COOKIES_KEY / data/cookies.key). "
            "Подключите аккаунт Avito заново и задайте постоянный COOKIES_KEY."
        )
        return None
