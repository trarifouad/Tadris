from dataclasses import dataclass
from datetime import date, datetime

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError, NotFound, ValidationError
from tadris.core.money import format_dzd
from tadris.core.permissions import allowed, require
from tadris.core.text import clean
from tadris.db.errors import atomic
from tadris.domain.models import PAYMENT_METHODS, CashReport, ChargeDue, Payment, PaymentLine
from tadris.i18n.fr import t
from tadris.repositories import contacts as contacts_repo
from tadris.repositories import payments as repo
from tadris.repositories import students as students_repo
from tadris.services import audit, counters, debt, payouts

# A payment is money received from (or for) a student. It is immutable: a mistake is undone
# by a void (director only), never by an update or a negative payment. Recording one, in a
# single transaction: the student's credit (money received earlier and not allocated yet)
# pays the oldest charges first, then the new money does, oldest due first unless the desk
# chose the charges; what is left stays as credit. A receipt number 'R2026-00001' comes from
# the year's counter in the same transaction, so a rolled-back payment leaves no gap.


@dataclass(frozen=True)
class PlannedLine:
    charge: ChargeDue
    from_credit: int  # paid by money received earlier
    from_payment: int  # paid by the new payment

    @property
    def left(self) -> int:
        return self.charge.due - self.from_credit - self.from_payment


@dataclass(frozen=True)
class PaymentPlan:
    """What recording a payment would do, before it is recorded."""

    lines: tuple[PlannedLine, ...]  # every charge with something left to pay
    credit_before: int
    credit_used: int
    amount: int
    to_credit: int  # the part of the new payment kept as credit

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
    """What the payment paid, charge by charge (its credit, used later, included)."""
    require(ctx, "student.view")
    _require_row(conn, payment_id)
    return [PaymentLine(charge_id=row["charge_id"], description=row["description"],
                        due_date=row["due_date"], amount=row["amount"])
            for row in repo.allocations(conn, payment_id)]


def receipt_lines(conn, ctx: UserContext, payment_id: int) -> list[PaymentLine]:
    """What was paid when the payment was recorded, as its receipt shows it (the same when
    printed again): per charge, its own money and the credit of earlier payments it used.
    Its own credit, used by a later payment, shows on that payment's receipt."""
    require(ctx, "student.view")
    _require_row(conn, payment_id)
    return [PaymentLine(charge_id=row["charge_id"], description=row["description"],
                        due_date=row["due_date"], amount=row["amount"],
                        from_credit=row["from_credit"])
            for row in repo.recorded_with(conn, payment_id)]


def cash_report(conn, ctx: UserContext, day: date) -> CashReport:
    """The day's payments (totals per method and per cashier count those not voided) and,
    for the director (teacher pay is theirs to see), the teachers paid that day."""
    require(ctx, "cash.view")
    teachers_paid = (tuple(payouts.paid_on(conn, ctx, day)) if allowed(ctx, "payout.view")
                     else ())
    return CashReport(day=dates.iso(day),
                      payments=tuple(_to_payment(row) for row in repo.on_day(conn,
                                                                              dates.iso(day))),
                      payouts=teachers_paid)


# ----- planning (pure: the dialog's preview and record() use the same code) -----

def plan_payment(charges: list[ChargeDue], credits: list[tuple[int, int]], amount: int,
                 chosen: list[tuple[int, int]] | None = None,
                 ) -> tuple[PaymentPlan, list[tuple[int, int, int]], list[tuple[int, int]]]:
    """Plan a payment of `amount` for open charges (oldest due first) and the credits
    (payment id, amount left), oldest first.

    Returns the plan, the credit allocations (payment id, charge id, amount) and the new
    payment's allocations (charge id, amount). `chosen` replaces the oldest-first order
    for the new payment: (charge id, amount) pairs, checked against what is left after the
    credit."""
    left = {c.id: c.due for c in charges}
    from_credit = dict.fromkeys(left, 0)
    credit_allocations: list[tuple[int, int, int]] = []
    for payment_id, available in credits:
        for c in charges:
            if available <= 0:
                break
            take = min(available, left[c.id])
            if take > 0:
                credit_allocations.append((payment_id, c.id, take))
                left[c.id] -= take
                from_credit[c.id] += take
                available -= take

    if chosen is None:
        allocations = []
        remaining = amount
        for c in charges:
            if remaining <= 0:
                break
            take = min(remaining, left[c.id])
            if take > 0:
                allocations.append((c.id, take))
                remaining -= take
    else:
        allocations = _check_chosen(chosen, left, amount)
    from_payment = dict.fromkeys(left, 0)
    for charge_id, value in allocations:
        from_payment[charge_id] += value

    credit_before = sum(available for _payment_id, available in credits)
    credit_used = sum(value for _p, _c, value in credit_allocations)
    plan = PaymentPlan(
        lines=tuple(PlannedLine(c, from_credit[c.id], from_payment[c.id]) for c in charges),
        credit_before=credit_before, credit_used=credit_used, amount=amount,
        to_credit=amount - sum(value for _c, value in allocations))
    return plan, credit_allocations, allocations


def _check_chosen(chosen: list[tuple[int, int]], left: dict[int, int],
                  amount: int) -> list[tuple[int, int]]:
    allocations = []
    seen = set()
    for charge_id, value in chosen:
        if value == 0:
            continue
        if charge_id not in left or charge_id in seen:
            raise ValidationError(t["payment.charge_unknown"])
        if value < 0 or value > left[charge_id]:
            raise ValidationError(t["payment.allocation_too_high"].format(
                amount=format_dzd(left[charge_id])))
        seen.add(charge_id)
        allocations.append((charge_id, value))
    if sum(value for _c, value in allocations) > amount:
        raise ValidationError(t["payment.allocations_exceed"].format(amount=format_dzd(amount)))
    return allocations


def _credits(conn, student_id: int) -> list[tuple[int, int]]:
    return [(row["id"], row["amount"] - row["allocated"])
            for row in repo.with_credit(conn, student_id)]


def preview(conn, ctx: UserContext, student_id: int, amount: int,
            chosen: list[tuple[int, int]] | None = None) -> PaymentPlan:
    """What record() would do with the same arguments, nothing written."""
    require(ctx, "payment.record")
    current = debt.compute(conn, student_id)
    plan, _credit, _allocations = plan_payment(list(current.charges),
                                               _credits(conn, student_id), amount, chosen)
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
           payer_contact_id: int | None = None,
           chosen: list[tuple[int, int]] | None = None) -> int:
    """Receive `amount` DA for the student; returns the payment id. The receipt is made with
    it. chosen: (charge id, amount) pairs instead of the oldest-first order."""
    require(ctx, "payment.record")
    _check_amount(amount)
    if method not in PAYMENT_METHODS:
        raise ValidationError(t["payment.method_invalid"])
    with atomic(conn):
        if students_repo.get(conn, student_id) is None:
            raise NotFound(t["student.not_found"])
        if payer_contact_id is not None and contacts_repo.get_link(
                conn, student_id, payer_contact_id) is None:
            raise ValidationError(t["payment.payer_unknown"])
        current = debt.compute(conn, student_id)
        plan, credit_allocations, allocations = plan_payment(
            list(current.charges), _credits(conn, student_id), amount, chosen)

        # The payment first: every allocation its recording makes, its credit's too, says so.
        now = _now()
        payment_id = repo.insert(conn, student_id, payer_contact_id, amount, method, now,
                                 ctx.user_id)
        for credit_payment_id, charge_id, value in credit_allocations:
            repo.insert_allocation(conn, credit_payment_id, charge_id, value, payment_id)
        if credit_allocations:
            audit.log(conn, ctx, "payment.apply_credit", "payments", payment_id, new={
                "student_id": student_id,
                "allocations": [{"payment_id": p, "charge_id": c, "amount": v}
                                for p, c, v in credit_allocations]})
        for charge_id, value in allocations:
            repo.insert_allocation(conn, payment_id, charge_id, value, payment_id)
        number = receipt_number(conn)
        receipt_id = repo.insert_receipt(conn, payment_id, number, now)
        audit.log(conn, ctx, "payment.record", "payments", payment_id, new={
            "student_id": student_id, "amount": amount, "method": method,
            "payer_contact_id": payer_contact_id, "receipt_id": receipt_id,
            "receipt_number": number, "chosen": chosen is not None,
            "allocations": [{"charge_id": c, "amount": v} for c, v in allocations],
            "to_credit": plan.to_credit})
        return payment_id


# ----- voiding -----

def void(conn, ctx: UserContext, payment_id: int, reason: str) -> None:
    """Director only. The payment stays, marked voided: what it paid is owed again and its
    credit is gone. Teacher payouts do not stop it: they count each month's full price
    whether it was paid or not. Refused once money of it was handed back (refunds archived
    since 0015)."""
    require(ctx, "payment.void")
    reason = clean(reason)
    if not reason:
        raise ValidationError(t["payment.reason_required"])
    with atomic(conn):
        row = _require_row(conn, payment_id)
        if row["voided"]:
            raise BusinessRuleError(t["payment.already_voided"])
        lines_paid = [{"charge_id": a["charge_id"], "amount": a["amount"]}
                      for a in repo.allocations(conn, payment_id)]
        repo.insert_void(conn, payment_id, reason, ctx.user_id, _now())
        audit.log(conn, ctx, "payment.void", "payments", payment_id,
                  old={"amount": row["amount"], "receipt_number": row["receipt_number"],
                       "allocations": lines_paid},
                  new={"voided": True, "reason": reason})
