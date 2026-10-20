from collections import Counter

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError, NotFound, ValidationError
from tadris.core.permissions import require
from tadris.db.errors import atomic
from tadris.domain.models import (
    ATTENDANCE_STATUSES,
    AttendanceRecord,
    AttendanceSummary,
    RosterLine,
)
from tadris.i18n.fr import t
from tadris.repositories import attendance as repo
from tadris.repositories import sessions as sessions_repo
from tadris.services import audit

# Attendance is taken per session for the group's students on that date (trial students
# included). It can be entered from the session's day on, never before, and corrected at any
# time by both roles: every save writes one audit entry with each change (old and new
# status). The first save marks the session held. Students whose month does not cover the
# date are flagged « Mois non renouvelé » but listed like everyone else.


def _today() -> str:
    return dates.iso(dates.today())


def _require_session(conn, session_id: int):
    row = sessions_repo.get(conn, session_id)
    if row is None:
        raise NotFound(t["session.not_found"])
    return row


def roster(conn, ctx: UserContext, session_id: int) -> list[RosterLine]:
    require(ctx, "session.view")
    _require_session(conn, session_id)
    return [
        RosterLine(enrollment_id=row["enrollment_id"], student_id=row["student_id"],
                   student_number=row["student_number"],
                   student_name=f"{row['last_name']} {row['first_name']}",
                   trial=row["enrollment_status"] == "trial",
                   not_renewed=bool(row["not_renewed"]), status=row["status"])
        for row in repo.roster(conn, session_id)
    ]


def save(conn, ctx: UserContext, session_id: int, marks: dict[int, str]) -> int:
    """Record {enrollment_id: status} for the session. Lines left out stay as they are.
    Returns how many lines changed."""
    require(ctx, "attendance.save")
    if any(status not in ATTENDANCE_STATUSES for status in marks.values()):
        raise ValidationError(t["attendance.status_invalid"])
    with atomic(conn):
        session = _require_session(conn, session_id)
        if session["status"] == "cancelled":
            raise BusinessRuleError(t["attendance.session_cancelled"])
        if session["date"] > _today():
            raise BusinessRuleError(t["attendance.future"].format(
                date=dates.display_date(session["date"])))
        expected = {row["enrollment_id"] for row in repo.roster(conn, session_id)}
        if set(marks) - expected:
            raise BusinessRuleError(t["attendance.not_in_session"])
        before = repo.statuses(conn, session_id)
        changes = []
        for enrollment_id, status in sorted(marks.items()):
            old = before.get(enrollment_id)
            if old == status:
                continue
            if old is None:
                repo.insert(conn, session_id, enrollment_id, status, ctx.user_id)
            else:
                repo.update(conn, session_id, enrollment_id, status, ctx.user_id)
            changes.append({"enrollment_id": enrollment_id, "old": old, "new": status})
        if changes:
            repo.mark_held(conn, session_id)
            audit.log(conn, ctx, "attendance.save", "sessions", session_id,
                      new={"date": session["date"], "changes": changes})
        return len(changes)


def summarize(statuses) -> AttendanceSummary:
    counts = Counter(statuses)
    return AttendanceSummary(present=counts["present"], late=counts["late"],
                             absent=counts["absent"], excused=counts["excused"])


def for_student(conn, ctx: UserContext, student_id: int, limit: int | None = None,
                offset: int = 0) -> list[AttendanceRecord]:
    """Latest first; limit/offset: one page (a student marks about 300 a year)."""
    require(ctx, "student.view")
    return [
        AttendanceRecord(session_id=row["session_id"], date=row["date"],
                         start_time=row["start_time"], end_time=row["end_time"],
                         group_id=row["group_id"],
                         group_title=f"{row['group_name']} · {row['subject']} {row['level']}",
                         status=row["status"])
        for row in repo.for_student(conn, student_id, limit, offset)
    ]


def summary_for_student(conn, ctx: UserContext, student_id: int) -> AttendanceSummary:
    """The counts over the student's whole history, counted by the database."""
    require(ctx, "student.view")
    counts = repo.counts_for_student(conn, student_id)
    return AttendanceSummary(**{status: counts.get(status, 0)
                                for status in ("present", "late", "absent", "excused")})
