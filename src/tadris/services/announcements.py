"""Ready-made WhatsApp messages, filled from what Tadris knows: a cancelled or moved session,
the next one, a substitute teacher, a holiday, the timetable, the month to pay, an absence,
a debt. The desk picks a model and, when it needs one, what it is about (which session,
which holiday…); the text lands in the message box, where it can still be edited.

A group model speaks of the group and suits its WhatsApp group; a student model speaks of
one child and goes to their parents only. {élève} is left in the text: each parent gets the
names of their own children (whatsapp.personal)."""

from dataclasses import dataclass
from datetime import date, timedelta

from tadris.core import dates, whatsapp
from tadris.core.context import UserContext
from tadris.core.errors import ValidationError
from tadris.core.money import format_dzd
from tadris.core.permissions import require
from tadris.core.text import fold
from tadris.domain.models import Group, Session
from tadris.i18n.fr import t
from tadris.repositories import messages as repo_messages
from tadris.services import (
    attendance,
    debt,
    groups,
    holidays,
    sessions,
    settings,
    students,
    timetable,
)

# (kind, needs a choice). Order: as the desk meets them, most frequent first.
GROUP_KINDS = (
    ("free", False), ("invite", False), ("cancelled", True), ("moved", True),
    ("reminder", True), ("substitute", True), ("holiday", True), ("timetable", False),
    ("payment", True),
)
STUDENT_KINDS = (("free", False), ("absence", True), ("debt", False), ("holiday", True))
NEEDS_CHOICE = {kind for kind, needs in GROUP_KINDS + STUDENT_KINDS if needs}

PAST_DAYS = 7  # a session cancelled last week can still be announced (a makeup to come)
AHEAD_DAYS = 30  # sessions a month ahead (generated ones reach 14 days; makeups may be later)
ABSENCE_DAYS = 30


@dataclass(frozen=True)
class Choice:
    id: object  # a session id, a holiday id, a month 'YYYY-MM', an attendance session id
    label: str


def kinds(target: str) -> tuple[str, ...]:
    """The models offered for a group ('group') or one student ('student')."""
    return tuple(kind for kind, _ in (GROUP_KINDS if target == "group" else STUDENT_KINDS))


# ----- wording -----

def day_label(iso_date: str) -> str:
    """'2026-10-29' -> 'jeudi 29/10/2026'."""
    day = date.fromisoformat(iso_date[:10])
    return f"{t[f'weekday.{dates.weekday_1_to_7(day)}']} {dates.display_date(iso_date)}"


def group_label(g: Group) -> str:
    """How parents name it: 'Maths 4AM (M1)'; just 'Français 1AM' when the group is named
    after its subject and level already."""
    course = f"{g.subject} {g.level}"
    return course if fold(g.name) == fold(course) else f"{course} ({g.name})"


def _session_label(s: Session) -> str:
    return t["announce.session_choice"].format(day=day_label(s.date), start=s.start_time,
                                               end=s.end_time)


def _school(conn) -> str:
    return settings.get(conn, "school.name", "")


# ----- what a model is about -----

def _window(back: int, ahead: int) -> tuple[date, date]:
    today = dates.today()
    return today - timedelta(days=back), today + timedelta(days=ahead)


def _group_sessions(conn, ctx, group_id: int) -> list[Session]:
    first, last = _window(PAST_DAYS, AHEAD_DAYS)
    return sessions.listing(conn, ctx, first, last, group_id=group_id)


def choices(conn, ctx: UserContext, kind: str, group_id: int | None = None,
            student_id: int | None = None) -> list[Choice]:
    """What the model can be about; empty: nothing to announce (the page says why)."""
    require(ctx, "message.send")
    today = dates.iso(dates.today())
    if kind == "cancelled":
        # Only what is cancelled in Tadris (Présences): the message follows the data, it
        # never stands in for it. A session still planned is not offered.
        return [Choice(s.id, _session_label(s) + (f" · {s.cancellation_reason}"
                                                  if s.cancellation_reason else ""))
                for s in _group_sessions(conn, ctx, group_id)
                if s.status == "cancelled" and s.makeup_id is None]
    if kind == "moved":
        return [Choice(s.id, t["announce.moved_choice"].format(
                    old=day_label(s.date), new=day_label(s.makeup_date)))
                for s in _group_sessions(conn, ctx, group_id)
                if s.status == "cancelled" and s.makeup_id is not None
                and s.makeup_date >= today]
    if kind == "reminder":
        return [Choice(s.id, _session_label(s)) for s in _group_sessions(conn, ctx, group_id)
                if s.status == "planned" and s.date >= today]
    if kind == "substitute":
        return [Choice(s.id, f"{_session_label(s)} · {s.teacher}")
                for s in _group_sessions(conn, ctx, group_id)
                if s.status == "planned" and s.date >= today and s.substitute]
    if kind == "holiday":
        found = [h for h in holidays.list_holidays(conn, ctx) if h.end_date >= today]
        return [Choice(h.id, t["announce.holiday_choice"].format(
                    label=h.label, period=_period(h.start_date, h.end_date)))
                for h in reversed(found)]  # the nearest first
    if kind == "payment":
        this = dates.today().replace(day=1)
        months = (this, dates.add_one_month(this))
        return [Choice(m.strftime("%Y-%m"), _month(m)) for m in months]
    if kind == "absence":
        first, _ = _window(ABSENCE_DAYS, 0)
        return [Choice(r.session_id, t["announce.absence_choice"].format(
                    day=day_label(r.date), group=r.group_title,
                    status=t[f"attendance_status.{r.status}"]))
                for r in attendance.for_student(conn, ctx, student_id, limit=60)
                if r.status in ("absent", "late") and r.date >= dates.iso(first)]
    return []


def _month(first_day: date) -> str:
    return f"{t[f'month.{first_day.month}'].lower()} {first_day.year}"


def _period(start: str, end: str) -> str:
    if start == end:
        return t["announce.on_day"].format(day=day_label(start))
    return t["announce.from_to"].format(first=day_label(start), last=day_label(end))


# ----- the text -----

def compose(conn, ctx: UserContext, kind: str, choice: object = None,
            group_id: int | None = None, student_id: int | None = None) -> str:
    """The message of a model; free: empty. Signed with the school's name."""
    require(ctx, "message.send")
    if kind == "free":
        return ""
    if kind in NEEDS_CHOICE and choice is None:
        raise ValidationError(t[f"announce.none.{kind}"])
    body = _body(conn, ctx, kind, choice, group_id, student_id)
    school = _school(conn)
    return f"{body}\n\n{school}" if school else body


def _body(conn, ctx, kind, choice, group_id, student_id) -> str:
    student = whatsapp.STUDENT
    if kind in ("absence", "debt"):
        students.get(conn, ctx, student_id)  # NotFound
    if kind == "absence":
        record = next(r for r in attendance.for_student(conn, ctx, student_id, limit=60)
                      if r.session_id == choice)
        return t[f"announce.text.absence.{record.status}"].format(
            student=student, group=record.group_title, day=day_label(record.date),
            start=record.start_time, end=record.end_time)
    if kind == "debt":
        owed = debt.for_student(conn, ctx, student_id).owed_now
        if owed <= 0:
            raise ValidationError(t["announce.none.debt"])
        return t["announce.text.debt"].format(student=student, amount=format_dzd(owed))
    if kind == "holiday":
        h = next(h for h in holidays.list_holidays(conn, ctx) if h.id == choice)
        if h.start_date == h.end_date:
            return t["announce.text.holiday_day"].format(day=day_label(h.start_date),
                                                         label=h.label)
        back = dates.iso(date.fromisoformat(h.end_date) + timedelta(days=1))
        return t["announce.text.holiday"].format(
            first=day_label(h.start_date), last=day_label(h.end_date), label=h.label,
            back=day_label(back))

    g = groups.get(conn, ctx, group_id)
    name = group_label(g)
    if kind == "invite":
        code = _code(conn, group_id)
        return t["announce.text.invite"].format(school=_school(conn), group=name,
                                                student=student,
                                                link=whatsapp.invite_link(code))
    if kind == "timetable":
        return _timetable(conn, ctx, g, name)
    if kind == "payment":
        month = _month(date.fromisoformat(f"{choice}-01"))
        key = "announce.text.payment" if g.price else "announce.text.payment_no_price"
        return t[key].format(month=month, group=name, price=format_dzd(g.price))

    s = sessions.get(conn, ctx, choice)
    when = {"group": name, "day": day_label(s.date), "start": s.start_time,
            "end": s.end_time, "room": s.room}
    if kind == "cancelled":
        text = t["announce.text.cancelled"].format(**when)
        if s.cancellation_reason:
            text += "\n" + t["announce.text.reason"].format(reason=s.cancellation_reason)
        return text
    if kind == "moved":
        makeup = sessions.get(conn, ctx, s.makeup_id)
        return t["announce.text.moved"].format(
            **when, new_day=day_label(makeup.date), new_start=makeup.start_time,
            new_end=makeup.end_time, new_room=makeup.room)
    if kind == "reminder":
        return t["announce.text.reminder"].format(**when)
    if kind == "substitute":
        return t["announce.text.substitute"].format(**when, teacher=s.teacher,
                                                    usual=g.teacher or "")
    raise ValidationError(t["validation.generic"])


def _code(conn, group_id: int) -> str:
    code = repo_messages.group_code(conn, group_id)
    if code is None:
        raise ValidationError(t["whatsapp_group.not_linked"])
    return code


def _timetable(conn, ctx, g: Group, name: str) -> str:
    slots = sorted(timetable.group_slots(conn, ctx, g.id),
                   key=lambda s: ((s.weekday - 6) % 7, s.start_time))  # Saturday first
    if not slots:
        raise ValidationError(t["announce.none.timetable"])
    today = dates.iso(dates.today())
    lines = []
    for s in slots:
        line = t["announce.timetable_line"].format(
            weekday=t[f"weekday.{s.weekday}"], start=s.start_time, end=s.end_time, room=s.room)
        if s.valid_from > today:
            line += " " + t["announce.timetable_from"].format(
                day=dates.display_date(s.valid_from))
        lines.append(line)
    head = (t["announce.text.starts"].format(group=name, day=day_label(g.start_date))
            if g.state == "upcoming" else t["announce.text.timetable"].format(group=name))
    return head + "\n" + "\n".join(lines)
