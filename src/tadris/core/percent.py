import re

from tadris.core.errors import ValidationError
from tadris.i18n.fr import t

# Teacher rates are stored as basis points: 60 % -> 6000, 62,5 % -> 6250.
_PERCENT = re.compile(r"^(\d{1,3})(?:[.,](\d{1,2}))?$")


def parse_percent(text: str) -> int:
    """'60', '62,5', '62.5 %' -> basis points. Between 0 and 100 with at most 2 decimals."""
    raw = text.strip().removesuffix("%").strip().replace(" ", "")
    match = _PERCENT.fullmatch(raw)
    if match is None:
        raise ValidationError(t["percent.invalid"])
    whole, decimals = match.group(1), (match.group(2) or "").ljust(2, "0")
    bp = int(whole) * 100 + int(decimals)
    if bp > 10000:
        raise ValidationError(t["percent.invalid"])
    return bp


def format_percent(bp: int) -> str:
    """6000 -> '60 %', 6250 -> '62,5 %', 6255 -> '62,55 %'."""
    whole, rest = divmod(bp, 100)
    if rest == 0:
        return f"{whole} %"
    return f"{whole},{rest:02d}".rstrip("0") + " %"


def apply_rate(amount: int, bp: int) -> int:
    """Whole-DZD share of an amount at a rate, rounded down (payouts never overpay)."""
    return amount * bp // 10000
