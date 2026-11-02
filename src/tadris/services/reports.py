"""Rapports: four reports, each a Report of raw values (amounts in DA, rates in basis points,
ISO dates) that the screen, the PDF and the Excel file show alike.

Money (Recettes, Enseignants: the director's). « Facturé » is the months and fees starting in
the period (accrual date), cancelled ones left out; « Réglé » is what payments not voided paid
on them, whenever; « Reste dû » the difference; « Encaissé » the money received in the period
(payments not voided), whatever it paid. A teacher's share of a month is its full price at the
rate of the group's teacher on its first day, as payouts count it, rounded down to the dinar
per month, group and rate (a payout rounds once per line: a few dinars apart at most); the
school keeps the rest, and the registration fees.

Attendance: the rate is (present + late) / (present + late + absent): an excused absence is
left out; cancelled sessions do not count. A row under LOW_RATE_BP is flagged.
"""

import calendar
from datetime import date, datetime, timedelta
from pathlib import Path

from tadris import config
from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import NotFound, ValidationError
from tadris.core.money import format_dzd
from tadris.core.percent import apply_rate, format_percent
from tadris.core.permissions import allowed, require
from tadris.core.phones import format_phone
from tadris.core.text import fold
from tadris.db.errors import atomic
from tadris.documents.report_pdf import build_report_pdf
from tadris.documents.report_xlsx import build_report_xlsx
from tadris.domain.models import (
    ATTENDANCE_STATUSES,
    Report,
    ReportChart,
    ReportColumn,
    ReportTile,
)
from tadris.i18n.fr import t
from tadris.repositories import reports as repo
from tadris.repositories import school_years as years_repo
from tadris.services import audit, catalog, debt, groups, payouts, printing, teachers

# Each report and what it takes to see it; the page lists the ones the user has.
REPORTS = {"revenue": "report.finance", "attendance": "session.view",
           "teachers": "report.finance", "students": "student.view"}
LOW_RATE_BP = 7500  # attendance under 75 %: the row is flagged
PERIODS = ("week", "month", "last_month", "year", "custom")  # Présences


def available(ctx: UserContext) -> list[str]:
    if not allowed(ctx, "report.view"):
        return []
    return [key for key, action in REPORTS.items() if allowed(ctx, action)]


# ----- dates -----

def month_end(day: date) -> date:
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


def year_months(start: date, end: date) -> list[date]:
    """The first day of every month from start's to end's."""
    months, day = [], start.replace(day=1)
    while day <= end:
        months.append(day)
        day = month_end(day) + timedelta(days=1)
    return months


def month_label(day: date) -> str:
    return f"{t[f'month.{day.month}']} {day.year}"


def period_text(first: date, last: date) -> str:
    return t["reports.period"].format(first=dates.display_date(dates.iso(first)),
                                      last=dates.display_date(dates.iso(last)))


def period_range(conn, key: str, today: date, year_id: int | None = None) -> tuple[date, date]:
    """The days a period preset covers: this week (Saturday to Friday), this month, last
    month, or the school year `year_id`."""
    if key == "week":
        first = dates.week_start(today)
        return first, first + timedelta(days=6)
    if key == "month":
        return today.replace(day=1), month_end(today)
    if key == "last_month":
        last = today.replace(day=1) - timedelta(days=1)
        return last.replace(day=1), last
    if key == "year" and year_id is not None:
        year = _year(conn, year_id)
        return date.fromisoformat(year["start_date"]), date.fromisoformat(year["end_date"])
    raise ValidationError(t["validation.generic"])


def rate_bp(part: int, whole: int) -> int | None:
    return part * 10000 // whole if whole else None


def _year(conn, year_id: int | None):
    if year_id is None:
        raise ValidationError(t["reports.no_year"])
    row = years_repo.get(conn, year_id)
    if row is None:
        raise NotFound(t["year.not_found"])
    return row


def years(conn, ctx: UserContext) -> list[tuple[int, str]]:
    """The school years, latest first, for the filters."""
    require(ctx, "report.view")
    return [(row["id"], row["label"]) for row in years_repo.list_all(conn)]


def default_year(conn) -> int | None:
    """The open year, else the latest."""
    year = years_repo.open_year(conn) or next(iter(years_repo.list_all(conn)), None)
    return None if year is None else year["id"]


def _check_range(first: date, last: date) -> None:
    if last < first:
        raise ValidationError(t["reports.dates_order"])


def _groups(conn, ctx: UserContext) -> dict:
    return {g.id: g for g in groups.search(conn, ctx)}


# ----- Recettes -----

def _money(*keys: str) -> tuple[ReportColumn, ...]:
    return tuple(ReportColumn(t[f"reports.col.{key}"], "money") for key in keys)


def _shares(charges) -> dict[tuple[str, int, int], int]:
    """The teachers' share, rounded down once per (month, group, teacher) and rate:
    {(month, group_id, teacher_id): share}."""
    amounts: dict[tuple[str, int, int, int], int] = {}
    for c in charges:
        if c["group_id"] is None or c["percentage_bp"] is None:
            continue
        key = (c["accrual_date"][:7], c["group_id"], c["teacher_id"], c["percentage_bp"])
        amounts[key] = amounts.get(key, 0) + c["amount"]
    shares: dict[tuple[str, int, int], int] = {}
    for (month, group_id, teacher_id, bp), amount in amounts.items():
        key = (month, group_id, teacher_id)
        shares[key] = shares.get(key, 0) + apply_rate(amount, bp)
    return shares


def _year_charges(conn, year) -> tuple[list[date], list, dict[str, int]]:
    start = date.fromisoformat(year["start_date"])
    end = date.fromisoformat(year["end_date"])
    months = year_months(start, end)
    first, last = dates.iso(months[0]), dates.iso(month_end(months[-1]))
    return (months, repo.charges_between(conn, first, last),
            repo.collected_by_month(conn, first, last))


def revenue(conn, ctx: UserContext, year_id: int, view: str = "month") -> Report:
    """The school year's money, by month or by group (the registration fees on a line of
    their own)."""
    require(ctx, "report.finance")
    if view not in ("month", "group"):
        raise ValidationError(t["validation.generic"])
    year = _year(conn, year_id)
    months, charges, collected = _year_charges(conn, year)
    shares = _shares(charges)
    charged = sum(c["amount"] for c in charges)
    settled = sum(c["paid"] for c in charges)
    share = sum(shares.values())
    received = sum(collected.values())
    tiles = (
        ReportTile(t["reports.tile.charged"], charged,
                   note=t["reports.tile.charged_note"].format(count=len(charges))),
        ReportTile(t["reports.tile.collected"], received,
                   note=t["reports.tile.collected_note"]),
        ReportTile(t["reports.tile.left"], charged - settled,
                   note=t["reports.tile.left_note"].format(
                       rate=_percent(rate_bp(charged - settled, charged)))),
        ReportTile(t["reports.tile.school"], charged - share,
                   note=t["reports.tile.school_note"].format(share=_dzd(share))),
    )
    by_month: dict[str, list[int]] = {}
    for c in charges:
        line = by_month.setdefault(c["accrual_date"][:7], [0, 0])
        line[0] += c["amount"]
        line[1] += c["paid"]
    month_share: dict[str, int] = {}
    for (month, _group, _teacher), value in shares.items():
        month_share[month] = month_share.get(month, 0) + value
    keys = [dates.iso(m)[:7] for m in months]
    chart = ReportChart(
        "bars", t["reports.chart.revenue"],
        tuple(t[f"month_short.{m.month}"] for m in months),
        ((t["reports.tile.charged"], tuple(by_month.get(k, [0, 0])[0] for k in keys)),
         (t["reports.tile.collected"], tuple(collected.get(k, 0) for k in keys))))
    common = {"tiles": tiles, "chart": chart, "note": t["reports.revenue.note"],
              "period": t["reports.year"].format(label=year["label"])}
    if view == "month":
        rows = []
        for month, key in zip(months, keys, strict=True):
            amount, paid = by_month.get(key, [0, 0])
            part = month_share.get(key, 0)
            rows.append((month_label(month), amount, paid, amount - paid,
                         collected.get(key, 0), part, amount - part))
        columns = (ReportColumn(t["reports.col.month"]),) + _money(
            "charged", "settled", "left", "collected", "teachers_share", "school_share")
        return Report(key="recettes-par-mois", title=t["reports.revenue_month.title"],
                      columns=columns, rows=tuple(rows), total=_total(rows, columns),
                      **common)
    return _revenue_by_group(conn, ctx, charges, shares, year, common)


def _revenue_by_group(conn, ctx: UserContext, charges, shares, year, common) -> Report:
    found = _groups(conn, ctx)
    lines: dict[int | None, dict] = {}
    for c in charges:
        line = lines.setdefault(c["group_id"], {"months": 0, "charged": 0, "settled": 0,
                                                "rates": set(), "share": 0})
        line["months"] += 1
        line["charged"] += c["amount"]
        line["settled"] += c["paid"]
        if c["percentage_bp"] is not None:
            line["rates"].add(c["percentage_bp"])
    for (_month, group_id, _teacher), value in shares.items():
        lines[group_id]["share"] += value
    ordered = sorted((key for key in lines if key is not None),
                     key=lambda key: found[key].title.casefold() if key in found else "")
    rows, ids = [], []
    for key in ordered + ([None] if None in lines else []):  # the fees last
        line = lines[key]
        group = found.get(key)
        title = t["reports.fees"] if key is None else (group.title if group else "—")
        rate = next(iter(line["rates"])) if len(line["rates"]) == 1 else None
        rows.append((title, group.teacher if group else None, line["months"],
                     line["charged"], line["settled"], line["charged"] - line["settled"],
                     rate, line["share"], line["charged"] - line["share"]))
        ids.append(key)
    columns = (ReportColumn(t["reports.col.group"]), ReportColumn(t["reports.col.teacher"]),
               ReportColumn(t["reports.col.months"], "number"))
    columns += _money("charged", "settled", "left")
    columns += (ReportColumn(t["reports.col.rate"], "percent"),)
    columns += _money("teachers_share", "school_share")
    return Report(key="recettes-par-groupe", title=t["reports.revenue_group.title"],
                  columns=columns, rows=tuple(rows), total=_total(rows, columns, skip={6}),
                  row_ids=tuple(ids), opens="groups", **common)


def _total(rows, columns: tuple[ReportColumn, ...], skip: set[int] = frozenset(),
           label: str | None = None) -> tuple | None:
    """The sum of every number and money column (except `skip`); the others stay empty."""
    if not rows:
        return None
    return (label or t["reports.total"],) + tuple(
        sum(row[index] or 0 for row in rows)
        if column.kind in ("number", "money") and index not in skip else None
        for index, column in enumerate(columns) if index > 0)


def _dzd(amount: int) -> str:
    """An amount in a sentence: it never breaks across two lines."""
    return format_dzd(amount).replace(" ", "\u00a0")


def _percent(bp: int | None) -> str:
    return "—" if bp is None else format_percent(bp)


# ----- Présences -----

def _rate(counts) -> int | None:
    came = counts["present"] + counts["late"]
    return rate_bp(came, came + counts["absent"])


def _tone(rate: int | None) -> str | None:
    return "danger" if rate is not None and rate < LOW_RATE_BP else None


def attendance(conn, ctx: UserContext, first: date, last: date, group_id: int | None = None,
               view: str = "group") -> Report:
    """Attendance between two days, by group or by student (the lowest rate first)."""
    require(ctx, "session.view")
    _check_range(first, last)
    if view not in ("group", "student"):
        raise ValidationError(t["validation.generic"])
    found = _groups(conn, ctx)
    by_group = repo.attendance_by_group(conn, dates.iso(first), dates.iso(last), group_id)
    counts = {status: sum(row[status] or 0 for row in by_group)
              for status in ATTENDANCE_STATUSES}
    held = sum(row["sessions"] for row in by_group)
    overall = _rate(counts)
    tiles = (
        ReportTile(t["reports.tile.rate"], overall, "percent",
                   t["reports.tile.rate_note"].format(
                       came=counts["present"] + counts["late"],
                       marks=counts["present"] + counts["late"] + counts["absent"])),
        ReportTile(t["reports.tile.sessions"], held, "number",
                   t["reports.tile.sessions_note"].format(groups=len(by_group))),
        ReportTile(t["reports.tile.absent"], counts["absent"], "number",
                   t["reports.tile.absent_note"].format(excused=counts["excused"])),
        ReportTile(t["reports.tile.late"], counts["late"], "number",
                   t["reports.tile.late_note"]),
    )
    title_of = {key: (found[key].title if key in found else "—") for key in
                (row["group_id"] for row in by_group)}
    rated = sorted(by_group, key=lambda row: (-(_rate(row) or 0), title_of[row["group_id"]]))
    chart = ReportChart("rates", t["reports.chart.attendance"],
                        tuple(title_of[row["group_id"]] for row in rated),
                        ((t["reports.tile.rate"], tuple(_rate(row) or 0 for row in rated)),))
    group_name = found[group_id].title if group_id in found else t["reports.all_groups"]
    common = {"tiles": tiles, "chart": chart, "note": t["reports.attendance.note"],
              "period": period_text(first, last),
              "filters": ((t["reports.filter.period"], period_text(first, last)),
                          (t["reports.filter.group"], group_name))}
    marks = tuple(ReportColumn(t[f"reports.col.{status}"], "number")
                  for status in ATTENDANCE_STATUSES) + (
        ReportColumn(t["reports.col.attendance_rate"], "percent"),)
    if view == "group":
        ordered = sorted(by_group, key=lambda row: title_of[row["group_id"]].casefold())
        rows = tuple(
            (title_of[row["group_id"]],
             found[row["group_id"]].teacher if row["group_id"] in found else None,
             row["sessions"], row["students"],
             *(row[status] for status in ATTENDANCE_STATUSES), _rate(row))
            for row in ordered)
        columns = (ReportColumn(t["reports.col.group"]), ReportColumn(t["reports.col.teacher"]),
                   ReportColumn(t["reports.col.sessions"], "number"),
                   ReportColumn(t["reports.col.students"], "number")) + marks
        total = None
        if rows:
            total = (t["reports.total"], None, held, None,
                     *(counts[status] for status in ATTENDANCE_STATUSES), overall)
        return Report(key="presences-par-groupe", title=t["reports.attendance_group.title"],
                      columns=columns, rows=rows, total=total,
                      row_ids=tuple(row["group_id"] for row in ordered), opens="groups",
                      tones=tuple(_tone(row[-1]) for row in rows), **common)
    lines = repo.attendance_by_student(conn, dates.iso(first), dates.iso(last), group_id)
    ordered = sorted(lines, key=lambda row: (
        _rate(row) if _rate(row) is not None else 10001,
        fold(f"{row['last_name']} {row['first_name']}"), title_of.get(row["group_id"], "")))
    rows = tuple(
        (f"{row['last_name']} {row['first_name']}", row["student_number"],
         title_of.get(row["group_id"], "—"),
         *(row[status] for status in ATTENDANCE_STATUSES), _rate(row))
        for row in ordered)
    columns = (ReportColumn(t["reports.col.student"]), ReportColumn(t["reports.col.number"]),
               ReportColumn(t["reports.col.group"])) + marks
    total = None
    if rows:
        total = (t["reports.students_count"].format(
                     count=len({row["student_id"] for row in ordered})), None, None,
                 *(counts[status] for status in ATTENDANCE_STATUSES), overall)
    return Report(key="presences-par-eleve", title=t["reports.attendance_student.title"],
                  columns=columns, rows=rows, total=total,
                  row_ids=tuple(row["student_id"] for row in ordered), opens="students",
                  tones=tuple(_tone(row[-1]) for row in rows), **common)


# ----- Enseignants -----

def teacher_summary(conn, ctx: UserContext, year_id: int) -> Report:
    """Per teacher: groups and students now; the year's months of their groups (revenue,
    their share); paid during the year, waiting (drafts and approved payouts), and what a
    draft built today would add."""
    require(ctx, "report.finance")
    require(ctx, "payout.view")
    year = _year(conn, year_id)
    today = dates.today()
    held: dict[int, list[int]] = {}
    for g in groups.search(conn, ctx, year_id=year_id):
        if g.state != "closed" and g.teacher_id is not None:
            line = held.setdefault(g.teacher_id, [0, 0])
            line[0] += 1
            line[1] += g.enrolled
    _months, charges, _collected = _year_charges(conn, year)
    revenue_of: dict[int, int] = {}
    for c in charges:
        if c["teacher_id"] is not None:
            revenue_of[c["teacher_id"]] = revenue_of.get(c["teacher_id"], 0) + c["amount"]
    share_of: dict[int, int] = {}
    for (_month, _group, teacher_id), value in _shares(charges).items():
        share_of[teacher_id] = share_of.get(teacher_id, 0) + value
    paid_rows = {row["teacher_id"]: row
                 for row in repo.payouts_by_teacher(conn, year["start_date"], year["end_date"])}
    prepare = payouts.not_prepared(conn, today)
    rows, ids = [], []
    active = 0
    for teacher in teachers.search(conn, ctx, status=None):
        groups_count, students = held.get(teacher.id, [0, 0])
        row = paid_rows.get(teacher.id)
        paid = row["paid"] if row else 0
        waiting = row["waiting"] if row else 0
        to_prepare = prepare.get(teacher.id, (0, 0))[1]
        income = revenue_of.get(teacher.id, 0)
        if teacher.status == "active":
            active += 1
        elif not (groups_count or income or paid or waiting or to_prepare):
            continue
        rows.append((teacher.full_name, groups_count, students, teacher.current_rate_bp,
                     income, share_of.get(teacher.id, 0), paid, waiting, to_prepare))
        ids.append(teacher.id)
    order = sorted(range(len(rows)), key=lambda i: rows[i][0].casefold())
    rows, ids = [rows[i] for i in order], [ids[i] for i in order]
    columns = (ReportColumn(t["reports.col.teacher"]),
               ReportColumn(t["reports.col.groups"], "number"),
               ReportColumn(t["reports.col.students"], "number"),
               ReportColumn(t["reports.col.rate"], "percent"))
    columns += _money("revenue", "share_due", "paid", "waiting", "to_prepare")
    paid = sum(row[6] for row in rows)
    waiting = sum(row[7] for row in rows)
    to_prepare = sum(row[8] for row in rows)
    tiles = (
        ReportTile(t["reports.tile.teachers"], active, "number",
                   t["reports.tile.teachers_note"].format(count=len(rows))),
        ReportTile(t["reports.tile.groups"], sum(row[1] for row in rows), "number",
                   t["reports.tile.groups_note"].format(students=sum(row[2] for row in rows))),
        ReportTile(t["reports.tile.paid"], paid, note=t["reports.tile.paid_note"].format(
            label=year["label"])),
        ReportTile(t["reports.tile.to_pay"], waiting + to_prepare,
                   note=t["reports.tile.to_pay_note"].format(waiting=_dzd(waiting),
                                                            prepare=_dzd(to_prepare))),
    )
    on = dates.display_date(dates.iso(today))
    return Report(key="enseignants", title=t["reports.teachers.title"],
                  period=t["reports.year_on"].format(label=year["label"], date=on),
                  columns=columns, rows=tuple(rows), total=_total(rows, columns, skip={3}),
                  tiles=tiles, note=t["reports.teachers.note"], row_ids=tuple(ids),
                  opens="teachers")


# ----- Élèves -----

STUDENT_STATUSES = ("active", "inactive", None)


def student_list(conn, ctx: UserContext, status: str | None = "active",
                 level_id: int | None = None, group_id: int | None = None,
                 query: str = "") -> Report:
    """The students the filters match, in name order, with what is late for each (after
    their credit, as the Paiements page shows it)."""
    require(ctx, "student.view")
    if status not in STUDENT_STATUSES:
        raise ValidationError(t["validation.generic"])
    year = years_repo.open_year(conn)
    year_id = None if year is None else year["id"]
    owing = {student_id: d.owed_now for student_id, d in debt.every_debt(conn).items()}
    words = fold(query or "").split()
    rows, ids = [], []
    for row in repo.students(conn, status, year_id, level_id, group_id):
        name = f"{row['last_name']} {row['first_name']}"
        if words:
            haystack = fold(f"{name} {row['student_number']} {row['phone'] or ''}")
            if not all(word in haystack for word in words):
                continue
        rows.append((row["student_number"], name, row["level"], row["groups"], row["contact"],
                     format_phone(row["phone"]) if row["phone"] else None,
                     row["registered_at"][:10] if row["registered_at"] else None,
                     owing.get(row["id"], 0)))
        ids.append(row["id"])
    counts = repo.student_counts(conn, year_id, dates.iso(dates.today()))
    tiles = (
        ReportTile(t["reports.tile.active"], counts["active"], "number",
                   t["reports.tile.active_note"]),
        ReportTile(t["reports.tile.registered"], counts["registered"], "number",
                   t["reports.tile.registered_note"].format(
                       label=year["label"] if year else "—")),
        ReportTile(t["reports.tile.trial"], counts["trial"], "number",
                   t["reports.tile.trial_note"]),
        ReportTile(t["reports.tile.no_month"], counts["no_month"], "number",
                   t["reports.tile.no_month_note"]),
    )
    columns = (ReportColumn(t["reports.col.number"]), ReportColumn(t["reports.col.student"]),
               ReportColumn(t["reports.col.level"]), ReportColumn(t["reports.col.groups_now"]),
               ReportColumn(t["reports.col.contact"]), ReportColumn(t["reports.col.phone"]),
               ReportColumn(t["reports.col.registered"], "date"),
               ReportColumn(t["reports.col.overdue"], "money"))
    total = None
    if rows:
        total = (t["reports.students_count"].format(count=len(rows)),) + (None,) * 6 + (
            sum(row[7] for row in rows),)
    filters = ((t["reports.filter.status"], t[f"reports.status.{status or 'all'}"]),)
    if level_id is not None:
        names = {item.id: item.name for item in catalog.list_items(conn, ctx, "level")}
        filters += ((t["reports.filter.level"], names.get(level_id, "—")),)
    if group_id is not None:
        group = _groups(conn, ctx).get(group_id)
        filters += ((t["reports.filter.group"], group.title if group else "—"),)
    if query.strip():
        filters += ((t["reports.filter.search"], query.strip()),)
    on = dates.display_date(dates.iso(dates.today()))
    return Report(key="liste-eleves", title=t["reports.students.title"],
                  period=t["reports.on"].format(date=on), columns=columns, rows=tuple(rows),
                  total=total, tiles=tiles, filters=filters, note=t["reports.students.note"],
                  row_ids=tuple(ids), opens="students")


# ----- exports -----

FORMATS = {"pdf": ".pdf", "xlsx": ".xlsx"}


def export(conn, ctx: UserContext, report: Report, fmt: str, path: Path | None = None) -> Path:
    """The report as shown, in a PDF or an Excel file: in the documents folder, named after
    it and the moment (cleaned after REPORT_DAYS), or at `path` (« Enregistrer sous… », never
    cleaned). Written to the audit log."""
    require(ctx, "report.view")
    if fmt not in FORMATS:
        raise ValidationError(t["validation.generic"])
    if path is None:
        path = config.documents_dir() / (
            f"rapport_{report.key}_{datetime.now():%Y-%m-%d_%H%M%S}{FORMATS[fmt]}")
    school = printing.school_of(conn)
    footer = printing.footer_for(ctx)
    if fmt == "pdf":
        build_report_pdf(report, school, footer, path)
    else:
        build_report_xlsx(report, school.name, footer.printed, path)
    with atomic(conn):
        audit.log(conn, ctx, "report.export", "reports", None,
                  new={"report": report.title, "format": t[f"reports.format.{fmt}"],
                       "rows": len(report.rows)})
    return path
