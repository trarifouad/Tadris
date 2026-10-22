import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError, NotFound, ValidationError
from tadris.core.permissions import require
from tadris.core.text import clean
from tadris.db.errors import atomic, translate
from tadris.domain.models import Session
from tadris.i18n.fr import t
from tadris.repositories import groups as groups_repo
from tadris.repositories import holidays as holidays_repo
from tadris.repositories import sessions as repo
from tadris.services import audit, settings
from tadris.services import rooms as rooms_service
from tadris.services import teachers as teachers_service

# Sessions are generated from the timetable for the next HORIZON_DAYS days (today included):
# one per slot meeting that day, with the group's teacher on that date, in the slot's room.
# Holidays, closed groups, days outside a slot's validity, before the group starts or after
# its year are skipped. Running it again never duplicates (unique slot and date, cancelled
# sessions included). A session that would clash with another (a makeup in the same room)
# is skipped and reported, not forced. Pending sessions (see repositories.sessions) are
# discarded and generated again when the timetable, a teacher or the holidays change.
# A planned session can be cancelled (with a reason) and restored; a cancelled one gets one
# makeup session; any session can be given a substitute teacher. A session of the week can
# also be rescheduled in one step (« Reporter », from the timetable): cancelled with its
# reason and replaced by a makeup the same week (Saturday to Friday), from today on; the
# timetable itself never changes. Clashes are checked here
# first, with a message naming them; the triggers stay the last line of defense.

HORIZON_DAYS = 14


@dataclass
class Generation:
    created: int = 0
    # (date, group_id, French message) of each session left out because of a clash
    conflicts: list[tuple[str, int, str]] = field(default_factory=list)


def _today() -> str:
    return dates.iso(dates.today())


def _days_off(conn, first: date, last: date) -> set[str]:
    off = set()
    for row in holidays_repo.between(conn, dates.iso(first), dates.iso(last)):
        day = max(date.fromisoformat(row["start_date"]), first)
        end = min(date.fromisoformat(row["end_date"]), last)
        while day <= end:
            off.add(dates.iso(day))
            day += timedelta(days=1)
    return off


def generate_in(conn, days: int = HORIZON_DAYS) -> Generation:
    """Inside a transaction: create the missing sessions from today on."""
    result = Generation()
    first = dates.today()
    last = first + timedelta(days=days - 1)
    off = _days_off(conn, first, last)
    day = first
    while day <= last:
        iso = dates.iso(day)
        if iso not in off:
            for slot in repo.slots_on(conn, iso, day.isoweekday()):
                if repo.exists_for_slot(conn, slot["id"], iso):
                    continue
                teacher_id = repo.scheduled_teacher(conn, slot["group_id"], iso)
                if teacher_id is None:
                    continue
                try:
                    repo.insert_generated(conn, slot["group_id"], slot["id"], slot["room_id"],
                                          teacher_id, iso, slot["start_time"], slot["end_time"])
                except sqlite3.IntegrityError as exc:  # the statement alone is rolled back
                    result.conflicts.append((iso, slot["group_id"], translate(exc).message))
                    continue
                result.created += 1
        day += timedelta(days=1)
    return result


def generate(conn, ctx: UserContext, days: int = HORIZON_DAYS) -> Generation:
    """The « Régénérer » button."""
    require(ctx, "session.manage")
    with atomic(conn):
        result = generate_in(conn, days)
        if result.created or result.conflicts:
            audit.log(conn, ctx, "session.generate", "sessions", None,
                      new={"created": result.created, "conflicts": len(result.conflicts)})
        return result


def generate_at_start(conn) -> Generation:
    """At app start, before anyone logs in (audited without a user)."""
    with atomic(conn):
        result = generate_in(conn)
        if result.created or result.conflicts:
            audit.log_system(conn, "session.generate", "sessions",
                             new={"created": result.created, "conflicts": len(result.conflicts)})
        return result


# ----- keeping the forecast in step (inside the caller's transaction) -----

def discard_for_slot(conn, slot_id: int, from_date: str | None = None) -> int:
    """The slot changes or ends: its pending sessions go (from a date, or all)."""
    return repo.discard_pending(conn, _today(), slot_id=slot_id, from_date=from_date)


def discard_for_teacher_change(conn, group_id: int, from_date: str, old_teacher: int) -> int:
    """A new teacher from a date: the pending sessions with the old one go. A substitute
    chosen by hand for one session is kept."""
    return repo.discard_pending(conn, _today(), group_id=group_id, from_date=from_date,
                                teacher_id=old_teacher)


def discard_for_days(conn, first: date, last: date) -> int:
    """Holidays: the pending sessions of those days go."""
    days = []
    day = max(first, dates.today())
    while day <= last:
        days.append(dates.iso(day))
        day += timedelta(days=1)
    return repo.discard_pending(conn, _today(), days=days)


def cancel_for_closed_group(conn, ctx: UserContext, group_id: int) -> int:
    """The group closes: what is still planned from today (makeups, substitutes) is cancelled
    with the reason « Groupe clôturé ». Generated forecasts went with the slots."""
    cancelled = repo.cancel_future_of_group(conn, group_id, _today(),
                                            t["session.group_closed_reason"])
    for session_id in cancelled:
        audit.log(conn, ctx, "session.cancel", "sessions", session_id,
                  old={"status": "planned"},
                  new={"status": "cancelled", "reason": t["session.group_closed_reason"]})
    return len(cancelled)


def kept_count(conn, slot_id: int) -> int:
    """Sessions of the slot that are history (held, cancelled, past, makeup, attendance)."""
    return repo.kept_count(conn, slot_id, _today())


# ----- one session: read, cancel, restore, makeup, substitute -----

def _to_session(row) -> Session:
    return Session(
        id=row["id"], group_id=row["group_id"],
        group_title=f"{row['group_name']} · {row['subject']} {row['level']}",
        group_name=row["group_name"], slot_id=row["slot_id"], room_id=row["room_id"],
        room=row["room"], teacher_id=row["teacher_id"], teacher=row["teacher"],
        scheduled_teacher_id=row["scheduled_teacher_id"], date=row["date"],
        start_time=row["start_time"], end_time=row["end_time"], status=row["status"],
        source=row["source"], cancellation_reason=row["cancellation_reason"],
        makeup_of_session_id=row["makeup_of_session_id"], makeup_id=row["makeup_id"],
        makeup_date=row["makeup_date"], makeup_of_date=row["makeup_of_date"],
        attendance_count=row["attendance_count"], expected=row["expected"],
    )


def _require_row(conn, session_id: int):
    row = repo.get(conn, session_id)
    if row is None:
        raise NotFound(t["session.not_found"])
    return row


def get(conn, ctx: UserContext, session_id: int) -> Session:
    require(ctx, "session.view")
    return _to_session(_require_row(conn, session_id))


def listing(conn, ctx: UserContext, first: date, last: date, group_id: int | None = None,
            teacher_id: int | None = None, room_id: int | None = None) -> list[Session]:
    require(ctx, "session.view")
    return [_to_session(row) for row in repo.listing(conn, dates.iso(first), dates.iso(last),
                                                       group_id, teacher_id, room_id)]


def cancel(conn, ctx: UserContext, session_id: int, reason: str) -> None:
    """A planned session that will not take place. The reason is shown and audited."""
    require(ctx, "session.manage")
    reason = clean(reason)
    if not reason:
        raise ValidationError(t["session.reason_required"])
    with atomic(conn):
        row = _require_row(conn, session_id)
        if row["status"] == "cancelled":
            raise BusinessRuleError(t["session.already_cancelled"])
        if row["status"] == "held" or row["attendance_count"]:
            raise BusinessRuleError(t["session.held"])
        repo.cancel(conn, session_id, reason)
        audit.log(conn, ctx, "session.cancel", "sessions", session_id,
                  old={"status": row["status"]}, new={"status": "cancelled", "reason": reason})


def restore(conn, ctx: UserContext, session_id: int) -> None:
    """A session cancelled by mistake takes place after all (if nothing took its place)."""
    require(ctx, "session.manage")
    with atomic(conn):
        row = _require_row(conn, session_id)
        if row["status"] != "cancelled":
            raise BusinessRuleError(t["session.not_cancelled"])
        if row["makeup_id"] is not None:
            raise BusinessRuleError(t["session.has_makeup"])
        if row["group_status"] == "closed":
            raise BusinessRuleError(t["db.group_closed"])
        _check_free(conn, row["group_id"], row["room_id"], row["teacher_id"], row["date"],
                    row["start_time"], row["end_time"], session_id)
        repo.restore(conn, session_id)
        audit.log(conn, ctx, "session.restore", "sessions", session_id,
                  old={"status": "cancelled", "reason": row["cancellation_reason"]},
                  new={"status": "planned"})


def _busy(key: str, clash, **extra) -> BusinessRuleError:
    return BusinessRuleError(t[key].format(
        day=dates.display_date(clash["date"]), start=clash["start_time"],
        end=clash["end_time"], group=clash["group"], room=clash["room"],
        teacher=clash["teacher"], **extra))


def _check_free(conn, group_id: int, room_id: int, teacher_id: int, day: str, start: str,
                end: str, exclude_id: int | None) -> None:
    """Readable messages before the triggers refuse: room, teacher, group, students."""
    clash = repo.room_clash(conn, room_id, day, start, end, exclude_id)
    if clash is not None:
        raise _busy("slot.room_busy", clash)
    clash = repo.teacher_clash(conn, teacher_id, day, start, end, exclude_id)
    if clash is not None:
        raise _busy("slot.teacher_busy", clash)
    clash = repo.group_clash(conn, group_id, day, start, end, exclude_id)
    if clash is not None:
        raise _busy("slot.group_busy", clash)
    busy = repo.students_clash(conn, group_id, day, start, end)
    if busy:
        others = len({row["student_id"] for row in busy}) - 1
        raise _busy("slot.students_busy" if others else "slot.student_busy", busy[0],
                    student=busy[0]["student"], others=others)


def _check_makeup_time(conn, start_time: str, end_time: str) -> tuple[str, str]:
    start, end = dates.parse_time(start_time), dates.parse_time(end_time)
    if end <= start:
        raise ValidationError(t["slot.times_order"])
    opens_at, closes_at = settings.school_hours(conn)
    if start < opens_at or end > closes_at:
        raise ValidationError(t["slot.outside_hours"].format(opens=opens_at, closes=closes_at))
    return start, end


def _insert_makeup(conn, row, iso: str, start: str, end: str, room_id: int,
                   teacher_id: int | None) -> tuple[int, int]:
    """Inside the caller's transaction: checks the group, the date, the room, the teacher and
    every clash, then inserts the makeup of the cancelled session `row`. Returns its id and
    its teacher."""
    group = groups_repo.get(conn, row["group_id"], _today())
    if group["status"] == "closed":
        raise BusinessRuleError(t["db.group_closed"])
    if not group["start_date"] <= iso <= group["year_end"]:
        raise ValidationError(t["session.makeup_outside"].format(
            start=dates.display_date(group["start_date"]),
            end=dates.display_date(group["year_end"])))
    room = rooms_service.require_active(conn, room_id)
    enrolled = repo.enrolled_on(conn, row["group_id"], iso)
    if enrolled > room["capacity"]:
        raise BusinessRuleError(t["room.too_small"].format(
            room=room["name"], room_capacity=room["capacity"], enrolled=enrolled))
    teacher = row["teacher_id"] if teacher_id is None else teacher_id
    teachers_service.require_active(conn, teacher)
    _check_free(conn, row["group_id"], room_id, teacher, iso, start, end, None)
    makeup_id = repo.insert_makeup(conn, row["id"], row["group_id"], room_id, teacher, iso,
                                   start, end)
    return makeup_id, teacher


def schedule_makeup(conn, ctx: UserContext, session_id: int, day: date, start_time: str,
                    end_time: str, room_id: int, teacher_id: int | None = None) -> int:
    """A makeup for a cancelled session: another date and time, a room, the same group. The
    teacher defaults to the cancelled session's. One makeup per cancelled session."""
    require(ctx, "session.manage")
    start, end = _check_makeup_time(conn, start_time, end_time)
    with atomic(conn):
        row = _require_row(conn, session_id)
        if row["status"] != "cancelled":
            raise BusinessRuleError(t["session.makeup_needs_cancel"])
        if row["makeup_id"] is not None:
            raise BusinessRuleError(t["session.has_makeup"])
        iso = dates.iso(day)
        makeup_id, teacher = _insert_makeup(conn, row, iso, start, end, room_id, teacher_id)
        audit.log(conn, ctx, "session.makeup", "sessions", makeup_id, new={
            "makeup_of_session_id": session_id, "date": iso, "start_time": start,
            "end_time": end, "room_id": room_id, "teacher_id": teacher})
        return makeup_id


def reschedule(conn, ctx: UserContext, session_id: int, day: date, start_time: str,
               end_time: str, room_id: int, reason: str, teacher_id: int | None = None) -> int:
    """Move one planned session to another day, time or room of the same week (Saturday to
    Friday), from today on: it is cancelled with `reason` and a makeup takes its place, in
    one transaction. The timetable slot is not touched. Returns the makeup's id."""
    require(ctx, "session.manage")
    reason = clean(reason)
    if not reason:
        raise ValidationError(t["session.reason_required"])
    start, end = _check_makeup_time(conn, start_time, end_time)
    with atomic(conn):
        row = _require_row(conn, session_id)
        if row["status"] == "cancelled":
            raise BusinessRuleError(t["session.already_cancelled"])
        if row["status"] == "held" or row["attendance_count"]:
            raise BusinessRuleError(t["session.held"])
        today = dates.today()
        if row["date"] < dates.iso(today):
            raise BusinessRuleError(t["session.reschedule_past"])
        first = dates.week_start(date.fromisoformat(row["date"]))
        last = first + timedelta(days=6)
        if not max(first, today) <= day <= last:
            raise ValidationError(t["session.reschedule_week"].format(
                first=dates.display_date(dates.iso(max(first, today))),
                last=dates.display_date(dates.iso(last))))
        iso = dates.iso(day)
        if (iso, start, end, room_id) == (row["date"], row["start_time"], row["end_time"],
                                          row["room_id"]) and teacher_id in (None,
                                                                             row["teacher_id"]):
            raise ValidationError(t["session.reschedule_same"])
        repo.cancel(conn, session_id, reason)  # first: the old place no longer clashes
        makeup_id, teacher = _insert_makeup(conn, row, iso, start, end, room_id, teacher_id)
        audit.log(conn, ctx, "session.reschedule", "sessions", session_id,
                  old={"status": row["status"], "date": row["date"],
                       "start_time": row["start_time"], "end_time": row["end_time"],
                       "room_id": row["room_id"], "teacher_id": row["teacher_id"]},
                  new={"status": "cancelled", "reason": reason, "makeup_id": makeup_id,
                       "date": iso, "start_time": start, "end_time": end,
                       "room_id": room_id, "teacher_id": teacher})
        return makeup_id


def undo_reschedule(conn, ctx: UserContext, session_id: int) -> None:
    """The session takes place as planned after all: its makeup (not held yet) is cancelled
    and the session restored, in one transaction."""
    require(ctx, "session.manage")
    with atomic(conn):
        row = _require_row(conn, session_id)
        if row["status"] != "cancelled" or row["makeup_id"] is None:
            raise BusinessRuleError(t["session.not_rescheduled"])
        makeup = _require_row(conn, row["makeup_id"])
        if makeup["status"] == "held" or makeup["attendance_count"]:
            raise BusinessRuleError(t["session.makeup_held"])
        if row["date"] < _today():
            raise BusinessRuleError(t["session.reschedule_past"])
        if row["group_status"] == "closed":
            raise BusinessRuleError(t["db.group_closed"])
        repo.cancel(conn, makeup["id"], t["session.reschedule_undone"])
        _check_free(conn, row["group_id"], row["room_id"], row["teacher_id"], row["date"],
                    row["start_time"], row["end_time"], session_id)
        repo.restore(conn, session_id)
        audit.log(conn, ctx, "session.undo_reschedule", "sessions", session_id,
                  old={"status": "cancelled", "reason": row["cancellation_reason"],
                       "makeup_id": makeup["id"]},
                  new={"status": "planned"})


def set_teacher(conn, ctx: UserContext, session_id: int, teacher_id: int) -> None:
    """A substitute for this session only; the group's own teacher again removes it."""
    require(ctx, "session.manage")
    with atomic(conn):
        row = _require_row(conn, session_id)
        if row["status"] == "cancelled":
            raise BusinessRuleError(t["session.cancelled"])
        if teacher_id == row["teacher_id"]:
            return
        teachers_service.require_active(conn, teacher_id)
        clash = repo.teacher_clash(conn, teacher_id, row["date"], row["start_time"],
                                   row["end_time"], session_id)
        if clash is not None:
            raise _busy("slot.teacher_busy", clash)
        repo.set_teacher(conn, session_id, teacher_id)
        audit.log(conn, ctx, "session.set_teacher", "sessions", session_id,
                  old={"teacher_id": row["teacher_id"]},
                  new={"teacher_id": teacher_id,
                       "substitute": teacher_id != row["scheduled_teacher_id"]})
