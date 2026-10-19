from datetime import date

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import NotFound
from tadris.core.money import format_dzd
from tadris.core.permissions import require
from tadris.domain.models import ChargeDue, Debt, Debtor
from tadris.i18n.fr import t
from tadris.repositories import payments as repo
from tadris.repositories import students as students_repo
from tadris.services import settings

# Debt is derived, never stored: open charges, minus what payments not voided allocated to
# them, minus adjustments; money received and not allocated yet is the student's credit.
# Cancelling a charge is refused once something was paid on it, so allocations of valid
# payments only sit on open charges. A charge is late from its due date (a month from its
# first day, the fee from the registration day); months renewed ahead are owed, not late.


def _today() -> str:
    return dates.iso(dates.today())


def to_charge(row) -> ChargeDue:
    return ChargeDue(
        id=row["id"], kind="registration" if row["registration_id"] is not None
        else "subscription", description=row["description"], amount=row["amount"],
        due_date=row["due_date"], paid=row["paid"], adjusted=row["adjusted"],
        group_id=row["group_id"],
    )


def _build(student_id: int, charge_rows, credit_rows, adjustment: int, on: str) -> Debt:
    charges = tuple(c for c in (to_charge(row) for row in charge_rows) if c.due > 0)
    credit = sum(row["amount"] - row["allocated"] for row in credit_rows)
    return Debt(student_id=student_id, as_of=on, charges=charges, credit=credit,
                adjustments=adjustment)


def compute(conn, student_id: int) -> Debt:
    """The debt, without a permission check: for services, inside their transaction."""
    adjustments = repo.unlinked_adjustments(conn, student_id)
    return _build(student_id, repo.open_charges(conn, student_id),
                  repo.with_credit(conn, student_id),
                  adjustments[0]["total"] if adjustments else 0, _today())


def for_student(conn, ctx: UserContext, student_id: int) -> Debt:
    require(ctx, "student.view")
    if students_repo.get(conn, student_id) is None:
        raise NotFound(t["student.not_found"])
    return compute(conn, student_id)


def debtors(conn, ctx: UserContext, group_id: int | None = None, min_amount: int = 0,
            min_days: int = 0) -> list[Debtor]:
    """Students with something late after their credit, the largest first. group_id keeps
    the students in that group now (trial or active); min_amount and min_days keep those
    owing at least that much, or late by at least that many days."""
    require(ctx, "payment.record")
    on = _today()
    charges: dict[int, list] = {}
    for row in repo.open_charges(conn):
        charges.setdefault(row["student_id"], []).append(row)
    credits: dict[int, list] = {}
    for row in repo.with_credit(conn):
        credits.setdefault(row["student_id"], []).append(row)
    adjustments = {row["student_id"]: row["total"] for row in repo.unlinked_adjustments(conn)}
    in_group = None
    if group_id is not None:
        in_group = {row["student_id"] for row in repo.live_groups(conn)
                    if row["group_id"] == group_id}

    owing: dict[int, Debt] = {}
    for student_id, rows in charges.items():
        if in_group is not None and student_id not in in_group:
            continue
        debt = _build(student_id, rows, credits.get(student_id, []),
                      adjustments.get(student_id, 0), on)
        if debt.owed_now <= 0 or debt.owed_now < min_amount:
            continue
        if _days_late(debt, on) < min_days:
            continue
        owing[student_id] = debt

    result = []
    for student in repo.students(conn, list(owing)):
        debt = owing[student["id"]]
        result.append(Debtor(
            student_id=student["id"], student_number=student["student_number"],
            student_name=f"{student['last_name']} {student['first_name']}",
            owed_now=debt.owed_now, due=debt.due, credit=debt.credit,
            oldest_overdue=debt.oldest_overdue, days_overdue=_days_late(debt, on)))
    result.sort(key=lambda d: (-d.owed_now, d.student_name.casefold()))
    return result


def _days_late(debt: Debt, on: str) -> int:
    if debt.oldest_overdue is None:
        return 0
    return (date.fromisoformat(on) - date.fromisoformat(debt.oldest_overdue)).days


def warning_threshold(conn) -> int:
    """defaults.max_debt_warning; 0 (the default) turns the warning off."""
    return settings.get(conn, "defaults.max_debt_warning", 0)


def warning(conn, ctx: UserContext, student_id: int) -> str | None:
    """A warning for the enrollment and renewal dialogs when what the student owes now
    reaches the threshold. It never blocks: the desk decides."""
    threshold = warning_threshold(conn)
    if threshold <= 0:
        return None
    debt = for_student(conn, ctx, student_id)
    if debt.owed_now < threshold:
        return None
    return t["debt.warning"].format(amount=format_dzd(debt.owed_now),
                                    threshold=format_dzd(threshold))
