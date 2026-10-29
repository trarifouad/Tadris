import re

from tadris.core.errors import ValidationError
from tadris.i18n.fr import t

_SEPARATORS = re.compile(r"[\s.\-/()]")
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
# Mobiles: 05, 06 or 07 plus 8 digits. Landlines: 02, 03 or 04 plus 7 digits.
_MOBILE = re.compile(r"0[567][0-9]{8}")
_LANDLINE = re.compile(r"0[2-4][0-9]{7}")


def normalize_phone(text: str | None) -> str | None:
    """'+213 661 90 25 47' -> '0661902547'. Blank -> None. Stored phones are always normalized."""
    if text is None:
        return None
    raw = _SEPARATORS.sub("", text.translate(_ARABIC_DIGITS))
    if not raw:
        return None
    if raw.startswith("+213"):
        raw = "0" + raw[4:]
    elif raw.startswith("00213"):
        raw = "0" + raw[5:]
    if not (_MOBILE.fullmatch(raw) or _LANDLINE.fullmatch(raw)):
        raise ValidationError(t["phone.invalid"])
    return raw


def is_mobile(phone: str | None) -> bool:
    """A normalized mobile number (05, 06 or 07), the only kind with WhatsApp."""
    return bool(phone) and _MOBILE.fullmatch(phone) is not None


def format_phone(phone: str | None) -> str:
    """'0661902547' -> '0661 90 25 47', '048551230' -> '048 55 12 30'."""
    if not phone:
        return ""
    head = 4 if len(phone) == 10 else 3
    rest = phone[head:]
    return " ".join([phone[:head], *(rest[i:i + 2] for i in range(0, len(rest), 2))])


def digits(text: str) -> str:
    return "".join(ch for ch in text.translate(_ARABIC_DIGITS) if "0" <= ch <= "9")
