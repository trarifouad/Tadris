from datetime import date, datetime

from tadris.core.dates import display_date
from tadris.core.money import format_dzd
from tadris.core.percent import format_percent

EMPTY = "—"


def display(kind: str, value) -> str:
    """A report cell as text (screen and PDF), by its column kind (models.REPORT_KINDS)."""
    if value is None or value == "":
        return EMPTY
    if kind == "money":
        return format_dzd(value)
    if kind == "percent":
        return format_percent(value)
    if kind == "number":
        return f"{value:,}".replace(",", " ")
    if kind == "date":
        return display_date(value)
    if kind == "datetime":
        return f"{display_date(value)} {value[11:16]}"
    return str(value)


def excel_value(kind: str, value):
    """A report cell as an Excel value: numbers stay numbers, dates become dates."""
    if value is None or value == "":
        return None
    if kind == "percent":
        return value / 10000
    if kind == "date":
        return date.fromisoformat(value[:10])
    if kind == "datetime":
        return datetime.fromisoformat(value)
    return value
