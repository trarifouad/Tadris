import calendar
from datetime import date


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


def add_one_month(value: date) -> date:
    year = value.year + (1 if value.month == 12 else 0)
    month = 1 if value.month == 12 else value.month + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(value.day, last_day))
