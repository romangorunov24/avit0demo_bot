from __future__ import annotations


class AvitoBaseError(Exception):
    """Базовое исключение при работе с Avito."""


class AvitoRateLimitError(AvitoBaseError):
    """Превышен лимит запросов или сработала антибот-защита (HTTP 429 / 439)."""

    def __init__(self, message: str = "Rate limit / антибот защита Avito", status_code: int = 429):
        super().__init__(message)
        self.status_code = status_code


class AvitoAuthError(AvitoBaseError):
    """Ошибка авторизации, невалидные или протухшие cookies, либо запрос капчи."""


class AvitoProxyError(AvitoBaseError):
    """Ошибка подключения через прокси-сервер."""


class AvitoParseError(AvitoBaseError):
    """Ошибка извлечения данных объявлений со страницы Avito."""


class AvitoMessengerError(AvitoBaseError):
    """Ошибка при создании диалога или отправке сообщения продавцу."""
