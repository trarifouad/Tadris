import calendar
import re
from datetime import date

from tadris.core.errors import ValidationError
from tadris.i18n.fr import t

_DISPLAY = re.compile(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})")


def iso(value: date) -> str:
    return value.isoformat()


def today() -> date:
    return date.today()


def weekday_1_to_7(value: date) -> int:
    """Monday = 1 ... Sunday = 7."""
    return value.weekday() + 1


def display_date(value: str) -> str:
    """ISO date or timestamp to the French display form: '2026-10-18T14:05:00' -> '18/10/2026'."""
    return date.fromisoformat(value[:10]).strftime("%d/%m/%Y")


def parse_display_date(text: str) -> date | None:
    """'18/10/2026' (also 18.10.2026, 18-10-2026) -> date. Blank -> None."""
    raw = text.strip()
    if not raw:
        return None
    match = _DISPLAY.fullmatch(raw)
    try:
        if match is None:
            raise ValueError(raw)
        day, month, year = (int(part) for part in match.groups())
        return date(year, month, day)
    except ValueError as exc:
        raise ValidationError(t["date.invalid"]) from exc


def add_one_month(value: date) -> date:
    year = value.year + (1 if value.month == 12 else 0)
    month = 1 if value.month == 12 else value.month + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(value.day, last_day))
