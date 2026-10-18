from dataclasses import replace
from datetime import date, timedelta

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError, NotFound, ValidationError
from tadris.core.permissions import require
from tadris.db.errors import atomic
from tadris.domain.models import Slot, SlotInput
from tadris.i18n.fr import t
from tadris.repositories import groups as groups_repo
from tadris.repositories import timetable as repo
from tadris.services import audit, settings
from tadris.services import rooms as rooms_service

# Slots repeat every week in half-open periods [valid_from, valid_to). Conflicts are checked
# here first so the message can name the clash; the triggers stay the last line of defense
# for rooms and groups. Teacher clashes (one teacher, two groups, same time) are a service
# rule that follows the teacher history: a teacher is busy in a group only during their
# period there.

WEEKDAYS = range(1, 8)


def _to_slot(row) -> Slot:
    return Slot(**dict(row))


def _today() -> str:
    return dates.iso(dates.today())


def _require_row(conn, slot_id: int):
    row = repo.get(conn, slot_id, _today())
    if row is None:
        raise NotFound(t["slot.not_found"])
    return row


def week(conn, ctx: UserContext, on: date | None = None, room_id: int | None = None,
         group_id: int | None = None, teacher_id: int | None = None) -> list[Slot]:
    """The weekly slots valid on a date (default today), for one room, group or teacher."""
    require(ctx, "timetable.view")
    on_iso = dates.iso(on or dates.today())
    return [_to_slot(r) for r in repo.valid_on(conn, on_iso, room_id, group_id, teacher_id)]


def group_slots(conn, ctx: UserContext, group_id: int) -> list[Slot]:
    """A group's running and future slots."""
    require(ctx, "timetable.view")
    return [_to_slot(r) for r in repo.for_group(conn, group_id, _today())]


def _busy(key: str, clash, **extra) -> BusinessRuleError:
    return BusinessRuleError(t[key].format(
        day=t[f"weekday.{clash['weekday']}"], start=clash["start_time"], end=clash["end_time"],
        group=clash["group"], room=clash["room"], teacher=clash["teacher"], **extra,
    ))


def check_clashes(conn, group, room, weekday: int, start: str, end: str, valid_from: str,
                  valid_to: str | None, exclude_id: int | None) -> None:
    """Raise a precise French error for a room too small for the enrolled students, or a
    room, group or teacher clash. The room must fit the students enrolled now; while the
    group meets there, the room also caps its enrollments (trigger). Every teacher the group
    has during [valid_from, valid_to) must be free for their own period."""
    if group["enrolled"] > room["capacity"]:
        raise BusinessRuleError(t["room.too_small"].format(
            room=room["name"], room_capacity=room["capacity"], enrolled=group["enrolled"]))
    window = (weekday, start, end, valid_from, valid_to, exclude_id)
    clash = repo.room_clash(conn, room["id"], *window, _today())
    if clash is not None:
        raise _busy("slot.room_busy", clash)
    clash = repo.group_clash(conn, group["id"], *window, _today())
    if clash is not None:
        raise _busy("slot.group_busy", clash)
    for period in groups_repo.teacher_rows_between(conn, group["id"], valid_from, valid_to):
        check_teacher_free(conn, period["teacher_id"], group["id"], weekday, start, end,
                           max(valid_from, period["valid_from"]),
                           _earliest(valid_to, period["valid_to"]), exclude_id)


def _earliest(a: str | None, b: str | None) -> str | None:
    """The earlier of two period ends, None meaning open-ended."""
    if a is None or b is None:
        return a or b
    return min(a, b)


def check_teacher_free(conn, teacher_id: int, group_id: int, weekday: int, start: str,
                       end: str, valid_from: str, valid_to: str | None,
                       exclude_id: int | None) -> None:
    clash = repo.teacher_clash(conn, teacher_id, group_id, weekday, start, end, valid_from,
                               valid_to, exclude_id)
    if clash is not None:
        raise _busy("slot.teacher_busy", clash)


def _validate(conn, data: SlotInput) -> SlotInput:
    """The input with its times in 'HH:MM' ('9h' -> '09:00'), checked."""
    if data.weekday not in WEEKDAYS:
        raise ValidationError(t["slot.weekday_invalid"])
    data = replace(data, start_time=dates.parse_time(data.start_time),
                   end_time=dates.parse_time(data.end_time))
    if data.end_time <= data.start_time:
        raise ValidationError(t["slot.times_order"])
    opens_at, closes_at = settings.school_hours(conn)
    if data.start_time < opens_at or data.end_time > closes_at:
        raise ValidationError(t["slot.outside_hours"].format(opens=opens_at, closes=closes_at))
    return data


def _open_group(conn, group_id: int):
    group = groups_repo.get(conn, group_id, _today())
    if group is None:
        raise NotFound(t["group.not_found"])
    if group["status"] == "closed":
        raise BusinessRuleError(t["group.closed"])
    return group


def add_slot(conn, ctx: UserContext, data: SlotInput) -> int:
    """valid_from defaults to the later of today and the group's start date."""
    require(ctx, "timetable.manage")
    data = _validate(conn, data)
    with atomic(conn):
        group = _open_group(conn, data.group_id)
        room = rooms_service.require_active(conn, data.room_id)
        start_from = dates.iso(data.valid_from) if data.valid_from else max(
            _today(), group["start_date"])
        check_clashes(conn, group, room, data.weekday, data.start_time, data.end_time,
                      start_from, None, None)
        slot_id = repo.insert(conn, group["id"], room["id"], data.weekday, data.start_time,
                              data.end_time, start_from)
        audit.log(conn, ctx, "slot.create", "timetable_slots", slot_id, new={
            "group_id": group["id"], "room_id": room["id"], "weekday": data.weekday,
            "start_time": data.start_time, "end_time": data.end_time, "valid_from": start_from,
        })
        return slot_id


def _snapshot(row) -> dict:
    return {key: row[key] for key in ("room_id", "weekday", "start_time", "end_time",
                                      "valid_from", "valid_to")}


def update_slot(conn, ctx: UserContext, slot_id: int, data: SlotInput) -> int:
    """Change room, day or hours. A slot with sessions keeps its history: it ends today and
    a new slot starts today. Returns the id of the slot now in force."""
    require(ctx, "timetable.manage")
    data = _validate(conn, data)
    with atomic(conn):
        row = _require_row(conn, slot_id)
        group = _open_group(conn, row["group_id"])
        room = rooms_service.require_active(conn, data.room_id)
        today = _today()
        if row["valid_to"] is not None and row["valid_to"] <= today:
            raise BusinessRuleError(t["slot.ended"])
        new = (data.room_id, data.weekday, data.start_time, data.end_time)
        if new == (row["room_id"], row["weekday"], row["start_time"], row["end_time"]):
            return slot_id
        if repo.session_count(conn, slot_id) == 0:
            check_clashes(conn, group, room, data.weekday, data.start_time, data.end_time,
                          row["valid_from"], row["valid_to"], slot_id)
            repo.update(conn, slot_id, *new)
            audit.log(conn, ctx, "slot.update", "timetable_slots", slot_id,
                      old=_snapshot(row), new=_snapshot(repo.get(conn, slot_id, today)))
            return slot_id
        _end(conn, ctx, row, today)
        start_from = repo.get(conn, slot_id, today)["valid_to"]  # the new slot takes over from here
        check_clashes(conn, group, room, data.weekday, data.start_time, data.end_time,
                      start_from, row["valid_to"], slot_id)
        new_id = repo.insert(conn, group["id"], room["id"], *new[1:], start_from)
        audit.log(conn, ctx, "slot.replace", "timetable_slots", new_id,
                  old={"slot_id": slot_id, **_snapshot(row)},
                  new=_snapshot(repo.get(conn, new_id, today)))
        return new_id


def remove_slot(conn, ctx: UserContext, slot_id: int) -> None:
    require(ctx, "timetable.manage")
    with atomic(conn):
        row = _require_row(conn, slot_id)
        today = _today()
        if row["valid_to"] is not None and row["valid_to"] <= today:
            raise BusinessRuleError(t["slot.ended"])
        _end(conn, ctx, row, today)


def end_group_slots(conn, ctx: UserContext, group_id: int) -> int:
    """Inside a transaction: end every running or future slot of a group (group closed)."""
    today = _today()
    rows = repo.for_group(conn, group_id, today)
    for row in rows:
        _end(conn, ctx, row, today)
    return len(rows)


def follow_group_start(conn, ctx: UserContext, group_id: int, start_date: str) -> None:
    """Inside a transaction: the group's start date moved later, so its slots start then
    too. A slot over before that date is removed. Refused once a slot has sessions."""
    for row in repo.starting_before(conn, group_id, start_date):
        if repo.session_count(conn, row["id"]):
            raise BusinessRuleError(t["group.slots_have_sessions"])
        if row["valid_to"] is not None and row["valid_to"] <= start_date:
            repo.delete(conn, row["id"])
            audit.log(conn, ctx, "slot.delete", "timetable_slots", row["id"],
                      old={"valid_from": row["valid_from"], "valid_to": row["valid_to"]})
            continue
        repo.set_valid_from(conn, row["id"], start_date)
        audit.log(conn, ctx, "slot.move_start", "timetable_slots", row["id"],
                  old={"valid_from": row["valid_from"]}, new={"valid_from": start_date})


def _end(conn, ctx: UserContext, row, on: str) -> None:
    """A slot that never produced a session and has not started is removed (a correction);
    otherwise it ends on `on` (at the earliest the day after it started)."""
    if repo.session_count(conn, row["id"]) == 0 and row["valid_from"] >= on:
        repo.delete(conn, row["id"])
        audit.log(conn, ctx, "slot.delete", "timetable_slots", row["id"], old=_snapshot(row))
        return
    earliest = dates.iso(date.fromisoformat(row["valid_from"]) + timedelta(days=1))
    valid_to = max(on, earliest)
    repo.end(conn, row["id"], valid_to)
    audit.log(conn, ctx, "slot.end", "timetable_slots", row["id"],
              old={"valid_to": row["valid_to"]}, new={"valid_to": valid_to})
