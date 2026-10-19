from datetime import date

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError, NotFound, ValidationError
from tadris.core.permissions import require
from tadris.core.text import clean
from tadris.db.errors import atomic
from tadris.domain.models import Enrollment, GroupOption
from tadris.i18n.fr import t
from tadris.repositories import enrollments as repo
from tadris.repositories import groups as groups_repo
from tadris.repositories import registrations as registrations_repo
from tadris.repositories import school_years as years_repo
from tadris.repositories import students as students_repo
from tadris.repositories import subscriptions as subscriptions_repo
from tadris.repositories import timetable as timetable_repo
from tadris.services import audit, groups, subscriptions

# An enrollment places a registered student in a group of the open year. A student may be in
# several groups under one registration, never twice at once in the same group. Joining a
# running group is normal; the entry date lies between the group's start and the end of the
# year. One free trial per student, ever. A student follows the groups of one level, that of
# their registration, and cannot attend two groups at the same time: both refused for
# everyone. A second group of the same subject needs the director with an audited reason.
# The first month (subscription) is created here, in the same transaction: from the entry
# date when enrolled as active, from the confirmation when a trial is confirmed, and after a
# switch from the end of the month running in the old group.

LIVE = ("trial", "active")


def _today() -> str:
    return dates.iso(dates.today())


def _to_enrollment(row) -> Enrollment:
    return Enrollment(
        id=row["id"], student_id=row["student_id"], student_number=row["student_number"],
        student_name=f"{row['last_name']} {row['first_name']}", group_id=row["group_id"],
        group_name=row["group_name"], subject=row["subject"], group_level=row["group_level"],
        registration_id=row["registration_id"], registration_level=row["registration_level"],
        status=row["status"], started_as_trial=bool(row["started_as_trial"]),
        enrolled_on=row["enrolled_on"], left_on=row["left_on"],
        switched_from_id=row["switched_from_id"],
    )


def _group_title(row) -> str:
    return f"{row['name']} · {row['subject']} {row['level']}"


def get(conn, ctx: UserContext, enrollment_id: int) -> Enrollment:
    require(ctx, "student.view")
    row = repo.get(conn, enrollment_id)
    if row is None:
        raise NotFound(t["enrollment.not_found"])
    return _to_enrollment(row)


def for_student(conn, ctx: UserContext, student_id: int) -> list[Enrollment]:
    """Live enrollments first, then the history."""
    require(ctx, "student.view")
    return [_to_enrollment(row) for row in repo.for_student(conn, student_id)]


def for_group(conn, ctx: UserContext, group_id: int) -> list[Enrollment]:
    """Live enrollments first, by name, then the students who left."""
    require(ctx, "group.view")
    return [_to_enrollment(row) for row in repo.for_group(conn, group_id)]


def can_take_trial(conn, student_id: int) -> bool:
    return not repo.had_trial(conn, student_id)


def default_date(group_start: str, today: date | None = None) -> date:
    """Today, or the group's first day if it has not started yet."""
    return max(today or dates.today(), date.fromisoformat(group_start))


def options(conn, ctx: UserContext, student_id: int,
            leaving_group_id: int | None = None) -> list[GroupOption]:
    """The open groups of the open year at the level of the student's registration.
    leaving_group_id: the group a switch leaves, which no longer counts as one of theirs."""
    require(ctx, "enrollment.create")
    year = years_repo.open_year(conn)
    if year is None:
        return []
    registration = registrations_repo.for_student_year(conn, student_id, year["id"])
    if registration is None or registration["status"] != "active":
        return []
    year_groups = [g for g in groups.search(conn, ctx, year_id=year["id"],
                                            level_id=registration["level_id"])
                   if g.status != "closed"]
    live = {row["group_id"] for row in repo.for_student(conn, student_id)
            if row["status"] in LIVE} - {leaving_group_id}
    taken = {(g.subject_id, g.level_id) for g in year_groups if g.id in live}
    return [
        GroupOption(group=g, already_in=g.id in live,
                    same_subject=g.id not in live and (g.subject_id, g.level_id) in taken)
        for g in year_groups
    ]


def enroll(conn, ctx: UserContext, student_id: int, group_id: int, trial: bool = False,
           enrolled_on: date | None = None, override_reason: str | None = None) -> int:
    """Place the student in the group. override_reason lets the director add a second group
    of a subject the student already has; it is ignored otherwise."""
    require(ctx, "enrollment.create")
    with atomic(conn):
        if trial and repo.had_trial(conn, student_id):
            _require_student(conn, student_id)
            raise BusinessRuleError(t["enrollment.trial_used"])
        enrollment_id, entry = _place(conn, ctx, student_id, group_id, enrolled_on,
                                      "trial" if trial else "active", trial, override_reason)
        audit.log(conn, ctx, "enrollment.create", "enrollments", enrollment_id, new=entry)
        if not trial:
            subscriptions.create_in(conn, ctx, enrollment_id, entry["enrolled_on"])
        return enrollment_id


def _require_student(conn, student_id: int):
    student = students_repo.get(conn, student_id)
    if student is None:
        raise NotFound(t["student.not_found"])
    if student["status"] != "active":
        raise BusinessRuleError(t["registration.student_inactive"])
    return student


def _place(conn, ctx: UserContext, student_id: int, group_id: int, enrolled_on: date | None,
           status: str, started_as_trial: bool, override_reason: str | None,
           switched_from_id: int | None = None) -> tuple[int, dict]:
    """Inside a transaction: check and insert one enrollment. Returns its id and the audit
    entry."""
    reason = clean(override_reason or "")
    _require_student(conn, student_id)
    group = groups_repo.get(conn, group_id, _today())
    if group is None:
        raise NotFound(t["group.not_found"])
    title = _group_title(group)
    year = years_repo.open_year(conn)
    if year is None:
        raise BusinessRuleError(t["registration.no_open_year"])
    if group["school_year_id"] != year["id"]:
        raise BusinessRuleError(t["enrollment.group_other_year"].format(label=year["label"]))
    if group["status"] == "closed":
        raise BusinessRuleError(t["db.group_closed"])
    registration = registrations_repo.for_student_year(conn, student_id, year["id"])
    if registration is None or registration["status"] != "active":
        raise BusinessRuleError(t["enrollment.not_registered"].format(label=year["label"]))
    if group["level_id"] != registration["level_id"]:
        raise BusinessRuleError(t["enrollment.level_mismatch"].format(
            group=title, group_level=group["level"], level=registration["level"]))
    if repo.live_in_group(conn, student_id, group_id) is not None:
        raise BusinessRuleError(t["enrollment.already_in"].format(group=title))
    on = dates.iso(enrolled_on or default_date(group["start_date"]))
    if not group["start_date"] <= on <= group["year_end"]:
        raise ValidationError(t["enrollment.date_outside"].format(
            start=dates.display_date(group["start_date"]),
            end=dates.display_date(group["year_end"])))
    _check_seats(group, title)
    _check_free_time(conn, student_id, group, title, on)
    # The one rule the director may lift, with a reason: a second group of a subject.
    same = repo.live_in_subject(conn, student_id, group["subject_id"], group["level_id"],
                                group_id)
    if same is not None:
        if not reason:
            if ctx.role == "director":
                raise ValidationError(t["enrollment.override_reason_required"])
            raise BusinessRuleError(t["enrollment.same_subject"].format(
                subject=group["subject"], level=group["level"], other=same["name"]))
        require(ctx, "enrollment.override")
    enrollment_id = repo.insert(conn, student_id, group_id, registration["id"], on, status,
                                started_as_trial, switched_from_id)
    entry = {
        "student_id": student_id, "group_id": group_id,
        "registration_id": registration["id"], "enrolled_on": on, "status": status,
        **({"overrides": ["same_subject"], "reason": reason} if same is not None else {}),
    }
    return enrollment_id, entry


def _check_free_time(conn, student_id: int, group, title: str, on: str) -> None:
    """The group's running or future slots must not meet while another of the student's
    groups does, from the entry date on."""
    today = _today()
    for slot in timetable_repo.for_group(conn, group["id"], today):
        clash = timetable_repo.student_busy(
            conn, student_id, group["id"], slot["weekday"], slot["start_time"],
            slot["end_time"], max(slot["valid_from"], on), slot["valid_to"], today)
        if clash is not None:
            raise BusinessRuleError(t["enrollment.time_clash"].format(
                group=title, day=t[f"weekday.{slot['weekday']}"], start=slot["start_time"],
                end=slot["end_time"], other=f"{clash['group']} · {clash['subject']} "
                f"{clash['level']}", other_start=clash["start_time"],
                other_end=clash["end_time"]))


def _check_seats(group, title: str) -> None:
    """A readable message before the triggers (group is full, room is full) refuse."""
    seats = group["capacity"]
    room_limited = group["room_limit"] is not None and group["room_limit"] < seats
    if room_limited:
        seats = group["room_limit"]
    if group["enrolled"] >= seats:
        if room_limited:
            raise BusinessRuleError(t["enrollment.room_full"].format(
                group=title, room=group["limiting_room"], seats=seats))
        raise BusinessRuleError(t["enrollment.full"].format(group=title, seats=seats))


# ----- after enrolling: confirm a trial, leave, switch -----

def _require_live(conn, enrollment_id: int):
    row = repo.get(conn, enrollment_id)
    if row is None:
        raise NotFound(t["enrollment.not_found"])
    if row["status"] not in LIVE:
        raise BusinessRuleError(t["enrollment.not_live"])
    return row


def _end_date(conn, row, on: date | None) -> str:
    """The leaving date: today by default, never in the future (the seat is freed now), never
    before the entry date or a recorded attendance."""
    end = dates.iso(on or dates.today())
    if end > _today():
        raise ValidationError(t["enrollment.leave_future"])
    if end < row["enrolled_on"]:
        raise ValidationError(t["enrollment.leave_before_entry"].format(
            date=dates.display_date(row["enrolled_on"])))
    attended = repo.last_attendance_date(conn, row["id"])
    if attended is not None and end < attended:
        raise ValidationError(t["enrollment.leave_before_attendance"].format(
            date=dates.display_date(attended)))
    return end


def confirm_trial(conn, ctx: UserContext, enrollment_id: int) -> None:
    """The trial becomes a regular enrollment and keeps its seat. Its first month starts
    today, or on the entry date if later: the trial days are free."""
    require(ctx, "enrollment.update")
    with atomic(conn):
        row = _require_live(conn, enrollment_id)
        if row["status"] != "trial":
            raise BusinessRuleError(t["enrollment.not_trial"])
        repo.set_status(conn, enrollment_id, "active")
        audit.log(conn, ctx, "enrollment.confirm_trial", "enrollments", enrollment_id,
                  old={"status": "trial"}, new={"status": "active"})
        subscriptions.create_in(conn, ctx, enrollment_id, max(_today(), row["enrolled_on"]))


def leave(conn, ctx: UserContext, enrollment_id: int, left_on: date | None = None,
          reason: str = "") -> None:
    """The student leaves the group (a trial not followed up leaves too). The seat is freed."""
    require(ctx, "enrollment.update")
    with atomic(conn):
        row = _require_live(conn, enrollment_id)
        end = _end_date(conn, row, left_on)
        repo.end(conn, enrollment_id, "left", end)
        audit.log(conn, ctx, "enrollment.leave", "enrollments", enrollment_id,
                  old={"status": row["status"]},
                  new={"status": "left", "left_on": end, "reason": clean(reason) or None})


def switch(conn, ctx: UserContext, enrollment_id: int, group_id: int, on: date | None = None,
           override_reason: str | None = None) -> int:
    """Move the student to another group: the old enrollment ends as 'switched' on `on`, the new
    one points to it and starts that day (or on the new group's first day if later). A trial
    stays a trial without using the student's one trial again. The month running in the old
    group stays there; the first month in the new group starts when it ends. Returns the new
    id."""
    require(ctx, "enrollment.update")
    with atomic(conn):
        old = _require_live(conn, enrollment_id)
        if old["group_id"] == group_id:
            raise ValidationError(t["enrollment.same_group"])
        end = _end_date(conn, old, on)
        repo.end(conn, enrollment_id, "switched", end)
        target = groups_repo.get(conn, group_id, _today())
        entry_on = date.fromisoformat(end if target is None else max(end, target["start_date"]))
        new_id, entry = _place(conn, ctx, old["student_id"], group_id, entry_on, old["status"],
                               False, override_reason, switched_from_id=enrollment_id)
        audit.log(conn, ctx, "enrollment.switch", "enrollments", new_id,
                  old={"enrollment_id": enrollment_id, "group_id": old["group_id"],
                       "status": old["status"], "left_on": end},
                  new={**entry, "switched_from_id": enrollment_id})
        if old["status"] == "active":
            _first_month_after_switch(conn, ctx, enrollment_id, new_id, entry["enrolled_on"])
        return new_id


def _first_month_after_switch(conn, ctx: UserContext, old_id: int, new_id: int,
                              entry_on: str) -> None:
    """The old group keeps its running month: the new group's first month starts when that
    month ends (on the entry date when none runs). Past the end of the year, no month."""
    running = subscriptions_repo.latest(conn, old_id)
    start = entry_on if running is None else max(entry_on, running["end_date"])
    year_end = groups_repo.get(conn, repo.get(conn, new_id)["group_id"], _today())["year_end"]
    if start <= year_end:
        subscriptions.create_in(conn, ctx, new_id, start)


def end_for_closed_group(conn, ctx: UserContext, group_id: int) -> int:
    """Inside a transaction: the students of a group being closed leave it today. Returns how
    many left."""
    ended = repo.end_live_for_group(conn, group_id, _today())
    for enrollment_id in ended:
        audit.log(conn, ctx, "enrollment.leave", "enrollments", enrollment_id,
                  new={"status": "left", "reason": "group_closed"})
    return len(ended)
