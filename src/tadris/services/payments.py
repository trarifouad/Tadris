from dataclasses import dataclass
from datetime import date, datetime

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError, NotFound, ValidationError
from tadris.core.money import format_dzd
from tadris.core.permissions import allowed, require
from tadris.core.text import clean, group_title
from tadris.db.errors import atomic
from tadris.domain.models import PAYMENT_METHODS, CashReport, ChargeDue, Payment, PaymentLine
from tadris.i18n.fr import t
from tadris.repositories import contacts as contacts_repo
from tadris.repositories import payments as repo
from tadris.repositories import refunds as refunds_repo
from tadris.repositories import students as students_repo
from tadris.services import audit, counters, debt, payouts, refunds, subscriptions

# A payment is money received from (or for) a student. It is immutable: a mistake is undone
# by a void (director only), never by an update or a negative payment. A payment pays lines
# and nothing else: there is no credit (decided 2026-11-05). Recording one, in a single
# transaction: the months ahead the desk added are renewed first (a student still pays
# months in advance: as months, not as credit), then the money pays the student's open
# charges, oldest due first unless the desk chose them, the months ahead always among them.
# It is never more than what is left on those lines; less (a part of a month) leaves the rest
# owed. A receipt number 'R2026-00001' comes from the year's counter in the same
# transaction, so a rolled-back payment leaves no gap.


@dataclass(frozen=True)
class PlannedLine:
    charge: ChargeDue
    from_payment: int  # paid by the new payment
    ahead: bool = False  # a month ahead the payment renews (in a preview: not made yet)

    @property
    def left(self) -> int:
        return self.charge.due - self.from_payment


@dataclass(frozen=True)
class PaymentPlan:
    """What recording a payment would do, before it is recorded."""

    lines: tuple[PlannedLine, ...]  # every charge with something left, the months ahead too
    amount: int

    @property
    def allocated(self) -> int:
        return sum(line.from_payment for line in self.lines)

    @property
    def left_to_pay(self) -> int:
        return sum(line.left for line in self.lines)


def _now() -> str:
    """The service's clock, not SQLite's: the day matches dates.today()."""
    return f"{dates.iso(dates.today())}T{datetime.now():%H:%M:%S}"


def _to_payment(row) -> Payment:
    return Payment(
        id=row["id"], student_id=row["student_id"], student_number=row["student_number"],
        student_name=f"{row['last_name']} {row['first_name']}",
        payer_contact_id=row["payer_contact_id"], payer_name=row["payer_name"],
        amount=row["amount"], method=row["method"], paid_at=row["paid_at"],
        cashier=row["cashier"], receipt_id=row["receipt_id"],
        receipt_number=row["receipt_number"], allocated=row["allocated"],
        voided=bool(row["voided"]), void_reason=row["void_reason"],
        voided_at=row["voided_at"], voided_by=row["voided_by"],
    )


def _require_row(conn, payment_id: int):
    row = repo.get(conn, payment_id)
    if row is None:
        raise NotFound(t["payment.not_found"])
    return row


# ----- reading -----

def get(conn, ctx: UserContext, payment_id: int) -> Payment:
    require(ctx, "student.view")
    return _to_payment(_require_row(conn, payment_id))


def for_student(conn, ctx: UserContext, student_id: int, limit: int | None = None,
                offset: int = 0) -> list[Payment]:
    """Latest first, voided ones included; limit/offset: one page of them."""
    require(ctx, "student.view")
    return [_to_payment(row) for row in repo.for_student(conn, student_id, limit, offset)]


def count_for_student(conn, ctx: UserContext, student_id: int) -> int:
    require(ctx, "student.view")
    return repo.count_for_student(conn, student_id)


def lines(conn, ctx: UserContext, payment_id: int) -> list[PaymentLine]:
    """What the payment paid, charge by charge: what its receipt lists."""
    require(ctx, "student.view")
    _require_row(conn, payment_id)
    return [PaymentLine(charge_id=row["charge_id"], description=row["description"],
                        due_date=row["due_date"], amount=row["amount"],
                        group_title=None if row["group_name"] is None else
                        group_title(row),
                        month_start=row["month_start"], month_end=row["month_end"])
            for row in repo.allocations(conn, payment_id)]


def cash_report(conn, ctx: UserContext, day: date) -> CashReport:
    """The day's payments, the payments of earlier days voided on it (taken off it, never
    off their own day: a day counted stays as it was), the refunds whose money went back that
    day (money going out, apart from the payments) and, for the director (teacher pay is
    theirs to see), the teachers paid that day."""
    require(ctx, "cash.view")
    teachers_paid = (tuple(payouts.paid_on(conn, ctx, day)) if allowed(ctx, "payout.view")
                     else ())
    on = dates.iso(day)
    return CashReport(day=on,
                      payments=tuple(_to_payment(row) for row in repo.on_day(conn, on)),
                      payouts=teachers_paid,
                      voided_earlier=tuple(_to_payment(row) for row in repo.voided_on(conn, on)),
                      refunds=tuple(refunds.paid_on(conn, ctx, day)))


# ----- planning (pure: the dialog's preview and record() use the same code) -----

def plan_payment(charges: list[ChargeDue], amount: int, chosen: list[int] | None = None,
                 ahead: frozenset[int] = frozenset(),
                 ) -> tuple[PaymentPlan, list[tuple[int, int]]]:
    """Plan a payment of `amount` over the open charges, in their order (oldest due first).

    Returns the plan and the allocations (charge id, amount). `chosen`: the charge ids it
    pays instead of all of them. The months ahead (`ahead`: charge ids among `charges`) are
    always paid, and each must get something: a month would otherwise be renewed for
    nothing. The amount is never more than what is left on the lines it pays."""
    if chosen is not None:
        known = {c.id for c in charges if c.id not in ahead}
        if len(set(chosen)) != len(chosen) or not set(chosen) <= known:
            raise ValidationError(t["payment.charge_unknown"])
        if not chosen and not ahead:
            raise ValidationError(t["payment.nothing_chosen"])
    paying = [c for c in charges if chosen is None or c.id in ahead or c.id in chosen]
    room = sum(c.due for c in paying)
    if amount > room:
        raise ValidationError(t["payment.above_due"].format(amount=format_dzd(room)) if room
                              else t["payment.nothing_due"])
    allocations: list[tuple[int, int]] = []
    remaining = amount
    for c in paying:
        take = min(remaining, c.due)
        if take <= 0:
            break
        allocations.append((c.id, take))
        remaining -= take
    paid = dict(allocations)
    if amount and not ahead <= set(paid):
        raise ValidationError(t["payment.ahead_unpaid"])
    plan = PaymentPlan(lines=tuple(PlannedLine(c, paid.get(c.id, 0), c.id in ahead)
                                   for c in charges), amount=amount)
    return plan, allocations


def _check_ahead(ahead: dict[int, int] | None) -> dict[int, int]:
    """{enrollment id: how many months ahead}, the zeros left out."""
    checked = {}
    for enrollment_id, count in (ahead or {}).items():
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValidationError(t["payment.ahead_invalid"])
        if count:
            checked[enrollment_id] = count
    return checked


def _months_ahead(conn, ctx: UserContext, student_id: int,
                  ahead: dict[int, int]) -> list[ChargeDue]:
    """The months `ahead` renews, as the charges they will be (not made yet: ids below 0), in
    the order record() makes them."""
    if not ahead:
        return []
    require(ctx, "subscription.manage")
    groups = {g.enrollment_id: g for g in subscriptions.next_months(conn, ctx, student_id)}
    months: list[ChargeDue] = []
    for enrollment_id, count in ahead.items():
        group = groups.get(enrollment_id)
        if group is None:
            raise ValidationError(t["payment.ahead_unknown"])
        if count > len(group.months):
            raise ValidationError(t["payment.ahead_too_many"].format(count=len(group.months)))
        for start, end in group.months[:count]:
            months.append(ChargeDue(
                id=-(len(months) + 1), kind="subscription",
                description=t["subscription.charge_description"].format(
                    group=group.group_name, start=dates.display_date(start),
                    end=dates.display_date(end)),
                amount=group.price, due_date=start, paid=0, group_id=group.group_id,
                start_date=start, end_date=end, group_name=group.group_name))
    return months


def preview(conn, ctx: UserContext, student_id: int, amount: int,
            chosen: list[int] | None = None, ahead: dict[int, int] | None = None
            ) -> PaymentPlan:
    """What record() would do with the same arguments, nothing written."""
    require(ctx, "payment.record")
    months = _months_ahead(conn, ctx, student_id, _check_ahead(ahead))
    # By due date, the months ahead after the charges of the same day: their ids will be
    # the newest (sorted() keeps the order of equal keys).
    charges = sorted([*debt.compute(conn, student_id).charges, *months],
                     key=lambda c: c.due_date)
    plan, _allocations = plan_payment(charges, amount, chosen,
                                      frozenset(c.id for c in months))
    return plan


# ----- recording -----

def _check_amount(amount) -> int:
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise ValidationError(t["payment.amount_invalid"])
    return amount


def receipt_number(conn) -> str:
    """Next 'R2026-00001'. Call inside the transaction that inserts the receipt."""
    year = dates.today().year
    return f"R{year}-{counters.next_value(conn, f'receipt:{year}'):05d}"


def record(conn, ctx: UserContext, student_id: int, amount: int, method: str,
           payer_contact_id: int | None = None, chosen: list[int] | None = None,
           ahead: dict[int, int] | None = None) -> int:
    """Receive `amount` DA for the student; returns the payment id. The receipt is made with
    it. chosen: the charge ids to pay instead of all of them, oldest first either way.
    ahead: {enrollment id: how many months}, renewed now and paid by this payment."""
    require(ctx, "payment.record")
    _check_amount(amount)
    if method not in PAYMENT_METHODS:
        raise ValidationError(t["payment.method_invalid"])
    ahead = _check_ahead(ahead)
    with atomic(conn):
        if students_repo.get(conn, student_id) is None:
            raise NotFound(t["student.not_found"])
        if payer_contact_id is not None and contacts_repo.get_link(
                conn, student_id, payer_contact_id) is None:
            raise ValidationError(t["payment.payer_unknown"])
        _months_ahead(conn, ctx, student_id, ahead)  # the preview's checks, before renewing
        made = frozenset(charge_id for enrollment_id, count in ahead.items()
                         for charge_id in subscriptions.renew_ahead_in(conn, ctx,
                                                                       enrollment_id, count))
        _plan, allocations = plan_payment(list(debt.compute(conn, student_id).charges),
                                          amount, chosen, made)

        now = _now()
        payment_id = repo.insert(conn, student_id, payer_contact_id, amount, method, now,
                                 ctx.user_id)
        for charge_id, value in allocations:
            repo.insert_allocation(conn, payment_id, charge_id, value)
        number = receipt_number(conn)
        receipt_id = repo.insert_receipt(conn, payment_id, number, now)
        audit.log(conn, ctx, "payment.record", "payments", payment_id, new={
            "student_id": student_id, "amount": amount, "method": method,
            "payer_contact_id": payer_contact_id, "receipt_id": receipt_id,
            "receipt_number": number, "chosen": chosen is not None,
            "months_ahead": sum(ahead.values()),
            "allocations": [{"charge_id": c, "amount": v} for c, v in allocations]})
        return payment_id


# ----- voiding -----

def void(conn, ctx: UserContext, payment_id: int, reason: str) -> None:
    """Director only. The payment stays, marked voided: what it paid is owed again (the
    months it renewed ahead stay, owed). Teacher payouts do not stop it: they count each
    month's full price whether it was paid or not. Refused once money of it was handed back
    (a refund paid, or the archive), and while a month it paid has a refund request pending
    or approved."""
    require(ctx, "payment.void")
    reason = clean(reason)
    if not reason:
        raise ValidationError(t["payment.reason_required"])
    with atomic(conn):
        row = _require_row(conn, payment_id)
        if row["voided"]:
            raise BusinessRuleError(t["payment.already_voided"])
        if refunds_repo.payment_handed_back(conn, payment_id):
            raise BusinessRuleError(t["payment.handed_back"])
        if refunds_repo.payment_month_asked(conn, payment_id):
            raise BusinessRuleError(t["payment.refund_open"])
        lines_paid = [{"charge_id": a["charge_id"], "amount": a["amount"]}
                      for a in repo.allocations(conn, payment_id)]
        repo.insert_void(conn, payment_id, reason, ctx.user_id, _now())
        audit.log(conn, ctx, "payment.void", "payments", payment_id,
                  old={"amount": row["amount"], "receipt_number": row["receipt_number"],
                       "allocations": lines_paid},
                  new={"voided": True, "reason": reason})
