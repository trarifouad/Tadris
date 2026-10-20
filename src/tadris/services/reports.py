import calendar
from datetime import date, datetime, timedelta
from itertools import pairwise

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import NotFound, ValidationError
from tadris.core.permissions import allowed, require
from tadris.core.phones import format_phone
from tadris.domain.models import (
    ATTENDANCE_STATUSES,
    AuditEntry,
    Dashboard,
    DashboardSession,
    GroupFill,
    ReportColumn,
    ReportTable,
)
from tadris.i18n.fr import t
from tadris.repositories import reports as repo
from tadris.repositories import school_years as years_repo
from tadris.services import debt, groups, journal, payouts, sessions, subscriptions, teachers

# The dashboard and the reports only read. Each report is a ReportTable of raw values (amounts
# in DA, rates in basis points, ISO dates): the screen, the PDF and the Excel file show the same
# rows and the same totals.
#
# Money, by month: « Facturé » is the months and fees starting in the month (accrual date),
# cancelled ones left out; « Réglé » is what payments not voided paid on them, whenever it was
# paid; « Encaissé » is the money received in the month (payments not voided), whatever it
# paid; « Remboursé » is what was handed back in the month. Money reports are for the director.
#
# Attendance: the rate is (present + late) / (present + late + absent); an excused absence is
# left out. Only sessions not cancelled count.
#
# Debt by age: each late charge's remainder is aged from its due date; the student's credit
# pays the oldest first, as a payment would.

AGE_BUCKETS = (30, 60, 90)  # 0-30, 31-60, 61-90, more than 90 days late
TOP_DEBTORS = 20  # the dashboard shows as many as fit
AUDIT_LIMIT = 1000


def _now_time() -> str:
    return f"{datetime.now():%H:%M}"


def _iso(day: date) -> str:
    return dates.iso(day)


def _period(first: date, last: date) -> str:
    return t["report.period"].format(first=dates.display_date(_iso(first)),
                                     last=dates.display_date(_iso(last)))


def _check_range(first: date, last: date) -> None:
    if last < first:
        raise ValidationError(t["report.dates_order"])


def _year(conn, year_id: int):
    row = years_repo.get(conn, year_id)
    if row is None:
        raise NotFound(t["year.not_found"])
    return row


def month_bounds(day: date) -> tuple[date, date]:
    first = day.replace(day=1)
    return first, day.replace(day=calendar.monthrange(day.year, day.month)[1])


def year_months(start: date, end: date) -> list[date]:
    """The first day of every month from start's to end's."""
    months, day = [], start.replace(day=1)
    while day <= end:
        months.append(day)
        day = (day.replace(day=28) + timedelta(days=4)).replace(day=1)
    return months


def month_label(day: date) -> str:
    return f"{t[f'month.{day.month}']} {day.year}"


def rate_bp(part: int, whole: int) -> int | None:
    return part * 10000 // whole if whole else None


# ----- dashboard -----

def dashboard(conn, ctx: UserContext) -> Dashboard:
    require(ctx, "dashboard.view")
    today = dates.today()
    day_sessions = tuple(
        DashboardSession(id=s.id, start_time=s.start_time, end_time=s.end_time,
                         group_title=s.group_title, room=s.room, teacher=s.teacher,
                         status=s.status)
        for s in sorted(sessions.listing(conn, ctx, today, today),
                        key=lambda s: (s.start_time, s.group_title.casefold())))
    owing = debt.debtors(conn, ctx)
    running = [g for g in groups.search(conn, ctx, status="active") if g.state == "active"]
    fills = sorted((GroupFill(group_id=g.id, title=g.title, enrolled=g.enrolled, seats=g.seats)
                    for g in running), key=lambda f: (-f.rate_bp, f.title.casefold()))
    money = {}
    if allowed(ctx, "report.finance"):
        first, last = month_bounds(today)
        charges = repo.charges_between(conn, _iso(first), _iso(last))
        month = _iso(first)[:7]
        money = {
            "charged": sum(c["amount"] for c in charges),
            "settled": sum(c["paid"] for c in charges),
            "collected": repo.collected_by_month(conn, _iso(first), _iso(last)).get(month, 0),
            "refunded": repo.refunded_by_month(conn, _iso(first), _iso(last)).get(month, 0)}
    return Dashboard(
        today=_iso(today), now=_now_time(), sessions=day_sessions,
        ending=tuple(subscriptions.ending_soon(conn, ctx)),
        lapsed=len(subscriptions.lapsed(conn, ctx)),
        debt_total=sum(d.owed_now for d in owing), debtors=len(owing),
        top_debtors=tuple(owing[:TOP_DEBTORS]), groups=tuple(fills), **money)


# ----- money -----

def _money_columns(*keys: str) -> tuple[ReportColumn, ...]:
    return tuple(ReportColumn(t[f"report.col.{key}"], "money") for key in keys)


def revenue_by_month(conn, ctx: UserContext, year_id: int) -> ReportTable:
    """Every month of the school year: charged, settled, left, collected, refunded, net."""
    require(ctx, "report.finance")
    year = _year(conn, year_id)
    start, end = date.fromisoformat(year["start_date"]), date.fromisoformat(year["end_date"])
    months = year_months(start, end)
    first, last = _iso(months[0]), _iso(month_bounds(months[-1])[1])
    charged: dict[str, list[int]] = {}
    for c in repo.charges_between(conn, first, last):
        totals = charged.setdefault(c["accrual_date"][:7], [0, 0])
        totals[0] += c["amount"]
        totals[1] += c["paid"]
    collected = repo.collected_by_month(conn, first, last)
    refunded = repo.refunded_by_month(conn, first, last)
    rows = []
    for month in months:
        key = _iso(month)[:7]
        amount, paid = charged.get(key, [0, 0])
        cash_in, cash_out = collected.get(key, 0), refunded.get(key, 0)
        rows.append((month_label(month), amount, paid, amount - paid, cash_in, cash_out,
                     cash_in - cash_out))
    return _report(
        key="recettes-par-mois", title=t["report.revenue_month.title"],
        period=t["report.year"].format(label=year["label"]),
        columns=(ReportColumn(t["report.col.month"]),) + _money_columns(
            "charged", "settled", "left", "collected", "refunded", "net"),
        rows=rows, total_label=t["report.total"], note=t["report.revenue.note"])


def revenue_by_group(conn, ctx: UserContext, year_id: int,
                     month: date | None = None) -> ReportTable:
    """Per group (and the registration fees apart): months charged, charged, settled, left,
    refunded; over the school year or one month of it."""
    require(ctx, "report.finance")
    year = _year(conn, year_id)
    if month is None:
        first, last = date.fromisoformat(year["start_date"]), date.fromisoformat(year["end_date"])
        first, last = first.replace(day=1), month_bounds(last)[1]
        period = t["report.year"].format(label=year["label"])
    else:
        first, last = month_bounds(month)
        period = month_label(first)
    lines: dict[int | None, list] = {}
    for c in repo.charges_between(conn, _iso(first), _iso(last)):
        line = lines.setdefault(c["group_id"], [c["group_title"] or t["report.fees"],
                                                0, 0, 0, 0])
        line[1] += 1
        line[2] += c["amount"]
        line[3] += c["paid"]
        line[4] += c["refunded"]
    ordered = sorted((key for key in lines if key is not None),
                     key=lambda key: lines[key][0].casefold())
    if None in lines:
        ordered.append(None)  # the fees last
    rows = [(title, count, amount, paid, amount - paid, back)
            for title, count, amount, paid, back in (lines[key] for key in ordered)]
    return _report(
        key="recettes-par-groupe", title=t["report.revenue_group.title"], period=period,
        columns=(ReportColumn(t["report.col.group"]),
                 ReportColumn(t["report.col.charges"], "number"))
        + _money_columns("charged", "settled", "left", "refunded"),
        rows=rows, total_label=t["report.total"], note=t["report.revenue_group.note"])


def _report(key: str, title: str, period: str, columns: tuple[ReportColumn, ...], rows,
            total_label: str | None = None, **extra) -> ReportTable:
    """A report whose total row sums its number and money columns."""
    rows = tuple(rows)
    total = _total(rows, columns, total_label) if total_label is not None else None
    return ReportTable(key=key, title=title, period=period, columns=columns, rows=rows,
                       total=total, **extra)


def _total(rows, columns: tuple[ReportColumn, ...], label: str) -> tuple | None:
    """The sum of every number and money column; the others stay empty."""
    if not rows:
        return None
    return (label,) + tuple(
        sum(row[index] or 0 for row in rows) if column.kind in ("number", "money") else None
        for index, column in enumerate(columns) if index > 0)


def debtors_by_age(conn, ctx: UserContext, group_id: int | None = None) -> ReportTable:
    """Students with something late, what they owe split by how late it is."""
    require(ctx, "payment.record")
    today = dates.today()
    owing = {d.student_id: d for d in debt.debtors(conn, ctx, group_id=group_id)}
    debts = debt.every_debt(conn)
    rows, ids = [], []
    for student_id, debtor in owing.items():
        buckets = age_buckets(debts[student_id], today)
        rows.append((debtor.student_name, debtor.student_number, *buckets, debtor.owed_now))
        ids.append(student_id)
    labels = [t["report.col.age"].format(low=0, high=AGE_BUCKETS[0])]
    labels += [t["report.col.age"].format(low=low + 1, high=high)
               for low, high in pairwise(AGE_BUCKETS)]
    labels.append(t["report.col.age_over"].format(days=AGE_BUCKETS[-1]))
    return _report(
        key="retards-par-anciennete", title=t["report.debtors.title"],
        period=t["report.on"].format(date=dates.display_date(_iso(today))),
        columns=(ReportColumn(t["report.col.student"]), ReportColumn(t["report.col.number"]))
        + tuple(ReportColumn(label, "money") for label in labels)
        + (ReportColumn(t["report.col.total"], "money"),),
        rows=rows, total_label=t["report.total"], note=t["report.debtors.note"],
        row_ids=tuple(ids))


def age_buckets(student_debt, today: date) -> list[int]:
    """What is late, per age bucket, after the credit paid the oldest charges first."""
    credit = student_debt.credit
    buckets = [0] * (len(AGE_BUCKETS) + 1)
    for charge in student_debt.charges:  # oldest due first
        if charge.due_date > student_debt.as_of:
            continue
        left = charge.due - min(credit, charge.due)
        credit -= charge.due - left
        if left <= 0:
            continue
        late = (today - date.fromisoformat(charge.due_date)).days
        index = next((i for i, limit in enumerate(AGE_BUCKETS) if late <= limit),
                     len(AGE_BUCKETS))
        buckets[index] += left
    return buckets


# ----- attendance -----

def _attendance_columns() -> tuple[ReportColumn, ...]:
    return tuple(ReportColumn(t[f"report.col.{status}"], "number")
                 for status in ATTENDANCE_STATUSES) + (
        ReportColumn(t["report.col.rate"], "percent"),)


def _rate(counts: dict[str, int]) -> int | None:
    came = counts["present"] + counts["late"]
    return rate_bp(came, came + counts["absent"])


def attendance_by_group(conn, ctx: UserContext, first: date, last: date) -> ReportTable:
    require(ctx, "session.view")
    _check_range(first, last)
    lines: dict[int, dict] = {}
    for mark in repo.attendance_between(conn, _iso(first), _iso(last), None):
        line = lines.setdefault(mark["group_id"], {
            "title": mark["group_title"], "sessions": set(),
            **dict.fromkeys(ATTENDANCE_STATUSES, 0)})
        line["sessions"].add(mark["session_id"])
        line[mark["status"]] += 1
    rows = [(line["title"], len(line["sessions"]),
             *(line[status] for status in ATTENDANCE_STATUSES), _rate(line))
            for line in sorted(lines.values(), key=lambda line: line["title"].casefold())]
    total = None
    if rows:
        counts = {status: sum(line[status] for line in lines.values())
                  for status in ATTENDANCE_STATUSES}
        total = (t["report.total"], sum(row[1] for row in rows),
                 *(counts[status] for status in ATTENDANCE_STATUSES), _rate(counts))
    return ReportTable(
        key="presences-par-groupe", title=t["report.attendance_group.title"],
        period=_period(first, last),
        columns=(ReportColumn(t["report.col.group"]),
                 ReportColumn(t["report.col.sessions"], "number")) + _attendance_columns(),
        rows=tuple(rows), total=total, note=t["report.attendance.note"])


def attendance_by_student(conn, ctx: UserContext, first: date, last: date,
                          group_id: int | None = None) -> ReportTable:
    """One row per student and group, the lowest rate first."""
    require(ctx, "session.view")
    _check_range(first, last)
    lines: dict[tuple[int, int], dict] = {}
    for mark in repo.attendance_between(conn, _iso(first), _iso(last), group_id):
        line = lines.setdefault((mark["student_id"], mark["group_id"]), {
            "student_id": mark["student_id"],
            "name": f"{mark['last_name']} {mark['first_name']}",
            "number": mark["student_number"], "group": mark["group_title"],
            **dict.fromkeys(ATTENDANCE_STATUSES, 0)})
        line[mark["status"]] += 1
    ordered = sorted(lines.values(), key=lambda line: (
        _rate(line) if _rate(line) is not None else 10001, line["name"].casefold(),
        line["group"].casefold()))
    rows = [(line["name"], line["number"], line["group"],
             *(line[status] for status in ATTENDANCE_STATUSES), _rate(line))
            for line in ordered]
    return ReportTable(
        key="presences-par-eleve", title=t["report.attendance_student.title"],
        period=_period(first, last),
        columns=(ReportColumn(t["report.col.student"]), ReportColumn(t["report.col.number"]),
                 ReportColumn(t["report.col.group"])) + _attendance_columns(),
        rows=tuple(rows), note=t["report.attendance.note"],
        row_ids=tuple(line["student_id"] for line in ordered))


# ----- teachers -----

def teachers_summary(conn, ctx: UserContext, year_id: int) -> ReportTable:
    """Per teacher: groups and students now, paid during the year, waiting (drafts and
    approved payouts), and what the next draft up to today would add."""
    require(ctx, "report.finance")
    require(ctx, "payout.view")
    year = _year(conn, year_id)
    today = dates.today()
    by_teacher: dict[int, list] = {}
    for g in groups.search(conn, ctx, year_id=year_id):
        if g.state != "closed" and g.teacher_id is not None:
            line = by_teacher.setdefault(g.teacher_id, [0, 0])
            line[0] += 1
            line[1] += g.enrolled
    payouts_rows = {row["teacher_id"]: row
                    for row in repo.payouts_by_teacher(conn, year["start_date"], year["end_date"])}
    rows = []
    for teacher in teachers.search(conn, ctx, status=None):
        held = by_teacher.get(teacher.id, [0, 0])
        row = payouts_rows.get(teacher.id)
        paid = row["paid"] if row else 0
        waiting = (row["drafted"] + row["approved"]) if row else 0
        months, share = payouts.not_prepared(conn, teacher.id, today)
        if teacher.status != "active" and not (held[0] or paid or waiting or share):
            continue
        rows.append((teacher.full_name, held[0], held[1], paid, waiting, months, share,
                     waiting + share))
    rows.sort(key=lambda row: row[0].casefold())
    return _report(
        key="enseignants", title=t["report.teachers.title"],
        period=t["report.year_until"].format(label=year["label"],
                                             date=dates.display_date(_iso(today))),
        columns=(ReportColumn(t["report.col.teacher"]),
                 ReportColumn(t["report.col.groups"], "number"),
                 ReportColumn(t["report.col.students"], "number"))
        + _money_columns("paid", "waiting")
        + (ReportColumn(t["report.col.months_open"], "number"),)
        + _money_columns("not_prepared", "to_pay"),
        rows=rows, total_label=t["report.total"], note=t["report.teachers.note"])


# ----- students -----

def student_list(conn, ctx: UserContext, status: str | None = "active",
                 group_id: int | None = None) -> ReportTable:
    require(ctx, "student.view")
    if status not in (None, "active", "inactive"):
        raise ValidationError(t["validation.generic"])
    year = years_repo.open_year(conn)
    owing = {student_id: d.owed_now for student_id, d in debt.every_debt(conn).items()}
    found = repo.student_list(conn, status, None if year is None else year["id"], group_id)
    rows = tuple(
        (row["student_number"], row["last_name"], row["first_name"], row["birth_date"],
         row["level"], row["groups"], row["contact"],
         format_phone(row["phone"]) if row["phone"] else None,
         t[f"student_status.{row['status']}"], owing.get(row["id"], 0))
        for row in found)
    return _report(
        key="liste-eleves", title=t["report.students.title"],
        period=(t["report.year"].format(label=year["label"]) if year is not None
                else t["report.on"].format(date=dates.display_date(_iso(dates.today())))),
        columns=(ReportColumn(t["report.col.number"]), ReportColumn(t["report.col.last_name"]),
                 ReportColumn(t["report.col.first_name"]),
                 ReportColumn(t["report.col.birth"], "date"),
                 ReportColumn(t["report.col.level"]), ReportColumn(t["report.col.groups"]),
                 ReportColumn(t["report.col.contact"]), ReportColumn(t["report.col.phone"]),
                 ReportColumn(t["report.col.status"]),
                 ReportColumn(t["report.col.owed"], "money")),
        rows=rows, total_label=t["report.count"].format(count=len(rows)),
        note=t["report.students.note"], row_ids=tuple(row["id"] for row in found))


# ----- audit log -----

def audit_users(conn, ctx: UserContext) -> list[tuple[int, str]]:
    require(ctx, "audit.view")
    return [(row["id"], row["username"]) for row in repo.users(conn)]


def audit_families(conn, ctx: UserContext) -> list[str]:
    require(ctx, "audit.view")
    return repo.audit_families(conn)


def family_label(family: str) -> str:
    return t.get(f"audit.family.{family}", family)


def audit_log(conn, ctx: UserContext, first: date, last: date, user_id: int | None = None,
              family: str | None = None, entity_id: int | None = None) -> list[AuditEntry]:
    """What people did, latest first, at most AUDIT_LIMIT entries (and a failed backup)."""
    require(ctx, "audit.view")
    _check_range(first, last)
    return [AuditEntry(id=row["id"], created_at=row["created_at"], user=row["username"],
                       action=row["action"], entity_name=row["entity_name"],
                       entity_id=row["entity_id"], old_value=row["old_value"],
                       new_value=row["new_value"])
            for row in repo.audit_entries(conn, _iso(first), _iso(last), user_id, family,
                                          entity_id, AUDIT_LIMIT)]


def audit_fields(conn, ctx: UserContext, entry: AuditEntry) -> list[journal.Field]:
    """What the entry recorded, for the detail under the Journal (without the item's own
    name, shown above it)."""
    require(ctx, "audit.view")
    names = journal.load_names(conn)
    item = names.get(entry.entity_name, entry.entity_id)
    return journal.fields(entry.old_value, entry.new_value, names, skip=item)


def audit_table(conn, entries: list[AuditEntry], first: date, last: date) -> ReportTable:
    names = journal.load_names(conn)
    return ReportTable(
        key="journal", title=t["report.audit.title"], period=_period(first, last),
        columns=(ReportColumn(t["report.col.when"], "datetime"),
                 ReportColumn(t["report.col.user"]), ReportColumn(t["report.col.action"]),
                 ReportColumn(t["report.col.entity"]), ReportColumn(t["report.col.detail"])),
        rows=tuple((e.created_at, e.user or t["audit.system"], journal.action_label(e.action),
                    journal.entity_label(e.entity_name, e.entity_id, names),
                    journal.summary(e.old_value, e.new_value, names))
                   for e in entries),
        note=(t["report.audit.limit"].format(limit=AUDIT_LIMIT)
              if len(entries) >= AUDIT_LIMIT else ""))
