import unicodedata


def clean(text: str | None) -> str:
    """Trim and collapse inner whitespace: '  Ben   Ali ' -> 'Ben Ali'."""
    return " ".join((text or "").split())


def fold(text: str | None) -> str | None:
    """Lowercase without accents, for search: 'Hélène' -> 'helene'.

    Registered as the SQL function fold() on every connection.
    """
    if text is None:
        return None
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))
