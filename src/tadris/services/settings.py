from tadris.core.context import UserContext
from tadris.core.errors import ValidationError
from tadris.core.permissions import require
from tadris.db.connection import transaction
from tadris.i18n.fr import t
from tadris.services import audit

KEYS: dict[str, type] = {
    "school.name": str,
    "school.address": str,
    "school.phone": str,
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


def set_value(conn, ctx: UserContext, key: str, value) -> None:
    require(ctx, "settings.change")
    if key not in KEYS:
        raise ValidationError(t["settings.unknown_key"])
    expected = KEYS[key]
    if expected is int:
        try:
            stored = str(int(value))
        except (TypeError, ValueError) as exc:
            raise ValidationError(t["validation.generic"]) from exc
    else:
        stored = str(value).strip()
        if key == "school.name" and not stored:
            raise ValidationError(t["auth.school_name_required"])
    old = get(conn, key)
    with transaction(conn):
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
