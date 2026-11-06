from datetime import date, datetime, timedelta

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError, NotFound, PermissionDenied, ValidationError
from tadris.core.money import format_dzd
from tadris.core.permissions import allowed, require
from tadris.core.text import clean, group_title
from tadris.db.errors import atomic
from tadris.domain.models import PAYMENT_METHODS, Refund, RefundableMonth, SessionsLeft
from tadris.i18n.fr import t
from tadris.repositories import holidays as holidays_repo
from tadris.repositories import refunds as repo
from tadris.services import audit, counters
from tadris.services.enrollments import LIVE

# Refunds in V1 (decided 2026-11-06; PLAN « Refunds in V1 », migrations 0021 and 0022). A
# refund hands back money paid on one month paid in full, never the registration fee, for at
# most the value of the month's sessions left. It never changes what is owed nor teacher pay:
# the month stays open and paid; once refunded in full, the director may cancel it by hand.
#
# The steps, each in one transaction with its audit line: the desk or the director asks
# (pending), with a reason and an amount up to the maximum, counted then and kept with the
# request (the timetable is not read again). The director approves the amount asked or less
# (REVIEW_FIXES, decision 3) or rejects with a reason. A pending request is withdrawn by whoever
# asked it, or by the director, who also withdraws an approved one (cancelled, with a reason).
# Pending and approved requests hold their amount, paid ones what they handed back; the
# others nothing. Once the money has gone back, the director records it (paid): it is taken
# back from the payments that paid the month, the latest first, never more than each one
# gave, and numbered RB2026-00001 from the year's counter.
#
# The sessions left (this part is pure, apart from _sessions_left() that reads its inputs):
# the month's sessions are those of its group's timetable in [start, end): one per slot
# meeting on a day (two slots on a day, two sessions), while the slot is valid, from the
# group's start to the last day of its school year, holidays left out, as the sessions are
# generated. Not the generated sessions themselves: they only run 14 days ahead. The
# sessions left are those from the first day not used on, and only once the student has left
# (REVIEW_FIXES, decision 1): while they are still in the group, or in the group a switch took
# them to, nothing can be asked, since a month left in the old group covers the new one until
# it ends. The first day not used is taken from the whole switch chain, not only the last
# place: every day the student still followed the month (an enrollment that had started) is
# used, so a session attended in the old group on the switch day is never handed back, and
# two places that share that day count it once. A place left before it started occupies no
# day. The last day itself, when it may not have been used: the school closed the group that
# day (the entry day for a group closed before it), or the last started place ended on its
# entry day and no earlier place already covered that day; then only that day's sessions of
# the month's group already given count as used (held, for a closure; with attendance on the
# chain, otherwise), one by one. The sessions before, attended, missed or cancelled by the
# school (made up or not), are used: handing back a cancelled session is beyond V1 (PLAN
# « Refunds beyond V1 »). Their value is
# price × left ÷ total, rounded down to the dinar. A month with no session at all (no
# timetable, all holidays) is worth its price if none of it was used (counted from its first
# day or before), else nothing (REVIEW_FIXES, decision 2).
#
# A group closed by the school (its closure, migration 0022; the closure that ended the
# student's place if one did, even after a reopening, else the one the group is under): its
# slots ended on the closing day, so from that day on the count uses the slots the closure
# kept, running that day or
# planned to start later, each from its own first day to its planned end, as if they went on
# (to the month's end, never past its year). A slot over before the closure is not among
# them. A month running at the closure, and a month paid ahead after it, keep the sessions
# the school no longer gives; a group closed before it started keeps its first weeks.


# ----- the sessions left in a month (pure) -----

def days_off(holidays) -> set[date]:
    """Every day of holiday periods given as (first day, last day), both included."""
    off = set()
    for first, last in holidays:
        day = first
        while day <= last:
            off.add(day)
            day += timedelta(days=1)
    return off


def sessions_on(first: date, last: date, slots, off: set[date]) -> list[date]:
    """The day of each session in [first, last] (both included): one per slot meeting that
    day, in order. slots: (weekday 1 = Monday ... 7, valid_from, valid_to or None: half-open)."""
    found = []
    day = first
    while day <= last:
        if day not in off:
            weekday = day.isoweekday()
            found += [day for slot_day, valid_from, valid_to in slots
                      if slot_day == weekday and valid_from <= day
                      and (valid_to is None or day < valid_to)]
        day += timedelta(days=1)
    return found


def value_of(price: int, left: int, total: int) -> int:
    """price × left ÷ total, rounded down to the dinar; nothing without a session."""
    return price * left // total if total else 0


def count_left(start: date, end: date, price: int, counted_from: date, slots, holidays,
               group_start: date | None = None, year_end: date | None = None,
               used: int = 0) -> SessionsLeft:
    """The month [start, end) and its sessions left from counted_from on (that day
    included). group_start, year_end: no session before the group starts or after the last
    day of its year. used: sessions of counted_from's day already given, taken off what is
    left (never more than that day has). With no session at all, the month is worth its
    price if counted from its first day or before (none of it used), else nothing."""
    first = max(start, group_start) if group_start else start
    last = end - timedelta(days=1)
    if year_end is not None:
        last = min(last, year_end)
    month = sessions_on(first, last, slots, days_off(holidays))
    on_first = sum(1 for day in month if day == counted_from)
    left = sum(1 for day in month if day >= counted_from) - min(used, on_first)
    if not month:
        value = price if counted_from <= first else 0
    else:
        value = value_of(price, left, len(month))
    return SessionsLeft(counted_from=dates.iso(counted_from), total=len(month), left=left,
                        value=value)


def until_closure(slots, closed_on: date, kept) -> list:
    """A closed group's slots: the timetable before its closing day, then from that day on
    the slots its closure kept (weekday, valid_from, valid_to or None), each from its own
    first day (the closing day at the earliest) to its planned end, going on."""
    before = [(weekday, valid_from, min(valid_to, closed_on) if valid_to else closed_on)
              for weekday, valid_from, valid_to in slots if valid_from < closed_on]
    after = [(weekday, max(valid_from, closed_on), valid_to)
             for weekday, valid_from, valid_to in kept]
    return before + [(weekday, valid_from, valid_to) for weekday, valid_from, valid_to in after
                     if valid_to is None or valid_to > valid_from]


def last_day_open(by_closure: bool, left_on: str, enrolled_on: str,
                  covered_already: bool = False) -> bool:
    """The last day may not have been used: the school closed the group that day, or the
    last started place ended on its entry day and no earlier place of the chain already
    covered that day."""
    return by_closure or (left_on == enrolled_on and not covered_already)


def first_unused_day(left_on: date, open_last_day: bool) -> date:
    """The day after the student's last day in the group, or that day itself when it may not
    have been used (its sessions already given are then taken off: count_left's used)."""
    return left_on if open_last_day else left_on + timedelta(days=1)


# ----- the sessions left, read from the database -----

def _still_in(place) -> str | None:
    """The group the student still follows the month in (its own, or the one a switch took
    them to), or None once they have left."""
    return group_title(place) if place["status"] in LIVE else None


def _covers(place, day: str) -> bool:
    """The place occupies that calendar day: it had started, and [enrolled_on, left_on]
    includes it."""
    if place["never_started"]:
        return False
    if place["enrolled_on"] > day:
        return False
    return place["left_on"] is None or place["left_on"] >= day


def _started(chain) -> list:
    """Places of the chain that occupied at least one day (left before start occupy none)."""
    return [place for place in chain if not place["never_started"]]


def _first_unused(conn, chain) -> tuple[date, int]:
    """The chain has ended: the first day not used, and how many sessions were already given
    to the student that day (0 unless it is the last day itself). They are looked for where
    the student spent that day, the last started place's group (after a switch, not the
    month's): held there for a closure, attended there otherwise, timetable sessions only.
    count_left caps them by the month group's sessions that day."""
    occupied = _started(chain)
    if not occupied:
        return date.fromisoformat(chain[0]["enrolled_on"]), 0
    last = occupied[-1]
    left_on = last["left_on"]
    earlier = any(place["id"] != last["id"] and _covers(place, left_on) for place in occupied)
    open_last = last_day_open(last["closure_id"] is not None, left_on, last["enrolled_on"],
                              earlier)
    if not open_last:
        return first_unused_day(date.fromisoformat(left_on), False), 0
    ids = [place["id"] for place in chain]
    used = (repo.held_count(conn, last["group_id"], left_on) if last["closure_id"] is not None
            else repo.attended_on(conn, last["group_id"], ids, left_on))
    return first_unused_day(date.fromisoformat(left_on), True), used


def _closure_of(row, chain) -> tuple[int | None, str | None]:
    """The closure the month counts with: the one that ended the student's place in the
    month's own group, even after a reopening; else the one the group is under now."""
    for place in reversed(chain):
        if place["closure_id"] is not None and place["group_id"] == row["group_id"]:
            return place["closure_id"], place["closed_on"]
    return row["closure_id"], row["closed_on"]


def _sessions_of(conn, row, chain) -> tuple[SessionsLeft | None, str | None]:
    """(the sessions left, None) once the student has left; (None, the group they still
    follow the month in) before. `row` is a repo.month row, `chain` its enrollments."""
    still_in = _still_in(chain[-1])
    if still_in is not None:
        return None, still_in
    counted_from, used = _first_unused(conn, chain)
    return _count(conn, row, counted_from, used, _closure_of(row, chain)), None


def _sessions_left(conn, subscription_id: int) -> SessionsLeft:
    """The month's sessions left as its group's timetable and the holidays stand now. Refused
    while the student is still in the group, or in the group a switch took them to. No
    permission check: internal (the screens go through options and request, which check)."""
    row = repo.month(conn, subscription_id)
    if row is None:
        raise NotFound(t["subscription.not_found"])
    counted, still_in = _sessions_of(conn, row, repo.place_chain(conn, row["enrollment_id"]))
    if still_in is not None:
        raise BusinessRuleError(t["refund.still_enrolled"].format(group=still_in))
    return counted


def _periods(rows) -> list:
    """(weekday, valid_from, valid_to or None) of slot rows, as dates."""
    return [(r["weekday"], date.fromisoformat(r["valid_from"]),
             date.fromisoformat(r["valid_to"]) if r["valid_to"] else None) for r in rows]


def _count(conn, row, counted_from: date, used: int,
           closure: tuple[int | None, str | None]) -> SessionsLeft:
    """The month (a repo.month row) counted from that day on, `used` of that day's sessions
    already given, with that closure (id, day) if any."""
    start, end = date.fromisoformat(row["start_date"]), date.fromisoformat(row["end_date"])
    last = dates.iso(end - timedelta(days=1))
    slots = _periods(repo.slots(conn, row["group_id"], row["start_date"], last))
    closure_id, closed_on = closure
    if closure_id is not None:
        slots = until_closure(slots, date.fromisoformat(closed_on),
                              _periods(repo.closure_slots(conn, closure_id)))
    holidays = [(date.fromisoformat(h["start_date"]), date.fromisoformat(h["end_date"]))
                for h in holidays_repo.between(conn, row["start_date"], last)]
    return count_left(start, end, row["price"], counted_from, slots, holidays,
                      group_start=date.fromisoformat(row["group_start"]),
                      year_end=date.fromisoformat(row["year_end"]), used=used)


# ----- reading -----

def _now() -> str:
    """The service's clock, not SQLite's: the day matches dates.today()."""
    return f"{dates.iso(dates.today())}T{datetime.now():%H:%M:%S}"


def _to_refund(row) -> Refund:
    return Refund(
        id=row["id"], charge_id=row["charge_id"], subscription_id=row["subscription_id"],
        student_id=row["student_id"], student_number=row["student_number"],
        student_name=f"{row['last_name']} {row['first_name']}", group_title=group_title(row),
        month_start=row["month_start"], month_end=row["month_end"], price=row["price"],
        counted_from=row["counted_from"], sessions_total=row["sessions_total"],
        sessions_left=row["sessions_left"], sessions_value=row["sessions_value"],
        max_amount=row["max_amount"], amount_requested=row["amount_requested"],
        amount_approved=row["amount_approved"], reason=row["reason"], status=row["status"],
        requested_by_id=row["requested_by_id"], requested_by=row["requested_by"],
        requested_at=row["requested_at"], decided_by=row["decided_by"],
        decided_at=row["decided_at"], cancelled_by=row["cancelled_by"],
        cancelled_at=row["cancelled_at"], close_reason=row["close_reason"],
        number=row["number"], method=row["method"], paid_by=row["paid_by"],
        paid_at=row["paid_at"],
    )


def _require_row(conn, refund_id: int):
    row = repo.get(conn, refund_id)
    if row is None:
        raise NotFound(t["refund.not_found"])
    return row


def get(conn, ctx: UserContext, refund_id: int) -> Refund:
    require(ctx, "student.view")
    return _to_refund(_require_row(conn, refund_id))


def for_student(conn, ctx: UserContext, student_id: int) -> list[Refund]:
    """Latest first."""
    require(ctx, "student.view")
    return [_to_refund(row) for row in repo.for_student(conn, student_id)]


def count_for_student(conn, ctx: UserContext, student_id: int) -> int:
    """What for_student() would list, counted (the student's page, on each change)."""
    require(ctx, "student.view")
    return repo.count_for_student(conn, student_id)


def paid_on(conn, ctx: UserContext, day: date) -> list[Refund]:
    """The refunds whose money went back on `day`: the cash of the day takes them out."""
    require(ctx, "cash.view")
    return [_to_refund(row) for row in repo.paid_on(conn, dates.iso(day))]


def queue(conn, ctx: UserContext) -> list[Refund]:
    """What waits: pending (for the director's decision) and approved (for the money to go
    back), oldest first."""
    require(ctx, "refund.request")
    return [_to_refund(row) for row in repo.with_status(conn, ("pending", "approved"))]


# ----- what can be asked -----

def _maximum(value: int, paid: int, archived: int, held: int) -> int:
    """The value of the sessions left, never more than was paid less what the archive (phase
    8) handed back of it, less what refunds hold."""
    return max(min(value, paid - archived) - held, 0)


def options(conn, ctx: UserContext, student_id: int) -> list[RefundableMonth]:
    """The student's months paid in full, the latest first, each with the most a new request
    can ask now (0: nothing left to refund on it). A month the student still follows, in its
    group or in the one a switch took them to, has no count and 0 (still_in says where)."""
    require(ctx, "refund.request")
    result, chains = [], {}
    for row in repo.paid_months(conn, student_id):  # each row is also a month() row
        eid = row["enrollment_id"]
        if eid not in chains:
            chains[eid] = repo.place_chain(conn, eid)
        counted, still_in = _sessions_of(conn, row, chains[eid])
        held = row["held"]
        most = 0 if counted is None else _maximum(counted.value, row["paid"], row["archived"],
                                                   held)
        result.append(RefundableMonth(
            subscription_id=row["subscription_id"], charge_id=row["charge_id"],
            group_title=group_title(row), start_date=row["start_date"], end_date=row["end_date"],
            price=row["price"], paid=row["paid"], held=held + row["archived"],
            sessions=counted, max_amount=most, still_in=still_in))
    return result


# ----- the steps -----

def _check_amount(amount) -> int:
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise ValidationError(t["refund.amount_invalid"])
    return amount


def _reason(reason: str) -> str:
    reason = clean(reason)
    if not reason:
        raise ValidationError(t["refund.reason_required"])
    return reason


def request(conn, ctx: UserContext, subscription_id: int, amount: int, reason: str) -> int:
    """Ask to hand back `amount` DA paid on the month; returns the request's id. Refused while
    the student still follows the month (record the leave first)."""
    require(ctx, "refund.request")
    _check_amount(amount)
    reason = _reason(reason)
    with atomic(conn):
        row = repo.month(conn, subscription_id)
        if row is None:
            raise NotFound(t["subscription.not_found"])
        charge = repo.open_charge(conn, subscription_id)
        if charge is None:
            raise BusinessRuleError(t["refund.month_cancelled"])
        if charge["paid"] < charge["amount"]:
            raise BusinessRuleError(t["refund.not_paid_in_full"].format(
                paid=format_dzd(charge["paid"]), price=format_dzd(charge["amount"])))
        counted, still_in = _sessions_of(conn, row, repo.place_chain(conn, row["enrollment_id"]))
        if still_in is not None:
            raise BusinessRuleError(t["refund.still_enrolled"].format(group=still_in))
        if counted.total == 0 and counted.value == 0:
            raise BusinessRuleError(t["refund.no_session"])
        held = repo.held(conn, charge["id"])
        most = _maximum(counted.value, charge["paid"], charge["archived"], held)
        if most == 0:
            raise BusinessRuleError(t["refund.nothing_left"])
        if amount > most:
            raise BusinessRuleError(t["refund.above_max"].format(amount=format_dzd(most)))
        refund_id = repo.insert(conn, charge["id"], counted.counted_from, counted.total,
                                counted.left, counted.value, most, amount, reason,
                                ctx.user_id, _now())
        audit.log(conn, ctx, "refund.request", "refunds", refund_id, new={
            "subscription_id": subscription_id, "charge_id": charge["id"], "amount": amount,
            "max_amount": most, "held_before": held, "reason": reason,
            **({"archived": charge["archived"]} if charge["archived"] else {}),
            "counted_from": counted.counted_from, "sessions_total": counted.total,
            "sessions_left": counted.left, "sessions_value": counted.value})
        return refund_id


def approve(conn, ctx: UserContext, refund_id: int, amount: int | None = None) -> None:
    """Director only. amount: what goes back (default: the amount asked), the amount asked or
    less, and within the maximum kept with the request as the month stands now."""
    require(ctx, "refund.decide")
    with atomic(conn):
        row = _require_row(conn, refund_id)
        if row["status"] != "pending":
            raise BusinessRuleError(t["refund.not_pending"])
        final = row["amount_requested"] if amount is None else _check_amount(amount)
        if final > row["amount_requested"]:
            raise BusinessRuleError(t["refund.above_asked"].format(
                amount=format_dzd(row["amount_requested"])))
        charge = repo.open_charge(conn, row["subscription_id"])
        others = repo.held(conn, row["charge_id"], exclude_id=refund_id)
        left = 0 if charge is None else _maximum(row["sessions_value"], charge["paid"],
                                                  charge["archived"], others)
        if final > left:
            raise BusinessRuleError(t["refund.above_max"].format(amount=format_dzd(left)))
        repo.approve(conn, refund_id, final, ctx.user_id, _now())
        audit.log(conn, ctx, "refund.approve", "refunds", refund_id,
                  old={"status": "pending", "amount_requested": row["amount_requested"]},
                  new={"status": "approved", "amount_approved": final})


def reject(conn, ctx: UserContext, refund_id: int, reason: str) -> None:
    """Director only, a pending request (an approved one is withdrawn): its amount is freed."""
    require(ctx, "refund.decide")
    reason = _reason(reason)
    with atomic(conn):
        row = _require_row(conn, refund_id)
        if row["status"] != "pending":
            raise BusinessRuleError(t["refund.not_pending"])
        repo.reject(conn, refund_id, reason, ctx.user_id, _now())
        audit.log(conn, ctx, "refund.reject", "refunds", refund_id,
                  old={"status": "pending"}, new={"status": "rejected", "reason": reason})


def withdraw(conn, ctx: UserContext, refund_id: int, reason: str) -> None:
    """A pending request, by whoever asked it; any pending or approved one, by the director.
    Its amount is freed."""
    require(ctx, "refund.request")
    reason = _reason(reason)
    with atomic(conn):
        row = _require_row(conn, refund_id)
        if row["status"] not in ("pending", "approved"):
            raise BusinessRuleError(t["refund.closed"])
        if not allowed(ctx, "refund.decide") and (
                row["status"] != "pending" or row["requested_by_id"] != ctx.user_id):
            raise PermissionDenied(t["permission.denied"])
        repo.withdraw(conn, refund_id, reason, ctx.user_id, _now())
        audit.log(conn, ctx, "refund.cancel", "refunds", refund_id,
                  old={"status": row["status"]}, new={"status": "cancelled", "reason": reason})


def refund_number(conn) -> str:
    """Next 'RB2026-00001'. Call inside the transaction that records the refund paid. The
    counter is the one the phase 8 refunds used: their numbers are never given again."""
    year = dates.today().year
    return f"RB{year}-{counters.next_value(conn, f'refund:{year}'):05d}"


def pay_out(conn, ctx: UserContext, refund_id: int, method: str) -> str:
    """Director only: the money of an approved refund has gone back. It is taken back from
    the payments that paid the month, the latest first; returns the refund's number."""
    require(ctx, "refund.pay")
    if method not in PAYMENT_METHODS:
        raise ValidationError(t["payment.method_invalid"])
    with atomic(conn):
        row = _require_row(conn, refund_id)
        if row["status"] != "approved":
            raise BusinessRuleError(t["refund.not_approved"])
        amount = row["amount_approved"]
        sources = repo.sources(conn, row["charge_id"])
        if sum(source["remaining"] for source in sources) < amount:
            raise BusinessRuleError(t["refund.money_gone"])
        taken, left = [], amount
        for source in sources:
            if left == 0:
                break
            part = min(left, source["remaining"])
            repo.insert_allocation(conn, refund_id, source["id"], part)
            taken.append({"payment_id": source["payment_id"], "allocation_id": source["id"],
                          "amount": part})
            left -= part
        number = refund_number(conn)
        repo.mark_paid(conn, refund_id, number, method, ctx.user_id, _now())
        audit.log(conn, ctx, "refund.pay", "refunds", refund_id,
                  old={"status": "approved"},
                  new={"status": "paid", "number": number, "amount": amount,
                       "method": method, "from": taken})
        return number
