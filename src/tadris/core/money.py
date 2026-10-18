import re

from tadris.core.errors import ValidationError
from tadris.i18n.fr import t

_PARSE = re.compile(r"^[+-]?\d+$")
_SUFFIX = re.compile(r"\s*(DA|DZD)$", re.IGNORECASE)


def format_dzd(amount: int) -> str:
    sign = "-" if amount < 0 else ""
    digits = f"{abs(amount):,}".replace(",", " ")
    return f"{sign}{digits} DA"


def parse_dzd(text: str) -> int:
    raw = _SUFFIX.sub("", text.strip())
    raw = raw.replace("\u00a0", "").replace("\u202f", "").replace(" ", "")
    if not _PARSE.fullmatch(raw):
        raise ValidationError(t["money.invalid"])
    return int(raw)
