from datetime import date, timedelta

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import NotFound, ValidationError
from tadris.core.permissions import require
from tadris.core.text import clean
from tadris.db.errors import atomic
from tadris.domain.models import Holiday
from tadris.i18n.fr import t
from tadris.repositories import holidays as repo
from tadris.services import audit, sessions

# Holidays are periods without classes, both days included; a single day off has the same
# start and end. The director keeps them in Paramètres. Periods never overlap (service rule
# with a readable message, and a trigger). No session is generated on a holiday: adding one
# discards the pending sessions of its days, removing one generates them again.


def _to_holiday(row) -> Holiday:
    return Holiday(id=row["id"], label=row["label"], start_date=row["start_date"],
                   end_date=row["end_date"])


def _require_row(conn, holiday_id: int):
    row = repo.get(conn, holiday_id)
    if row is None:
        raise NotFound(t["holiday.not_found"])
    return row


def list_holidays(conn, ctx: UserContext) -> list[Holiday]:
    """Latest first."""
    require(ctx, "academic.view")
    return [_to_holiday(row) for row in repo.list_all(conn)]


def days_off(conn, first: date, last: date) -> dict[str, str]:
    """{'YYYY-MM-DD': label} for every holiday day in [first, last]."""
    off = {}
    for row in repo.between(conn, dates.iso(first), dates.iso(last)):
        day = max(date.fromisoformat(row["start_date"]), first)
        end = min(date.fromisoformat(row["end_date"]), last)
        while day <= end:
            off[dates.iso(day)] = row["label"]
            day += timedelta(days=1)
    return off


def _validate(conn, label: str, start: date, end: date, exclude_id: int | None) -> str:
    label = clean(label)
    if not label:
        raise ValidationError(t["holiday.label_required"])
    if end < start:
        raise ValidationError(t["holiday.dates_order"])
    other = repo.overlapping(conn, dates.iso(start), dates.iso(end), exclude_id)
    if other is not None:
        raise ValidationError(t["holiday.overlap"].format(
            label=other["label"], start=dates.display_date(other["start_date"]),
            end=dates.display_date(other["end_date"])))
    return label


def create(conn, ctx: UserContext, label: str, start: date, end: date | None = None) -> int:
    """end None: a single day off."""
    require(ctx, "academic.manage")
    end = end or start
    with atomic(conn):
        label = _validate(conn, label, start, end, None)
        holiday_id = repo.insert(conn, label, dates.iso(start), dates.iso(end))
        audit.log(conn, ctx, "holiday.create", "holidays", holiday_id,
                  new={"label": label, "start_date": start, "end_date": end})
        sessions.discard_for_days(conn, start, end)
        return holiday_id


def update(conn, ctx: UserContext, holiday_id: int, label: str, start: date,
           end: date | None = None) -> None:
    require(ctx, "academic.manage")
    end = end or start
    with atomic(conn):
        row = _require_row(conn, holiday_id)
        label = _validate(conn, label, start, end, holiday_id)
        old = {k: row[k] for k in ("label", "start_date", "end_date")}
        new = {"label": label, "start_date": dates.iso(start), "end_date": dates.iso(end)}
        if old == new:
            return
        repo.update(conn, holiday_id, label, new["start_date"], new["end_date"])
        audit.log(conn, ctx, "holiday.update", "holidays", holiday_id, old=old, new=new)
        sessions.discard_for_days(conn, start, end)
        sessions.generate_in(conn)  # the days no longer off get their sessions


def remove(conn, ctx: UserContext, holiday_id: int) -> None:
    """A holiday entered by mistake is removed (audited)."""
    require(ctx, "academic.manage")
    with atomic(conn):
        row = _require_row(conn, holiday_id)
        repo.delete(conn, holiday_id)
        audit.log(conn, ctx, "holiday.remove", "holidays", holiday_id,
                  old={k: row[k] for k in ("label", "start_date", "end_date")})
        sessions.generate_in(conn)
