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


def save_school(conn, ctx: UserContext, name: str, phone: str, address: str,
                opens_at: str, closes_at: str, registration_fee: int | None = None,
                debt_warning: int | None = None) -> None:
    """The École tab, all or nothing: details, opening hours, the default registration fee
    and the debt warning threshold (each left unchanged when None; a threshold of 0 turns
    the warning off)."""
    require(ctx, "settings.change")
    details = {key: _coerce(key, value) for key, value in (
        ("school.name", name), ("school.phone", phone), ("school.address", address))}
    if registration_fee is not None:
        if registration_fee < 0:
            raise ValidationError(t["registration.fee_invalid"])
        details["defaults.registration_fee"] = str(registration_fee)
    if debt_warning is not None:
        if debt_warning < 0:
            raise ValidationError(t["school.debt_warning_invalid"])
        details["defaults.max_debt_warning"] = str(debt_warning)
    with atomic(conn):
        _set_hours(conn, ctx, opens_at, closes_at)
        for key, stored in details.items():
            _store(conn, ctx, key, stored)


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
