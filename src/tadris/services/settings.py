from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError, ValidationError
from tadris.core.permissions import require
from tadris.db.errors import atomic
from tadris.i18n.fr import t
from tadris.repositories import timetable as timetable_repo
from tadris.services import audit

# Opening hours used until the director sets them (the timetable grid's former range).
DEFAULT_OPENS_AT = "08:00"
DEFAULT_CLOSES_AT = "20:00"

KEYS: dict[str, type] = {
    "school.name": str,
    "school.address": str,
    "school.phone": str,
    "school.opens_at": str,
    "school.closes_at": str,
    "defaults.registration_fee": int,
    "defaults.max_debt_warning": int,
    "defaults.group_price": int,
    "receipt.header": str,
    "receipt.footer": str,
    "backup.second_dir": str,
    "backup.school_id": str,
}


def get(conn, key: str, default=None):
    if key not in KEYS:
        raise ValidationError(t["settings.unknown_key"])
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    return KEYS[key](row[0])


HOUR_KEYS = ("school.opens_at", "school.closes_at")  # set together, see set_school_hours


def _coerce(key: str, value) -> str:
    """The stored text of a value, checked."""
    if key not in KEYS:
        raise ValidationError(t["settings.unknown_key"])
    if KEYS[key] is int:
        try:
            return str(int(value))
        except (TypeError, ValueError) as exc:
            raise ValidationError(t["validation.generic"]) from exc
    stored = str(value).strip()
    if key == "school.name" and not stored:
        raise ValidationError(t["auth.school_name_required"])
    return stored


def set_value(conn, ctx: UserContext, key: str, value) -> None:
    require(ctx, "settings.change")
    stored = _coerce(key, value)
    if key in HOUR_KEYS:
        raise ValidationError(t["validation.generic"])
    with atomic(conn):
        _store(conn, ctx, key, stored)


RECEIPT_LINE_MAX = 200  # a line under the header or at the foot of a receipt


def save_school(conn, ctx: UserContext, name: str, phone: str, address: str,
                opens_at: str, closes_at: str, registration_fee: int | None = None,
                debt_warning: int | None = None, group_price: int | None = None,
                receipt_header: str | None = None, receipt_footer: str | None = None) -> None:
    """Every part of the school at once, all or nothing: details, opening hours, the default
    registration fee, the debt warning threshold, the default price of a new group and the
    receipts' extra lines (each left unchanged when None; a threshold or price of 0 turns it
    off, an empty line prints nothing). Paramètres saves one part at a time (below)."""
    require(ctx, "settings.change")
    details = {**_identity(name, phone, address),
               **_defaults(registration_fee, group_price, debt_warning),
               **_receipt_lines(receipt_header, receipt_footer)}
    with atomic(conn):
        _set_hours(conn, ctx, opens_at, closes_at)
        for key, stored in details.items():
            _store(conn, ctx, key, stored)


def save_identity(conn, ctx: UserContext, name: str, phone: str, address: str) -> None:
    """The school's name (required), phone and address, printed on every document."""
    require(ctx, "settings.change")
    _save(conn, ctx, _identity(name, phone, address))


def save_defaults(conn, ctx: UserContext, registration_fee: int, group_price: int,
                  debt_warning: int) -> None:
    """What a registration and a new group start with, and the debt warning threshold
    (0: no default price, no warning)."""
    require(ctx, "settings.change")
    _save(conn, ctx, _defaults(registration_fee, group_price, debt_warning))


def save_receipt_lines(conn, ctx: UserContext, header: str, footer: str) -> None:
    """The receipts' extra lines, under the school's name and at the foot (empty: none)."""
    require(ctx, "settings.change")
    _save(conn, ctx, _receipt_lines(header, footer))


def _save(conn, ctx: UserContext, details: dict[str, str]) -> None:
    with atomic(conn):
        for key, stored in details.items():
            _store(conn, ctx, key, stored)


def _identity(name: str, phone: str, address: str) -> dict[str, str]:
    return {key: _coerce(key, value) for key, value in (
        ("school.name", name), ("school.phone", phone), ("school.address", address))}


def _defaults(registration_fee: int | None, group_price: int | None,
              debt_warning: int | None) -> dict[str, str]:
    details = {}
    if group_price is not None:
        if group_price < 0:
            raise ValidationError(t["group.price_invalid"])
        details["defaults.group_price"] = str(group_price)
    if registration_fee is not None:
        if registration_fee < 0:
            raise ValidationError(t["registration.fee_invalid"])
        details["defaults.registration_fee"] = str(registration_fee)
    if debt_warning is not None:
        if debt_warning < 0:
            raise ValidationError(t["school.debt_warning_invalid"])
        details["defaults.max_debt_warning"] = str(debt_warning)
    return details


def _receipt_lines(header: str | None, footer: str | None) -> dict[str, str]:
    details = {}
    for key, line in (("receipt.header", header), ("receipt.footer", footer)):
        if line is not None:
            stored = _coerce(key, line)
            if len(stored) > RECEIPT_LINE_MAX:
                raise ValidationError(t["school.receipt_line_too_long"].format(
                    max=RECEIPT_LINE_MAX))
            details[key] = stored
    return details


def _store(conn, ctx: UserContext, key: str, stored: str) -> None:
    """Write one setting and its audit entry, inside the caller's transaction."""
    old = get(conn, key)
    if old is not None and str(old) == stored:
        return
    conn.execute(
        """
        INSERT INTO settings(key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = strftime('%Y-%m-%dT%H:%M:%S','now','localtime')
        """,
        (key, stored),
    )
    audit.log(
        conn,
        ctx,
        "settings.set",
        "settings",
        None,
        old={"key": key, "value": old},
        new={"key": key, "value": stored},
    )


# ----- opening hours -----

def school_hours(conn) -> tuple[str, str]:
    """('HH:MM', 'HH:MM'): when the school opens and closes, every day."""
    return (get(conn, "school.opens_at", DEFAULT_OPENS_AT),
            get(conn, "school.closes_at", DEFAULT_CLOSES_AT))


def set_school_hours(conn, ctx: UserContext, opens_at: str, closes_at: str) -> None:
    """Both times in 'HH:MM'. Refused while a running or future slot falls outside them."""
    require(ctx, "settings.change")
    with atomic(conn):
        _set_hours(conn, ctx, opens_at, closes_at)


def _set_hours(conn, ctx: UserContext, opens_at: str, closes_at: str) -> None:
    opens_at, closes_at = dates.parse_time(opens_at), dates.parse_time(closes_at)
    if closes_at <= opens_at:
        raise ValidationError(t["hours.order"])
    outside = timetable_repo.outside_hours(conn, opens_at, closes_at,
                                           dates.iso(dates.today()))
    if outside:
        first = outside[0]
        raise BusinessRuleError(t["hours.slots_outside"].format(
            count=len(outside), group=first["group"], day=t[f"weekday.{first['weekday']}"],
            start=first["start_time"], end=first["end_time"]))
    _store(conn, ctx, "school.opens_at", opens_at)
    _store(conn, ctx, "school.closes_at", closes_at)
