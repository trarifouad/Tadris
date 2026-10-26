from datetime import date

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError, NotFound, ValidationError
from tadris.core.permissions import allowed, require
from tadris.core.phones import normalize_phone
from tadris.core.text import clean, fold
from tadris.db.errors import atomic
from tadris.domain.models import RatePeriod, Teacher, TeacherInput
from tadris.i18n.fr import t
from tadris.repositories import teachers as repo
from tadris.repositories.students import like_pattern
from tadris.services import audit, payouts

# Rates are one percentage per teacher, stored in basis points, in half-open periods
# [valid_from, valid_to) with no gap and no overlap: a new rate closes the current one on
# its start date. A new rate on the current rate's own start date corrects it instead,
# unless a validated payout already used it. The first rate may start earlier (it was set to
# start too late), never before the arrival date. A rate change that touches months a draft
# payout counts builds that draft again; approved and paid payouts never change. A teacher is
# put on a group only from a day they have a rate (require_rate_on): each month of a group
# is paid at its teacher's rate on its first day.

STATUSES = ("active", "inactive")


def _to_teacher(ctx: UserContext, row) -> Teacher:
    sees_rates = allowed(ctx, "teacher.manage")
    return Teacher(
        id=row["id"], full_name=row["full_name"], phone=row["phone"], status=row["status"],
        hire_date=row["hire_date"],
        current_rate_bp=row["current_rate_bp"] if sees_rates else None,
        group_count=row["group_count"],
        current_rate_from=row["current_rate_from"] if sees_rates else None,
    )


def _today() -> str:
    return dates.iso(dates.today())


def _require_row(conn, teacher_id: int):
    row = repo.get(conn, teacher_id, _today())
    if row is None:
        raise NotFound(t["teacher.not_found"])
    return row


def require_active(conn, teacher_id: int):
    row = _require_row(conn, teacher_id)
    if row["status"] != "active":
        raise ValidationError(t["teacher.inactive"])
    return row


def _clean(data: TeacherInput) -> tuple[str, str | None, str | None]:
    name = clean(data.full_name)
    if not name:
        raise ValidationError(t["teacher.name_required"])
    hire = None if data.hire_date is None else dates.iso(data.hire_date)
    return name, normalize_phone(data.phone), hire


def get(conn, ctx: UserContext, teacher_id: int) -> Teacher:
    require(ctx, "teacher.view")
    return _to_teacher(ctx, _require_row(conn, teacher_id))


def search(conn, ctx: UserContext, query: str = "",
           status: str | None = "active") -> list[Teacher]:
    require(ctx, "teacher.view")
    if status is not None and status not in STATUSES:
        raise ValidationError(t["validation.generic"])
    terms = [like_pattern(fold(word)) for word in clean(query).split()]
    return [_to_teacher(ctx, row) for row in repo.search(conn, terms, status, _today())]


def create(conn, ctx: UserContext, data: TeacherInput, rate_bp: int,
           rate_from: date | None = None) -> int:
    """A teacher always starts with a rate, from rate_from (default: hire date, else today)."""
    require(ctx, "teacher.manage")
    name, phone, hire = _clean(data)
    _check_bp(rate_bp)
    start = rate_from or data.hire_date or dates.today()
    with atomic(conn):
        teacher_id = repo.insert(conn, name, phone, hire)
        repo.insert_rate(conn, teacher_id, rate_bp, dates.iso(start))
        _check_rate_after_hire(conn, teacher_id, hire)
        audit.log(conn, ctx, "teacher.create", "teachers", teacher_id, new={
            "full_name": name, "phone": phone, "hire_date": hire,
            "percentage_bp": rate_bp, "rate_from": start,
        })
        return teacher_id


def _check_rate_after_hire(conn, teacher_id: int, hire: str | None) -> None:
    """The first rate never starts before the arrival date."""
    first = repo.first_rate_from(conn, teacher_id)
    if hire is not None and first is not None and first < hire:
        raise ValidationError(t["rate.before_hire"].format(date=dates.display_date(hire)))


def update(conn, ctx: UserContext, teacher_id: int, data: TeacherInput,
           rate_bp: int | None = None, rate_from: date | None = None) -> None:
    """Name, phone, arrival date and, with rate_bp, a rate from rate_from (default today; an
    earlier date than the current rate's moves the first rate's start): all saved, or
    none."""
    require(ctx, "teacher.manage")
    name, phone, hire = _clean(data)
    if rate_bp is not None:
        _check_bp(rate_bp)
    with atomic(conn):
        row = _require_row(conn, teacher_id)
        old = {"full_name": row["full_name"], "phone": row["phone"], "hire_date": row["hire_date"]}
        new = {"full_name": name, "phone": phone, "hire_date": hire}
        if old != new:
            repo.update(conn, teacher_id, name, phone, hire)
            changed = [key for key in new if old[key] != new[key]]
            audit.log(conn, ctx, "teacher.update", "teachers", teacher_id,
                      old={k: old[k] for k in changed}, new={k: new[k] for k in changed})
        if rate_bp is not None:
            _apply_rate(conn, ctx, teacher_id, rate_bp,
                        dates.iso(rate_from or dates.today()))
        if old["hire_date"] != hire:
            _check_rate_after_hire(conn, teacher_id, hire)


def deactivate(conn, ctx: UserContext, teacher_id: int) -> None:
    require(ctx, "teacher.manage")
    with atomic(conn):
        row = _require_row(conn, teacher_id)
        if row["status"] == "inactive":
            raise BusinessRuleError(t["teacher.already_inactive"])
        if repo.assigned_group_count(conn, teacher_id, _today()):
            raise BusinessRuleError(t["teacher.has_groups"])
        repo.set_status(conn, teacher_id, "inactive")
        audit.log(conn, ctx, "teacher.deactivate", "teachers", teacher_id,
                  old={"status": "active"}, new={"status": "inactive"})


def reactivate(conn, ctx: UserContext, teacher_id: int) -> None:
    require(ctx, "teacher.manage")
    with atomic(conn):
        row = _require_row(conn, teacher_id)
        if row["status"] == "active":
            raise BusinessRuleError(t["teacher.already_active"])
        repo.set_status(conn, teacher_id, "active")
        audit.log(conn, ctx, "teacher.reactivate", "teachers", teacher_id,
                  old={"status": "inactive"}, new={"status": "active"})


# ----- rates -----

def _check_bp(bp: int) -> None:
    if not 0 <= bp <= 10000:
        raise ValidationError(t["percent.invalid"])


def rates(conn, ctx: UserContext, teacher_id: int) -> list[RatePeriod]:
    """Rate history, newest first. Director only: rates are pay."""
    require(ctx, "teacher.manage")
    _require_row(conn, teacher_id)
    return [
        RatePeriod(id=r["id"], percentage_bp=r["percentage_bp"], valid_from=r["valid_from"],
                   valid_to=r["valid_to"])
        for r in repo.rates(conn, teacher_id)
    ]


def set_rate(conn, ctx: UserContext, teacher_id: int, bp: int, valid_from: date) -> None:
    require(ctx, "teacher.manage")
    _check_bp(bp)
    with atomic(conn):
        _require_row(conn, teacher_id)
        _apply_rate(conn, ctx, teacher_id, bp, dates.iso(valid_from))


def _apply_rate(conn, ctx: UserContext, teacher_id: int, bp: int, start: str) -> None:
    """Inside the caller's transaction: the running rate stops the day before `start`; on
    its own start day it is corrected, and before it the first rate starts earlier (see
    _start_earlier). Never before the arrival date. The teacher's draft payout is built again
    when it counts a month from `start` on."""
    current = repo.open_rate(conn, teacher_id)
    if current is not None and current["percentage_bp"] == bp \
            and start >= current["valid_from"]:
        return  # same rate already running
    hire = _require_row(conn, teacher_id)["hire_date"]
    if hire is not None and start < hire:
        raise ValidationError(t["rate.before_hire"].format(date=dates.display_date(hire)))
    if current is None:
        repo.insert_rate(conn, teacher_id, bp, start)
        audit.log(conn, ctx, "teacher.rate", "teachers", teacher_id,
                  new={"percentage_bp": bp, "valid_from": start})
    elif start < current["valid_from"]:
        _start_earlier(conn, ctx, teacher_id, current, bp, start)
    elif start == current["valid_from"]:
        if repo.has_locked_payout_since(conn, teacher_id, start):
            raise BusinessRuleError(t["rate.locked"])
        repo.correct_rate(conn, current["id"], bp)
        audit.log(conn, ctx, "teacher.rate_correct", "teachers", teacher_id,
                  old={"percentage_bp": current["percentage_bp"], "valid_from": start},
                  new={"percentage_bp": bp, "valid_from": start})
    else:
        repo.close_rate(conn, current["id"], start)
        repo.insert_rate(conn, teacher_id, bp, start)
        audit.log(conn, ctx, "teacher.rate", "teachers", teacher_id,
                  old={"percentage_bp": current["percentage_bp"],
                       "valid_from": current["valid_from"]},
                  new={"percentage_bp": bp, "valid_from": start})
    payouts.refresh_draft(conn, ctx, teacher_id, start)


def _start_earlier(conn, ctx: UserContext, teacher_id: int, current, bp: int,
                   start: str) -> None:
    """The first rate was set to start too late: it starts on `start` instead, at `bp`.
    Refused when an older rate exists (the history stays as it is) and, for another
    percentage, once an approved or paid payout used the rate. With the same percentage
    nothing paid changes: a month before the old start could not be paid without a rate."""
    if repo.first_rate_from(conn, teacher_id) < current["valid_from"]:
        raise ValidationError(t["rate.before_current"].format(
            date=dates.display_date(current["valid_from"])))
    if bp != current["percentage_bp"] and repo.has_locked_payout_since(conn, teacher_id, start):
        raise BusinessRuleError(t["rate.locked"])
    repo.move_rate_start(conn, current["id"], start)
    if bp != current["percentage_bp"]:
        repo.correct_rate(conn, current["id"], bp)
    audit.log(conn, ctx, "teacher.rate_correct", "teachers", teacher_id,
              old={"percentage_bp": current["percentage_bp"],
                   "valid_from": current["valid_from"]},
              new={"percentage_bp": bp, "valid_from": start})


def require_rate_on(conn, teacher_id: int, on: str) -> None:
    """A teacher is put on a group only from a day they have a rate: each month of the
    group is paid at its teacher's rate on its first day."""
    if repo.rate_on(conn, teacher_id, on) is None:
        row = _require_row(conn, teacher_id)
        raise BusinessRuleError(t["group.teacher_no_rate"].format(
            teacher=row["full_name"], date=dates.display_date(on)))


def rate_on(conn, teacher_id: int, on: date) -> int | None:
    """The rate snapshot for a day (used by payouts)."""
    return repo.rate_on(conn, teacher_id, dates.iso(on))
