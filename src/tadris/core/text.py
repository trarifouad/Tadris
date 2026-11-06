import unicodedata


def clean(text: str | None) -> str:
    """Trim and collapse inner whitespace: '  Ben   Ali ' -> 'Ben Ali'."""
    return " ".join((text or "").split())


def group_title(row, name: str = "group_name") -> str:
    """A group as the screens name it, « A · Maths 4AM », from a row with its name (the
    `name` column), its subject and its level."""
    return f"{row[name]} · {row['subject']} {row['level']}"


def fold(text: str | None) -> str | None:
    """Lowercase without accents, for search: 'Hélène' -> 'helene'.

    Registered as the SQL function fold() on every connection.
    """
    if text is None:
        return None
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))
