"""The audit log in plain French, for the director's Journal: the action's name, the item it
changed (« Paiement n° 12 », « Élève : Benali Amine ») and what it recorded, with names
instead of ids, amounts in DA, dates in dd/mm/yyyy and statuses in French.

Only reads. Unknown actions, keys or values (a later phase) show as they are recorded.
"""

import json
from dataclasses import dataclass

from tadris.core import dates
from tadris.core.money import format_dzd
from tadris.core.percent import format_percent
from tadris.i18n.fr import t

MONEY = {"amount", "amount_due", "amount_final", "base_amount", "default_fee", "fee_amount",
         "price", "suggestion", "to_credit"}
PERCENT = {"percentage_bp"}
DATES = {"birth_date", "date", "end_date", "enrolled_on", "hire_date", "left_on", "on",
         "period_end", "period_start", "rate_from", "start_date", "valid_from"}
BOOLS = {"can_receive_sms", "is_main", "voided", "substitute"}
# Ids that only link rows together: the name they point to is shown when there is one.
NAMES = {"student_id": "students", "teacher_id": "teachers", "group_id": "class_groups",
         "room_id": "rooms", "level_id": "levels", "subject_id": "subjects",
         "school_year_id": "school_years"}
HIDDEN = {"id", "charge_id", "receipt_id", "registration_id", "enrollment_id", "contact_id",
          "payer_contact_id", "renewal_of_id", "switched_from_id", "makeup_of_session_id",
          "allocation_id", "payment_id", "replaced", "conflicts",
          "chosen"}  # whether the desk picked the lines: says nothing to the director
LISTS = {"allocations", "lines", "from"}  # shown as a count
ZERO_SAYS_NOTHING = {"to_credit"}  # « Mis en avoir : 0 DA » on every payment


@dataclass(frozen=True)
class Names:
    """Names of the rows an entry points to, read once per Journal."""

    by_table: dict[str, dict[int, str]]

    def get(self, table: str, row_id) -> str | None:
        if not isinstance(row_id, int):
            return None
        return self.by_table.get(table, {}).get(row_id)


def load_names(conn) -> Names:
    queries = {
        "students": "SELECT id, last_name || ' ' || first_name FROM students",
        "teachers": "SELECT id, full_name FROM teachers",
        "class_groups": "SELECT g.id, g.name FROM class_groups g",
        "rooms": "SELECT id, name FROM rooms",
        "levels": "SELECT id, name FROM levels",
        "subjects": "SELECT id, name FROM subjects",
        "school_years": "SELECT id, label FROM school_years",
        "users": "SELECT id, username FROM users",
    }
    return Names({table: dict(conn.execute(sql).fetchall()) for table, sql in queries.items()})


def action_label(action: str) -> str:
    return t.get(f"audit.action.{action}", action)


def entity_label(entity: str, entity_id: int | None, names: Names) -> str:
    kind = t.get(f"audit.entity.{entity}", entity)
    if entity_id is None:
        return kind
    name = names.get(entity, entity_id)
    if name:
        return t["audit.entity_named"].format(kind=kind, name=name)
    return t["audit.entity_number"].format(kind=kind, id=entity_id)


def _key_label(key: str) -> str:
    return t.get(f"audit.key.{key}", key.replace("_", " "))


def _value(key: str, value, names: Names) -> str | None:
    """One recorded value in French; None when it says nothing to the reader."""
    if value is None or key in HIDDEN:
        return None
    if key in ZERO_SAYS_NOTHING and value == 0:
        return None
    if key in NAMES:
        return names.get(NAMES[key], value) or t["audit.number"].format(id=value)
    if key in LISTS and isinstance(value, list):
        return t["audit.lines"].format(count=len(value))
    if key == "changes" and isinstance(value, list):
        return _attendance(value)
    if isinstance(value, bool) or key in BOOLS:
        return t["audit.yes"] if value else t["audit.no"]
    if key in MONEY and isinstance(value, int):
        return format_dzd(value)
    if key in PERCENT and isinstance(value, int):
        return format_percent(value)
    if key in DATES and isinstance(value, str) and len(value) >= 10:
        try:
            return dates.display_date(value)
        except ValueError:
            return value
    if key == "weekday" and isinstance(value, int):
        return t.get(f"weekday.{value}", str(value)).capitalize()
    if key == "method":
        return t.get(f"payment_method.{value}", value)
    if key == "role":
        return t.get(f"role.{value}", value)
    if key == "status":
        return t.get(f"audit.status.{value}", value)
    if key == "report":
        return t.get(f"audit.report.{value}", value)
    if key == "format":
        return t.get(f"audit.format.{value}", value)
    if key == "type":
        return t.get(f"audit.type.{value}", value)
    if key == "key":
        return t.get(f"audit.setting.{value}", value)
    if key == "result":
        return t.get(f"audit.result.{value}", value)
    if isinstance(value, list):
        return t["audit.lines"].format(count=len(value))
    if isinstance(value, dict):
        return ", ".join(f"{_key_label(k)} : {v}" for k, v in value.items())
    return str(value)


def _attendance(changes: list) -> str:
    """« 2 Présent, 1 Absent » from the marks an attendance save changed."""
    counts: dict[str, int] = {}
    for change in changes:
        status = change.get("new") if isinstance(change, dict) else None
        if status:
            counts[status] = counts.get(status, 0) + 1
    return ", ".join(f"{count} {t.get(f'attendance_status.{status}', status)}"
                     for status, count in counts.items()) or "—"


def _load(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except ValueError:
        return {"value": raw}
    return value if isinstance(value, dict) else {"value": value}


@dataclass(frozen=True)
class Field:
    """One recorded value: before is set only when it changed (a status, an amount)."""

    label: str
    value: str
    before: str | None = None


def fields(old_raw: str | None, new_raw: str | None, names: Names,
           skip: str | None = None) -> list[Field]:
    """What an entry recorded, in French. skip: a value already shown as the entry's item
    (« Utilisateur : kadam »), not repeated."""
    old, new = _load(old_raw), _load(new_raw)
    out = []
    for key in list(new) + [k for k in old if k not in new]:
        after = _value(key, new.get(key), names) if key in new else None
        before = _value(key, old.get(key), names) if key in old else None
        label = _key_label(key)
        if key in new and key in old and before != after:
            out.append(Field(label, after or "—", before or "—"))
            continue
        value = after if key in new else before
        if value is not None and value != skip:
            out.append(Field(label, value))
    return out


def lines(old_raw: str | None, new_raw: str | None, names: Names,
          skip: str | None = None) -> list[str]:
    """« Clé : valeur », one per recorded value; a changed one as « avant → après »."""
    return [f"{f.label} : {f.before} → {f.value}" if f.before is not None
            else f"{f.label} : {f.value}" for f in fields(old_raw, new_raw, names, skip)]


def summary(old_raw: str | None, new_raw: str | None, names: Names,
            width: int | None = 160) -> str:
    """The values on one line; width None keeps it whole."""
    text = " · ".join(lines(old_raw, new_raw, names))
    return text if width is None or len(text) <= width else text[:width - 1] + "…"
