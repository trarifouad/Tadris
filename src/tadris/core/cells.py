"""A report's raw values as text (the screen, the PDF) and as Excel values. Amounts go
without « DA » (the column's title says it), rates in %, dates dd/mm/yyyy, « — » for
nothing."""

from datetime import date

from tadris.core.dates import display_date
from tadris.core.money import format_dzd
from tadris.core.percent import format_percent
from tadris.i18n.fr import t

NUMERIC = ("number", "money", "percent")


def display(kind: str, value) -> str:
    if value is None:
        return "—"
    if kind == "money":
        return format_dzd(value).removesuffix(" DA")
    if kind == "percent":
        return format_percent(value)
    if kind == "number":
        return f"{value:,}".replace(",", " ")
    if kind == "date":
        return display_date(value)
    return str(value)


def header(column) -> str:
    """A column's title; an amount's says « (DA) »."""
    return t["reports.col_money"].format(title=column.title) if column.kind == "money" \
        else column.title


def excel_value(kind: str, value):
    """A rate as a fraction (Excel's %), a date as a date; the rest as it is."""
    if value is None:
        return None
    if kind == "percent":
        return value / 10000
    if kind == "date":
        return date.fromisoformat(value[:10])
    return value


def tile_text(tile) -> str:
    """A report's key figure: an amount with « DA »."""
    if tile.value is None:
        return "—"
    return format_dzd(tile.value) if tile.kind == "money" else display(tile.kind, tile.value)
