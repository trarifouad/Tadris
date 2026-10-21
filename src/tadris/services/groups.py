from datetime import date

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError, NotFound, ValidationError
from tadris.core.permissions import require
from tadris.core.text import clean, fold
from tadris.db.errors import atomic
from tadris.domain.models import Group, GroupInput, TeacherPeriod
from tadris.i18n.fr import t
from tadris.repositories import groups as repo
from tadris.repositories import timetable as timetable_repo
from tadris.repositories.students import like_pattern
from tadris.services import (
    audit,
    catalog,
    school_years,
    sessions,
    settings,
    teachers,
    timetable,
)

# Groups belong to the open year or an upcoming one. The price is copied onto each
# subscription when it is created, so a price change only affects later subscriptions.
# The teacher is kept as history in group_teachers, half-open [valid_from, valid_to): a change
# closes the current period and opens a new one; a change on the current period's own start
# date corrects it, unless that teacher was already paid for the group. A change can be
# planned for a later date; until then the group shows its current teacher.

STATUSES = ("planned", "active", "closed")


def state_of(row, today: date | None = None) -> str:
    if row["status"] == "closed":
        return "closed"
    return "upcoming" if row["start_date"] > dates.iso(today or dates.today()) else "active"


def _to_group(row) -> Group:
    return Group(
        id=row["id"], school_year_id=row["school_year_id"], year_label=row["year_label"],
        level_id=row["level_id"], level=row["level"], subject_id=row["subject_id"],
        subject=row["subject"], name=row["name"], price=row["price"],
        capacity=row["capacity"], start_date=row["start_date"], status=row["status"],
        state=state_of(row), teacher_id=row["teacher_id"], teacher=row["teacher"],
        enrolled=row["enrolled"], room_limit=row["room_limit"], limiting_room=row["limiting_room"],
    )


def _today() -> str:
    return dates.iso(dates.today())


def default_price(conn) -> int:
    """The monthly price a new group starts with (Paramètres → École); 0: none."""
    return settings.get(conn, "defaults.group_price", 0)


def _require_row(conn, group_id: int):
    row = repo.get(conn, group_id, _today())
    if row is None:
        raise NotFound(t["group.not_found"])
    return row


def get(conn, ctx: UserContext, group_id: int) -> Group:
    require(ctx, "group.view")
    return _to_group(_require_row(conn, group_id))


def search(conn, ctx: UserContext, year_id: int | None = None, level_id: int | None = None,
           subject_id: int | None = None, teacher_id: int | None = None,
           status: str | None = None, query: str = "") -> list[Group]:
    require(ctx, "group.view")
    if status is not None and status not in STATUSES:
        raise ValidationError(t["validation.generic"])
    term = clean(query)
    rows = repo.search(conn, _today(), year_id, level_id, subject_id, teacher_id, status,
                       like_pattern(fold(term)) if term else None)
    return [_to_group(row) for row in rows]


def _clean(conn, data: GroupInput, year, exclude_id: int | None) -> str:
    name = clean(data.name)
    if not name:
        raise ValidationError(t["name.required"])
    if data.price < 0:
        raise ValidationError(t["group.price_invalid"])
    if data.capacity < 1:
        raise ValidationError(t["group.capacity_invalid"])
    start = dates.iso(data.start_date)
    if not year["start_date"] <= start <= year["end_date"]:
        raise ValidationError(t["group.start_outside_year"].format(label=year["label"]))
    if repo.name_taken(conn, year["id"], name, exclude_id):
        raise ValidationError(t["group.name_taken"])
    return name


def _snapshot(row) -> dict:
    return {key: row[key] for key in ("level_id", "subject_id", "name", "price", "capacity",
                                      "start_date")}


def create(conn, ctx: UserContext, data: GroupInput, teacher_id: int) -> int:
    require(ctx, "group.manage")
    with atomic(conn):
        year = school_years.require_usable(conn, data.school_year_id)
        name = _clean(conn, data, year, None)
        catalog.require_active(conn, "level", data.level_id)
        catalog.require_active(conn, "subject", data.subject_id)
        teachers.require_active(conn, teacher_id)
        start = dates.iso(data.start_date)
        group_id = repo.insert(conn, year["id"], data.level_id, data.subject_id, name,
                               data.price, data.capacity, start)
        repo.insert_teacher_row(conn, group_id, teacher_id, start)
        audit.log(conn, ctx, "group.create", "class_groups", group_id, new={
            "school_year_id": year["id"], **_snapshot(repo.get(conn, group_id, _today())),
            "teacher_id": teacher_id,
        })
        return group_id


def update(conn, ctx: UserContext, group_id: int, data: GroupInput) -> None:
    """Level, subject and start date are fixed once the group has students. The school year
    never changes. Capacity stays above the enrolled count (trigger); it may exceed the
    rooms used, which then limit the seats."""
    require(ctx, "group.manage")
    with atomic(conn):
        row = _require_row(conn, group_id)
        if row["status"] == "closed":
            raise BusinessRuleError(t["group.closed"])
        year = school_years.require_usable(conn, row["school_year_id"])
        name = _clean(conn, data, year, group_id)
        start = dates.iso(data.start_date)
        structural = (data.level_id, data.subject_id, start) != (
            row["level_id"], row["subject_id"], row["start_date"])
        if structural and repo.enrollment_count(conn, group_id):
            raise BusinessRuleError(t["group.has_enrollments"])
        if data.level_id != row["level_id"]:
            catalog.require_active(conn, "level", data.level_id)
        if data.subject_id != row["subject_id"]:
            catalog.require_active(conn, "subject", data.subject_id)
        old = _snapshot(row)
        repo.update(conn, group_id, data.level_id, data.subject_id, name, data.price,
                    data.capacity, start)
        if start != row["start_date"]:
            _move_start(conn, ctx, group_id, start)
        new = _snapshot(repo.get(conn, group_id, _today()))
        changed = [key for key in new if old[key] != new[key]]
        if changed:
            audit.log(conn, ctx, "group.update", "class_groups", group_id,
                      old={k: old[k] for k in changed}, new={k: new[k] for k in changed})


def _move_start(conn, ctx: UserContext, group_id: int, start: str) -> None:
    """The first teacher starts with the group, and so do its slots."""
    first = repo.first_teacher_row(conn, group_id)
    if first["valid_to"] is not None and start >= first["valid_to"]:
        raise BusinessRuleError(t["group.start_after_teacher_change"].format(
            date=dates.display_date(first["valid_to"])))
    repo.move_teacher_row_start(conn, first["id"], start)
    timetable.follow_group_start(conn, ctx, group_id, start)


def change_teacher(conn, ctx: UserContext, group_id: int, teacher_id: int,
                   from_date: date) -> None:
    require(ctx, "group.manage")
    start = dates.iso(from_date)
    with atomic(conn):
        row = _require_row(conn, group_id)
        if row["status"] == "closed":
            raise BusinessRuleError(t["group.closed"])
        if not row["start_date"] <= start <= row["year_end"]:
            raise ValidationError(t["group.teacher_date_outside"].format(
                start=dates.display_date(row["start_date"]),
                end=dates.display_date(row["year_end"])))
        teachers.require_active(conn, teacher_id)
        current = repo.open_teacher_row(conn, group_id)
        if current is not None and current["teacher_id"] == teacher_id:
            raise BusinessRuleError(t["group.same_teacher"])
        # The new teacher must be free during the group's slots.
        for slot in timetable_repo.for_group(conn, group_id, _today()):
            if slot["valid_to"] is not None and slot["valid_to"] <= start:
                continue  # over before the new teacher starts
            timetable.check_teacher_free(conn, teacher_id, group_id, slot["weekday"],
                                         slot["start_time"], slot["end_time"],
                                         max(slot["valid_from"], start), slot["valid_to"],
                                         slot["id"])
        if current is not None:  # the planned sessions with the old teacher are redone
            sessions.discard_for_teacher_change(conn, group_id, start, current["teacher_id"])
        if current is None:
            repo.insert_teacher_row(conn, group_id, teacher_id, start)
        elif start < current["valid_from"]:
            raise ValidationError(t["group.teacher_before_current"].format(
                date=dates.display_date(current["valid_from"])))
        elif start == current["valid_from"]:
            if repo.teacher_paid_for_group(conn, group_id, current["teacher_id"]):
                raise BusinessRuleError(t["group.teacher_locked"])
            repo.correct_teacher_row(conn, current["id"], teacher_id)
        else:
            repo.close_teacher_row(conn, current["id"], start)
            repo.insert_teacher_row(conn, group_id, teacher_id, start)
        audit.log(conn, ctx, "group.change_teacher", "class_groups", group_id,
                  old={"teacher_id": None if current is None else current["teacher_id"]},
                  new={"teacher_id": teacher_id, "valid_from": start})
        sessions.generate_in(conn)


def teacher_history(conn, ctx: UserContext, group_id: int) -> list[TeacherPeriod]:
    require(ctx, "group.view")
    _require_row(conn, group_id)
    return [
        TeacherPeriod(id=r["id"], teacher_id=r["teacher_id"], teacher=r["teacher"],
                      valid_from=r["valid_from"], valid_to=r["valid_to"])
        for r in repo.teacher_history(conn, group_id)
    ]


def release(conn, ctx: UserContext, group_id: int) -> tuple[int, int]:
    """Inside a transaction: a group being closed frees its rooms, its students leave it and
    what is still planned from today is cancelled. Returns (slots ended, students who
    left)."""
    from tadris.services import enrollments  # enrollments depends on this module

    left = enrollments.end_for_closed_group(conn, ctx, group_id)
    ended = timetable.end_group_slots(conn, ctx, group_id)
    sessions.cancel_for_closed_group(conn, ctx, group_id)
    return ended, left


def close(conn, ctx: UserContext, group_id: int) -> None:
    """Closed groups take no new students; their students leave and their timetable slots
    end today. Reopening brings neither back."""
    require(ctx, "group.manage")
    with atomic(conn):
        row = _require_row(conn, group_id)
        if row["status"] == "closed":
            raise BusinessRuleError(t["group.already_closed"])
        repo.set_status(conn, group_id, "closed")
        ended, left = release(conn, ctx, group_id)
        audit.log(conn, ctx, "group.close", "class_groups", group_id,
                  old={"status": row["status"]},
                  new={"status": "closed", "slots_ended": ended, "students_left": left})


def reopen(conn, ctx: UserContext, group_id: int) -> None:
    """Only in the open or an upcoming year. Slots are not restored."""
    require(ctx, "group.manage")
    with atomic(conn):
        row = _require_row(conn, group_id)
        if row["status"] != "closed":
            raise BusinessRuleError(t["group.not_closed"])
        school_years.require_usable(conn, row["school_year_id"])
        repo.set_status(conn, group_id, "active")
        audit.log(conn, ctx, "group.reopen", "class_groups", group_id,
                  old={"status": "closed"}, new={"status": "active"})
