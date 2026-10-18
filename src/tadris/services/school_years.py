from datetime import date

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError, NotFound, ValidationError
from tadris.core.permissions import require
from tadris.core.text import clean
from tadris.db.errors import atomic
from tadris.domain.models import SchoolYear
from tadris.i18n.fr import t
from tadris.repositories import school_years as repo
from tadris.services import audit

# Rule: at most one open year (also a unique index). A year created while another is open
# starts closed and shows as "à venir" until it is first opened (opened_on), even once its
# start date has passed; groups and timetable slots can be prepared in it, registrations and
# enrollments happen only in the open year. A finished year (end date passed) cannot be
# opened again; a year closed by mistake before its end can.


def state_of(row, today: date | None = None) -> str:
    today_iso = dates.iso(today or dates.today())
    if row["status"] == "open":
        return "open"
    if row["opened_on"] is None and row["end_date"] >= today_iso:
        return "upcoming"
    return "closed"


def can_open(year: SchoolYear, today: date | None = None) -> bool:
    return year.status != "open" and year.end_date >= dates.iso(today or dates.today())


def _to_year(row) -> SchoolYear:
    return SchoolYear(
        id=row["id"], label=row["label"], start_date=row["start_date"],
        end_date=row["end_date"], status=row["status"], state=state_of(row),
        group_count=row["group_count"],
    )


def suggest_label(start: date) -> str:
    return f"{start.year}-{start.year + 1}"


def _require_row(conn, year_id: int):
    row = repo.get(conn, year_id)
    if row is None:
        raise NotFound(t["year.not_found"])
    return row


def list_years(conn, ctx: UserContext) -> list[SchoolYear]:
    require(ctx, "academic.view")
    return [_to_year(row) for row in repo.list_all(conn)]


def get(conn, ctx: UserContext, year_id: int) -> SchoolYear:
    require(ctx, "academic.view")
    return _to_year(_require_row(conn, year_id))


def current(conn, ctx: UserContext) -> SchoolYear | None:
    """The open year, if any."""
    require(ctx, "academic.view")
    row = repo.open_year(conn)
    return None if row is None else _to_year(row)


def usable(conn, ctx: UserContext) -> list[SchoolYear]:
    """Years that can receive groups: the open one and the upcoming ones."""
    return [y for y in list_years(conn, ctx) if y.state in ("open", "upcoming")]


def require_usable(conn, year_id: int):
    """Inside a transaction: the year row, if groups may be added to it."""
    row = _require_row(conn, year_id)
    if state_of(row) == "closed":
        raise BusinessRuleError(t["year.not_usable"])
    return row


def _validate(conn, label: str, start: date, end: date, exclude_id: int | None) -> str:
    label = clean(label)
    if not label:
        raise ValidationError(t["year.label_required"])
    if end <= start:
        raise ValidationError(t["year.dates_order"])
    if repo.label_taken(conn, label, exclude_id):
        raise ValidationError(t["year.label_taken"])
    other = repo.overlapping(conn, dates.iso(start), dates.iso(end), exclude_id)
    if other is not None:
        raise ValidationError(t["year.overlap"].format(label=other["label"]))
    return label


def create(conn, ctx: UserContext, label: str, start: date, end: date) -> int:
    """The first year opens; while another is open, a new year waits as upcoming."""
    require(ctx, "academic.manage")
    with atomic(conn):
        label = _validate(conn, label, start, end, None)
        status = "closed" if repo.open_year(conn) is not None else "open"
        opened_on = dates.iso(dates.today()) if status == "open" else None
        year_id = repo.insert(conn, label, dates.iso(start), dates.iso(end), status, opened_on)
        audit.log(conn, ctx, "school_year.create", "school_years", year_id, new={
            "label": label, "start_date": start, "end_date": end, "status": status,
        })
        return year_id


def update(conn, ctx: UserContext, year_id: int, label: str, start: date, end: date) -> None:
    require(ctx, "academic.manage")
    with atomic(conn):
        row = _require_row(conn, year_id)
        label = _validate(conn, label, start, end, year_id)
        if repo.groups_outside(conn, year_id, dates.iso(start), dates.iso(end)):
            raise BusinessRuleError(t["year.groups_outside"])
        repo.update(conn, year_id, label, dates.iso(start), dates.iso(end))
        audit.log(conn, ctx, "school_year.update", "school_years", year_id,
                  old={k: row[k] for k in ("label", "start_date", "end_date")},
                  new={"label": label, "start_date": start, "end_date": end})


def open_year(conn, ctx: UserContext, year_id: int) -> None:
    require(ctx, "academic.manage")
    with atomic(conn):
        row = _require_row(conn, year_id)
        if row["status"] == "open":
            raise BusinessRuleError(t["year.already_open"])
        today = dates.iso(dates.today())
        if row["end_date"] < today:
            raise BusinessRuleError(t["year.ended"])
        other = repo.open_year(conn)
        if other is not None:
            raise BusinessRuleError(t["year.other_open"].format(label=other["label"]))
        repo.set_status(conn, year_id, "open")
        repo.mark_opened(conn, year_id, today)
        audit.log(conn, ctx, "school_year.open", "school_years", year_id,
                  old={"status": "closed"}, new={"status": "open"})


def close(conn, ctx: UserContext, year_id: int) -> int:
    """Close the year and its groups (their timetable slots end today). Returns the number
    of groups closed."""
    from tadris.services import groups  # groups depends on this module

    require(ctx, "academic.manage")
    with atomic(conn):
        row = _require_row(conn, year_id)
        if row["status"] != "open":
            raise BusinessRuleError(t["year.not_open"])
        closed = repo.close_groups(conn, year_id)
        for group_id in closed:
            groups.release_slots(conn, ctx, group_id)
        repo.set_status(conn, year_id, "closed")
        audit.log(conn, ctx, "school_year.close", "school_years", year_id,
                  old={"status": "open"}, new={"status": "closed", "groups_closed": closed})
        return len(closed)
