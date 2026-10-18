import calendar
from datetime import date


def iso(value: date) -> str:
    return value.isoformat()


def today() -> date:
    return date.today()


def weekday_1_to_7(value: date) -> int:
    """Monday = 1 ... Sunday = 7."""
    return value.weekday() + 1


def add_one_month(value: date) -> date:
    year = value.year + (1 if value.month == 12 else 0)
    month = 1 if value.month == 12 else value.month + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(value.day, last_day))
