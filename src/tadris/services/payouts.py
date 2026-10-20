import calendar
from datetime import date, datetime

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError, NotFound, ValidationError
from tadris.core.money import format_dzd
from tadris.core.percent import apply_rate
from tadris.core.permissions import require
from tadris.db.errors import atomic
from tadris.domain.models import (
    PAYMENT_METHODS,
    Payout,
    PayoutDue,
    PayoutLine,
    PayoutMonth,
)
from tadris.i18n.fr import t
from tadris.repositories import payouts as repo
from tadris.repositories import teachers as teachers_repo
from tadris.services import audit, counters

# A teacher is paid a percentage of the full price of each month (subscription charge) of
# the groups they taught on the month's first day, whether the student paid or not (section
# 1 of the plan; there are no discounts). A payout takes every month not paid to the
# teacher yet up to a date: a month renewed late, starting in a period already paid, goes
# into the next payout instead of being lost. One line per group and rate, each at the
# teacher's rate on the months' first day (snapshot), its share rounded down once.
#
# Director only. A draft can be built again (it is replaced) or deleted until approved;
# approved, it is locked (triggers); paid, it gets a number 'PE2026-00001' and its method.

STATUSES_OPEN = ("draft", "approved")


def _now() -> str:
    return f"{dates.iso(dates.today())}T{datetime.now():%H:%M:%S}"


def month_end(on: date) -> date:
    return on.replace(day=calendar.monthrange(on.year, on.month)[1])


def _to_payout(row) -> Payout:
    return Payout(
        id=row["id"], teacher_id=row["teacher_id"], teacher=row["teacher"],
        period_start=row["period_start"], period_end=row["period_end"],
        base_amount=row["base_amount"], amount_due=row["amount_due"],
        amount_paid=row["amount_paid"], receipt_number=row["receipt_number"],
        status=row["status"], approved_by=row["approved_by"], approved_at=row["approved_at"],
        method=row["method"], paid_by=row["paid_by"], paid_at=row["paid_at"],
        created_at=row["created_at"], months=row["months"],
    )


def _title(row) -> str:
    return f"{row['group_name']} · {row['subject']} {row['level']}"


def _require_row(conn, payout_id: int):
    row = repo.get(conn, payout_id)
    if row is None:
        raise NotFound(t["payout.not_found"])
    return row


# ----- reading -----

def get(conn, ctx: UserContext, payout_id: int) -> Payout:
    require(ctx, "payout.view")
    return _to_payout(_require_row(conn, payout_id))


def listing(conn, ctx: UserContext, statuses: tuple[str, ...] = STATUSES_OPEN,
            teacher_id: int | None = None) -> list[Payout]:
    """Latest period first."""
    require(ctx, "payout.view")
    return [_to_payout(row) for row in repo.listing(conn, statuses, teacher_id)]


def lines(conn, ctx: UserContext, payout_id: int) -> list[PayoutLine]:
    require(ctx, "payout.view")
    _require_row(conn, payout_id)
    return [PayoutLine(id=row["id"], group_id=row["group_id"], group_title=_title(row),
                       revenue_basis=row["revenue_basis"], percentage_bp=row["percentage_bp"],
                       amount=row["amount"], months=row["months"], students=row["students"])
            for row in repo.lines(conn, payout_id)]


def months(conn, ctx: UserContext, payout_id: int) -> list[PayoutMonth]:
    """Every month the payout counts, by group then student."""
    require(ctx, "payout.view")
    _require_row(conn, payout_id)
    return [PayoutMonth(charge_id=row["charge_id"], student_number=row["student_number"],
                        student_name=f"{row['last_name']} {row['first_name']}",
                        group_title=_title(row), description=row["description"],
                        accrual_date=row["accrual_date"], amount=row["amount"],
                        percentage_bp=row["percentage_bp"])
            for row in repo.months(conn, payout_id)]


def due(conn, ctx: UserContext, until: date) -> list[PayoutDue]:
    """Per teacher: the months not paid yet up to `until` (not in a draft either)."""
    require(ctx, "payout.view")
    result = []
    for row in repo.owed_teachers(conn, dates.iso(until)):
        teacher = teachers_repo.get(conn, row["teacher_id"], dates.iso(dates.today()))
        draft = repo.draft_of(conn, row["teacher_id"])
        result.append(PayoutDue(teacher_id=row["teacher_id"], teacher=teacher["full_name"],
                                months=row["months"], revenue=row["revenue"],
                                draft_id=None if draft is None else draft["id"]))
    result.sort(key=lambda d: d.teacher.casefold())
    return result


def paid_on(conn, ctx: UserContext, day: date) -> list[Payout]:
    require(ctx, "payout.view")
    return [_to_payout(row) for row in repo.paid_on(conn, dates.iso(day))]


def for_teacher(conn, ctx: UserContext, teacher_id: int) -> list[Payout]:
    """Every payout of the teacher, latest first."""
    return listing(conn, ctx, ("draft", "approved", "paid"), teacher_id)


# ----- building a draft -----

def _check_until(until: date) -> str:
    limit = month_end(dates.today())
    if until > limit:
        raise ValidationError(t["payout.until_too_late"].format(
            date=dates.display_date(dates.iso(limit))))
    return dates.iso(until)


def _by_line(conn, teacher_id: int, owed: list) -> tuple[dict[tuple[int, int], list], object]:
    """The owed months by (group, rate on the month's first day), and the first month
    without a rate (None when every month has one)."""
    by_line: dict[tuple[int, int], list] = {}
    no_rate = None
    for month in owed:
        bp = teachers_repo.rate_on(conn, teacher_id, month["accrual_date"])
        if bp is None:
            no_rate = no_rate or month
            continue
        by_line.setdefault((month["group_id"], bp), []).append(month)
    return by_line, no_rate


def not_prepared(conn, until: date) -> dict[int, tuple[int, int]]:
    """Per teacher: (months, share) owed up to `until` and that no payout holds yet, what
    the next draft would pay. Months without a rate are left out (the draft refuses them).
    One query for every teacher: a month is not looked at one by one."""
    result: dict[int, tuple[int, int]] = {}
    for row in repo.owed_by_rate(conn, dates.iso(until)):
        months, share = result.get(row["teacher_id"], (0, 0))
        result[row["teacher_id"]] = (months + row["months"],
                                     share + apply_rate(row["amount"], row["percentage_bp"]))
    return result


def _build(conn, ctx: UserContext, teacher_id: int, until: str) -> int:
    """Inside a transaction: the teacher's draft up to `until`, replacing theirs."""
    teacher = teachers_repo.get(conn, teacher_id, dates.iso(dates.today()))
    if teacher is None:
        raise NotFound(t["teacher.not_found"])
    replaced = repo.draft_of(conn, teacher_id)
    if replaced is not None:
        repo.delete_draft(conn, replaced["id"])
    owed = repo.owed(conn, teacher_id, until)
    if not owed:
        raise BusinessRuleError(t["payout.nothing"].format(
            teacher=teacher["full_name"], date=dates.display_date(until)))
    by_line, no_rate = _by_line(conn, teacher_id, owed)
    if no_rate is not None:
        raise BusinessRuleError(t["payout.no_rate"].format(
            teacher=teacher["full_name"], date=dates.display_date(no_rate["accrual_date"])))
    shares = {key: apply_rate(sum(m["amount"] for m in group), key[1])
              for key, group in by_line.items()}
    base = sum(m["amount"] for m in owed)
    total = sum(shares.values())
    if total <= 0:
        raise BusinessRuleError(t["payout.zero"].format(teacher=teacher["full_name"]))
    start = owed[0]["accrual_date"]
    clash = repo.same_period(conn, teacher_id, start, until)
    if clash is not None:
        raise BusinessRuleError(t["payout.same_period"].format(
            start=dates.display_date(start), end=dates.display_date(until)))
    payout_id = repo.insert(conn, teacher_id, start, until, base, total, _now())
    for (group_id, bp), group in by_line.items():
        line_id = repo.insert_line(conn, payout_id, group_id,
                                   sum(m["amount"] for m in group), bp, shares[(group_id, bp)])
        for month in group:
            repo.insert_month(conn, line_id, month["charge_id"], month["amount"])
    audit.log(conn, ctx, "payout.build", "teacher_payouts", payout_id, new={
        "teacher_id": teacher_id, "period_start": start, "period_end": until,
        "months": len(owed), "base_amount": base, "amount_due": total,
        "lines": [{"group_id": g, "percentage_bp": bp, "amount": shares[(g, bp)]}
                  for g, bp in by_line],
        "replaced": None if replaced is None else replaced["id"]})
    return payout_id


def build_draft(conn, ctx: UserContext, teacher_id: int, until: date) -> int:
    """The teacher's draft for every month not paid yet up to `until` (at most the end of
    this month). Their previous draft, if any, is replaced."""
    require(ctx, "payout.manage")
    end = _check_until(until)
    with atomic(conn):
        return _build(conn, ctx, teacher_id, end)


def rebuild(conn, ctx: UserContext, payout_id: int) -> int:
    """A draft built again up to the same date: months added or cancelled since count."""
    require(ctx, "payout.manage")
    with atomic(conn):
        row = _require_row(conn, payout_id)
        if row["status"] != "draft":
            raise BusinessRuleError(t["payout.not_draft"])
        return _build(conn, ctx, row["teacher_id"], row["period_end"])


def run(conn, ctx: UserContext, until: date) -> tuple[list[int], list[str]]:
    """The monthly run: a draft for every teacher owed something up to `until`. Each
    teacher in their own transaction; returns (payout ids, messages of those refused)."""
    require(ctx, "payout.manage")
    end = _check_until(until)
    built, refused = [], []
    for row in repo.owed_teachers(conn, end):
        try:
            with atomic(conn):
                built.append(_build(conn, ctx, row["teacher_id"], end))
        except BusinessRuleError as exc:
            refused.append(exc.message)
    return built, refused


def delete_draft(conn, ctx: UserContext, payout_id: int) -> None:
    require(ctx, "payout.manage")
    with atomic(conn):
        row = _require_row(conn, payout_id)
        if row["status"] != "draft":
            raise BusinessRuleError(t["payout.not_draft"])
        repo.delete_draft(conn, payout_id)
        audit.log(conn, ctx, "payout.delete", "teacher_payouts", payout_id,
                  old={"teacher_id": row["teacher_id"], "period_end": row["period_end"],
                       "amount_due": row["amount_due"]})


# ----- approving and paying -----

def stale(conn, ctx: UserContext, payout_id: int) -> int:
    """Months the teacher is owed up to the draft's date and that it does not count yet
    (entered after it was built): 0 when it is up to date."""
    require(ctx, "payout.view")
    row = _require_row(conn, payout_id)
    return len(repo.owed(conn, row["teacher_id"], row["period_end"]))


def approve(conn, ctx: UserContext, payout_id: int) -> None:
    """Locks the payout as it is (build it again first to add months entered since)."""
    require(ctx, "payout.manage")
    with atomic(conn):
        row = _require_row(conn, payout_id)
        if row["status"] != "draft":
            raise BusinessRuleError(t["payout.not_draft"])
        repo.approve(conn, payout_id, ctx.user_id, _now())
        audit.log(conn, ctx, "payout.approve", "teacher_payouts", payout_id,
                  old={"status": "draft"},
                  new={"status": "approved", "amount_due": row["amount_due"]})


def payout_number(conn) -> str:
    """Next 'PE2026-00001'. Call inside the transaction that pays the teacher."""
    year = dates.today().year
    return f"PE{year}-{counters.next_value(conn, f'payout:{year}'):05d}"


def mark_paid(conn, ctx: UserContext, payout_id: int, method: str) -> str:
    """The whole amount handed to the teacher; returns the payout's number."""
    require(ctx, "payout.manage")
    if method not in PAYMENT_METHODS:
        raise ValidationError(t["payment.method_invalid"])
    with atomic(conn):
        row = _require_row(conn, payout_id)
        if row["status"] != "approved":
            raise BusinessRuleError(t["payout.not_approved"])
        number = payout_number(conn)
        repo.mark_paid(conn, payout_id, row["amount_due"], number, method, ctx.user_id, _now())
        audit.log(conn, ctx, "payout.pay", "teacher_payouts", payout_id,
                  old={"status": "approved"},
                  new={"status": "paid", "number": number, "amount": row["amount_due"],
                       "method": method})
        return number


def summary(p: Payout) -> str:
    """'Karim Haddad · 108 000 DA' for confirmations."""
    return f"{p.teacher} · {format_dzd(p.amount_due)}"
