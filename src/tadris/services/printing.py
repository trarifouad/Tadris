import re
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path

from tadris import config
from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.permissions import require
from tadris.core.text import fold
from tadris.db.errors import atomic
from tadris.documents.attendance_sheet import (
    TICK,
    SessionSheet,
    WeekSheet,
    build_session_sheet,
    build_week_sheet,
)
from tadris.documents.pdf import Footer, School
from tadris.domain.models import ATTENDANCE_STATUSES
from tadris.i18n.fr import t
from tadris.repositories import print_log
from tadris.services import attendance, groups, sessions, settings

# Printed documents are PDF files written to config.documents_dir() (next to the database)
# and opened in the system viewer, where they are printed. Every document made is written to
# print_log (type, id, who, when).

SESSION_SHEET = "attendance_session"
WEEK_SHEET = "attendance_week"
LETTERS = {"present": "P", "late": "R", "absent": "A", "excused": "E"}


def _school(conn) -> School:
    return School(name=settings.get(conn, "school.name", "") or t["app.name"],
                  address=settings.get(conn, "school.address", "") or "",
                  phone=settings.get(conn, "school.phone", "") or "")


def _footer(ctx: UserContext) -> Footer:
    now = datetime.now()
    return Footer(t["print.footer"].format(date=dates.display_date(dates.iso(dates.today())),
                                           time=f"{now:%H:%M}", user=ctx.username))


def _file(kind: str, name: str, day: str, out_dir: Path | None) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", fold(name)).strip("-") or "groupe"
    return (out_dir or config.documents_dir()) / f"{kind}_{slug}_{day}.pdf"


def _log(conn, ctx: UserContext, kind: str, document_id: int) -> None:
    with atomic(conn):
        print_log.insert(conn, kind, document_id, ctx.user_id)


def session_sheet(conn, ctx: UserContext, session_id: int, out_dir: Path | None = None) -> Path:
    """The sheet of one session: a box per status, ticked when already recorded."""
    require(ctx, "print.document")
    sheet = session_sheet_content(conn, ctx, session_id)
    s = sessions.get(conn, ctx, session_id)
    path = build_session_sheet(sheet, _file("presence", s.group_name, s.date, out_dir))
    _log(conn, ctx, SESSION_SHEET, session_id)
    return path


def session_sheet_content(conn, ctx: UserContext, session_id: int) -> SessionSheet:
    s = sessions.get(conn, ctx, session_id)
    day = t[f"weekday.{dates.weekday_1_to_7(date.fromisoformat(s.date))}"]
    teacher = s.teacher + (f" ({t['sessions_page.substitute_mark']})" if s.substitute else "")
    details = [t["print.session_when"].format(day=day, date=dates.display_date(s.date),
                                              start=s.start_time, end=s.end_time),
               t["print.session_where"].format(room=s.room, teacher=teacher)]
    if s.status == "cancelled":
        details.append(t["print.session_cancelled"].format(reason=s.cancellation_reason))
    rows = []
    for line in attendance.roster(conn, ctx, session_id):
        notes = []
        if line.trial:
            notes.append(t["attendance_view.trial"])
        if line.not_renewed:
            notes.append(t["print.not_renewed_short"])
        rows.append([line.student_number, line.student_name, ", ".join(notes)]
                    + [TICK if line.status == status else "" for status in ATTENDANCE_STATUSES]
                    + [""])
    return SessionSheet(
        school=_school(conn), title=t["print.session_title"], heading=s.group_title,
        details=details,
        columns=[escape(c) for c in [t["print.col.number"], t["print.col.student"],
                                     t["print.col.note"]]
                 + [t[f"attendance_status.{status}"] for status in ATTENDANCE_STATUSES]
                 + [t["print.col.observation"]]],
        rows=rows, footer=_footer(ctx), empty=t["attendance_view.empty"])


def week_sheet(conn, ctx: UserContext, group_id: int, first: date,
               out_dir: Path | None = None) -> Path:
    """A group's week from `first` (seven days): a column per session, a row per student."""
    require(ctx, "print.document")
    sheet = week_sheet_content(conn, ctx, group_id, first)
    name = groups.get(conn, ctx, group_id).name
    path = build_week_sheet(sheet, _file("presence-semaine", name, dates.iso(first), out_dir))
    _log(conn, ctx, WEEK_SHEET, group_id)
    return path


def week_sheet_content(conn, ctx: UserContext, group_id: int, first: date) -> WeekSheet:
    g = groups.get(conn, ctx, group_id)
    last = first + timedelta(days=6)
    week = sessions.listing(conn, ctx, first, last, group_id=group_id)
    rosters = {s.id: {line.enrollment_id: line for line in attendance.roster(conn, ctx, s.id)}
               for s in week}
    students: dict[int, tuple[str, str]] = {}
    for lines in rosters.values():
        for line in lines.values():
            students[line.enrollment_id] = (line.student_number, line.student_name)
    columns = [escape(t["print.col.number"]), escape(t["print.col.student"])]
    cancelled = []
    for index, s in enumerate(week):
        day = t[f"weekday.{dates.weekday_1_to_7(date.fromisoformat(s.date))}"][:3]
        label = f"{day} {dates.display_date(s.date)[:5]}<br/>{s.start_time}"
        if s.status == "cancelled":
            label += f"<br/>{escape(t['session_status.cancelled'])}"
            cancelled.append(index + 2)
        columns.append(label)
    rows = []
    for enrollment_id, (number, name) in sorted(students.items(), key=lambda kv: fold(kv[1][1])):
        cells = []
        for s in week:
            line = rosters[s.id].get(enrollment_id)
            if line is None:
                cells.append("—")  # not in the group that day
            else:
                cells.append(LETTERS.get(line.status, ""))
        rows.append([number, name] + cells)
    return WeekSheet(
        school=_school(conn), title=t["print.week_title"], heading=g.title,
        details=[t["print.week_when"].format(first=dates.display_date(dates.iso(first)),
                                             last=dates.display_date(dates.iso(last))),
                 t["print.week_teacher"].format(teacher=g.teacher or "—")],
        columns=columns, rows=rows, footer=_footer(ctx), legend=t["print.week_legend"],
        empty=t["print.week_empty"], cancelled_columns=cancelled)
