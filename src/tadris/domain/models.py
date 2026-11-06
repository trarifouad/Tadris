from dataclasses import dataclass, field
from datetime import date

from tadris.core.percent import ratio_bp

# ----- inputs (what a form sends to a service) -----


@dataclass(frozen=True)
class StudentInput:
    first_name: str
    last_name: str
    birth_date: date | None = None
    notes: str = ""


@dataclass(frozen=True)
class ContactInput:
    full_name: str
    phone: str = ""
    phone_2: str = ""
    address: str = ""


@dataclass(frozen=True)
class ContactLink:
    """How a contact relates to one student."""

    relation: str = ""
    is_main: bool = False
    can_receive_sms: bool = True


# ----- read models (what a service returns) -----


@dataclass(frozen=True)
class Student:
    id: int
    student_number: str
    first_name: str
    last_name: str
    birth_date: str | None
    status: str
    notes: str
    created_at: str

    @property
    def full_name(self) -> str:
        return f"{self.last_name} {self.first_name}"


@dataclass(frozen=True)
class StudentListItem:
    id: int
    student_number: str
    first_name: str
    last_name: str
    birth_date: str | None
    status: str
    main_contact: str | None
    main_phone: str | None
    groups: str | None  # now (trial or active): "A · Maths, B · Physique"
    standing: str | None  # the most urgent of its paid groups (models.standing); None: none


@dataclass(frozen=True)
class StudentContact:
    contact_id: int
    full_name: str
    phone: str | None
    phone_2: str | None
    address: str | None
    relation: str
    is_main: bool
    can_receive_sms: bool
    # Other students this contact is linked to (siblings), as "Last First".
    shared_with: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ExistingContact:
    contact_id: int
    full_name: str
    phone: str | None
    students: tuple[str, ...]


@dataclass(frozen=True)
class DuplicateMatch:
    student_id: int
    student_number: str
    full_name: str
    reason: str  # "name" or "phone"


# ----- academic setup -----


@dataclass(frozen=True)
class SchoolYear:
    id: int
    label: str
    start_date: str
    end_date: str
    status: str  # 'open' or 'closed'
    state: str  # display state: 'open', 'upcoming' or 'closed'
    group_count: int = 0


@dataclass(frozen=True)
class NamedItem:
    """A level or a subject."""

    id: int
    name: str
    is_active: bool
    order_index: int = 0
    group_count: int = 0
    # Levels only: its groups take students of every level (« Tous niveaux »).
    is_open: bool = False
    # Subjects only: a workshop (calligraphie, arts…), offered for the open levels' groups.
    is_workshop: bool = False


@dataclass(frozen=True)
class Room:
    id: int
    name: str
    capacity: int
    status: str
    slot_count: int = 0


@dataclass(frozen=True)
class TeacherInput:
    full_name: str
    phone: str = ""
    hire_date: date | None = None


@dataclass(frozen=True)
class Teacher:
    id: int
    full_name: str
    phone: str | None
    status: str
    hire_date: str | None
    # Basis points; None when the user may not see rates.
    current_rate_bp: int | None = None
    group_count: int = 0
    current_rate_from: str | None = None  # the current rate's first day (None: not seen)


@dataclass(frozen=True)
class RatePeriod:
    id: int
    percentage_bp: int
    valid_from: str
    valid_to: str | None


@dataclass(frozen=True)
class GroupInput:
    school_year_id: int
    level_id: int
    subject_id: int
    name: str
    price: int
    capacity: int
    start_date: date


@dataclass(frozen=True)
class Group:
    id: int
    school_year_id: int
    year_label: str
    level_id: int
    level: str
    subject_id: int
    subject: str
    name: str
    price: int
    capacity: int
    start_date: str
    status: str
    state: str  # display: 'active', 'upcoming' (not started yet) or 'closed'
    teacher_id: int | None
    teacher: str | None
    enrolled: int
    # Smallest room among the running or future slots; it caps the seats while used.
    room_limit: int | None = None
    limiting_room: str | None = None
    # Its level is open (« Tous niveaux »): students of every level may join.
    level_open: bool = False

    @property
    def title(self) -> str:
        return f"{self.name} · {self.subject} {self.level}"

    @property
    def seats(self) -> int:
        """Places actually available: the group's capacity, or less if a room is smaller."""
        if self.room_limit is None:
            return self.capacity
        return min(self.capacity, self.room_limit)

    @property
    def room_limited(self) -> bool:
        return self.seats < self.capacity


@dataclass(frozen=True)
class TeacherPeriod:
    id: int
    teacher_id: int
    teacher: str
    valid_from: str
    valid_to: str | None


@dataclass(frozen=True)
class SlotInput:
    group_id: int
    room_id: int
    weekday: int  # 1 = Monday ... 7 = Sunday
    start_time: str  # 'HH:MM'
    end_time: str
    valid_from: date | None = None


@dataclass(frozen=True)
class Slot:
    id: int
    group_id: int
    group: str
    level: str
    subject: str
    room_id: int
    room: str
    teacher_id: int | None
    teacher: str | None
    weekday: int
    start_time: str
    end_time: str
    valid_from: str
    valid_to: str | None


# ----- registration and enrollment -----


@dataclass(frozen=True)
class Registration:
    id: int
    student_id: int
    school_year_id: int
    year_label: str
    level_id: int
    level: str
    fee_amount: int
    status: str  # 'active' or 'cancelled'
    registered_at: str
    live_enrollments: int  # groups the student is in (trial or active)
    fee_charge_id: int | None  # None when the fee was 0
    fee_paid: int  # by payments not voided
    # Of the live ones, those in groups of a level that is not open: they hold the level.
    level_enrollments: int = 0

    @property
    def fee_due(self) -> int:
        """What remains to pay on the fee (0 once cancelled)."""
        if self.status != "active" or self.fee_charge_id is None:
            return 0
        return max(self.fee_amount - self.fee_paid, 0)


@dataclass(frozen=True)
class Enrollment:
    id: int
    student_id: int
    student_number: str
    student_name: str  # "Last First"
    group_id: int
    group_name: str
    subject: str
    group_level: str
    registration_id: int
    registration_level: str
    status: str  # 'trial', 'active', 'left' or 'switched'
    started_as_trial: bool
    enrolled_on: str
    left_on: str | None
    switched_from_id: int | None
    # The group's level is open (« Tous niveaux »): any registration level belongs there.
    group_level_open: bool = False
    # Left (or closed) before the entry day: on no session, even the entry day itself.
    never_started: bool = False

    @property
    def group_title(self) -> str:
        return f"{self.group_name} · {self.subject} {self.group_level}"

    @property
    def is_live(self) -> bool:
        return self.status in ("trial", "active")

    @property
    def other_level(self) -> bool:
        """In a group of another level: only enrollments made before migration 0010, when the
        director could override the level, can be. A group of an open level is never one."""
        return not self.group_level_open and self.group_level != self.registration_level


@dataclass(frozen=True)
class GroupCandidate:
    """A student who may join a group, as offered from the group's page."""

    student_id: int
    student_number: str
    student_name: str  # "Last First"
    level: str  # their registration's
    can_trial: bool  # never had their free trial
    # Already in another group of this subject: needs the director override.
    same_subject: bool = False


@dataclass(frozen=True)
class GroupOption:
    """A group of the open year, as offered in the "enroll in group" dialog."""

    group: Group
    already_in: bool
    # Already in another group of this subject: needs the director override.
    same_subject: bool = False

    @property
    def needs_override(self) -> bool:
        return self.same_subject

    @property
    def free(self) -> int:
        return max(self.group.seats - self.group.enrolled, 0)

    @property
    def available(self) -> bool:
        return not self.already_in and self.free > 0


# ----- subscriptions -----


@dataclass(frozen=True)
class Subscription:
    id: int
    enrollment_id: int
    enrollment_status: str  # 'trial', 'active', 'left' or 'switched'
    student_id: int
    student_number: str
    student_name: str  # "Last First"
    group_id: int
    group_title: str
    renewal_of_id: int | None
    price: int
    start_date: str
    end_date: str  # the day after the last day (half-open period)
    status: str  # stored: 'active', 'ended' or 'cancelled'
    state: str  # display: 'upcoming', 'active', 'expiring', 'ended' or 'cancelled'
    charge_id: int | None  # None for a free group
    paid: int  # by payments not voided
    in_payout: bool  # counted in an approved or paid teacher payout (a draft lets it go)
    # Read for one month, one student's or one enrollment's months; None from the
    # school-wide lists, which never decide a cancel.
    refunded: int | None = 0  # handed back by refunds (paid out)
    refund_open: bool | None = False  # a refund request pending or approved on it

    @property
    def due(self) -> int:
        """What remains to pay (0 once cancelled or for a free group). A refund never
        changes it: a month refunded stays paid."""
        if self.status == "cancelled" or self.charge_id is None:
            return 0
        return max(self.price - self.paid, 0)

    @property
    def kept(self) -> int:
        """The money paid on it that the school keeps: paid less what was handed back."""
        if self.refunded is None:
            raise ValueError("this list does not read refunds: use subscriptions.get")
        return self.paid - self.refunded

    @property
    def can_cancel(self) -> bool:
        """The director's « Annuler »: no money kept on it (nothing paid, or all of it handed
        back), no refund request open, and no teacher paid for it yet."""
        return (self.status != "cancelled" and not self.kept and not self.refund_open
                and not self.in_payout)

    @property
    def cancelled_on_leaving(self) -> bool:
        """Leaving the group cancels a month to come only if nothing was ever paid on it and
        no teacher was paid for it: a month refunded in full is kept, for the director to
        cancel by hand (a refund never cancels a month by itself)."""
        return self.status != "cancelled" and not self.paid and not self.in_payout


@dataclass(frozen=True)
class MissingSubscription:
    """A student in a group (not on trial) with no subscription left."""

    enrollment_id: int
    student_id: int
    student_number: str
    student_name: str
    group_id: int
    group_title: str
    enrolled_on: str


# The standings, the most urgent first: how a student with several groups reads, and how the
# students list sorts them (repositories/students.ORDERS["standing"]).
STANDINGS_BY_URGENCY = ("ended", "none", "expiring", "active")


def standing(month: Subscription | None) -> str:
    """Where a student stands in a group, from its latest month: active (a month runs, or the
    next one is already made), expiring (ends within 7 days, nothing after), ended (over, not
    renewed) or none (no month left)."""
    if month is None:
        return "none"
    return "active" if month.state in ("active", "upcoming") else month.state


@dataclass(frozen=True)
class NextMonths:
    """A group whose next months a payment can pay ahead: they are renewed with it, from the
    end of the latest month and keeping its cycle, as « Renouveler » does."""

    enrollment_id: int
    group_id: int
    group_title: str  # "M1 · Maths 4AM"
    group_name: str  # "M1": the charge's description names it
    price: int  # the group's price now, the price of each month made
    months: tuple[tuple[str, str], ...]  # (start, end) of each month that can follow, in order


@dataclass(frozen=True)
class SubscriptionLine:
    """A student in a group (not on trial), on the Abonnements page: the latest month (None
    when none is left) and what is left to pay on all of that group's months. Months paid
    ahead only push the end of the period: it starts with the month running today (or the
    next one to come), else with the latest month."""

    enrollment_id: int
    student_id: int
    student_number: str
    student_name: str
    group_id: int
    group_title: str
    month: Subscription | None
    owed: int  # left to pay on the group's months
    period_start: str | None  # None without a month

    @property
    def standing(self) -> str:
        return standing(self.month)


# ----- sessions and attendance -----


@dataclass(frozen=True)
class Holiday:
    id: int
    label: str
    start_date: str
    end_date: str  # last day off, included

    @property
    def days(self) -> int:
        return (date.fromisoformat(self.end_date) - date.fromisoformat(self.start_date)).days + 1


@dataclass(frozen=True)
class Session:
    id: int
    group_id: int
    group_title: str
    group_name: str
    slot_id: int | None
    room_id: int
    room: str
    teacher_id: int
    teacher: str
    scheduled_teacher_id: int | None  # the group's teacher on that date
    date: str
    start_time: str
    end_time: str
    status: str  # 'planned', 'held' or 'cancelled'
    source: str  # 'generated', 'manual' or 'makeup'
    cancellation_reason: str | None
    makeup_of_session_id: int | None
    makeup_id: int | None  # the makeup scheduled for this cancelled session
    makeup_date: str | None  # its date
    makeup_of_date: str | None  # for a makeup: the date of the session it replaces
    attendance_count: int  # students whose attendance is recorded
    expected: int = 0  # students in the group on that date

    @property
    def substitute(self) -> bool:
        """Taught by someone else than the group's teacher that day."""
        return (self.scheduled_teacher_id is not None
                and self.teacher_id != self.scheduled_teacher_id)


ATTENDANCE_STATUSES = ("present", "late", "absent", "excused")


@dataclass(frozen=True)
class RosterLine:
    """A student expected at a session, with what was recorded (None: not yet)."""

    enrollment_id: int
    student_id: int
    student_number: str
    student_name: str
    trial: bool
    not_renewed: bool  # a paid student with no month covering the session date
    status: str | None


@dataclass(frozen=True)
class AttendanceRecord:
    session_id: int
    date: str
    start_time: str
    end_time: str
    group_id: int
    group_title: str
    status: str


@dataclass(frozen=True)
class AttendanceSummary:
    present: int = 0
    late: int = 0
    absent: int = 0
    excused: int = 0

    @property
    def total(self) -> int:
        return self.present + self.late + self.absent + self.excused

    @property
    def rate_bp(self) -> int | None:
        """(present + late) / (present + late + absent), in basis points to the nearest; an
        excused absence is left out. None before any mark counts."""
        counted = self.present + self.late + self.absent
        return None if counted == 0 else ratio_bp(self.present + self.late, counted)


# ----- payments and debt -----

PAYMENT_METHODS = ("cash", "transfer", "cheque", "other")


@dataclass(frozen=True)
class ChargeDue:
    """An open charge with something left to pay."""

    id: int
    kind: str  # 'registration' (the fee) or 'subscription' (a month)
    description: str
    amount: int
    due_date: str
    paid: int  # allocations of payments not voided
    group_id: int | None  # the month's group; None for the fee
    start_date: str | None = None  # a month: its first day; None for the fee
    end_date: str | None = None  # a month: the day after its last day (half-open)
    group_name: str | None = None  # a month: its group's name ("Physique 4AM")

    @property
    def due(self) -> int:
        return max(self.amount - self.paid, 0)


@dataclass(frozen=True)
class Debt:
    """What a student owes on `as_of`. Never stored: derived from charges and payments each
    time."""

    student_id: int
    as_of: str  # 'YYYY-MM-DD'
    charges: tuple[ChargeDue, ...]  # oldest due first, each with due > 0

    @property
    def due(self) -> int:
        """Left to pay on every open charge, months to come included."""
        return sum(c.due for c in self.charges)

    @property
    def overdue(self) -> int:
        """Left to pay on charges already due (due date today or before)."""
        return sum(c.due for c in self.charges if c.due_date <= self.as_of)

    @property
    def owed_now(self) -> int:
        """What is late now: what the debtors list shows."""
        return self.overdue

    @property
    def oldest_overdue(self) -> str | None:
        """The due date of the oldest late charge with something left to pay."""
        late = [c.due_date for c in self.charges if c.due_date <= self.as_of]
        return min(late) if late else None


@dataclass(frozen=True)
class Payment:
    id: int
    student_id: int
    student_number: str
    student_name: str  # "Last First"
    payer_contact_id: int | None
    payer_name: str | None
    amount: int
    method: str  # PAYMENT_METHODS
    paid_at: str  # 'YYYY-MM-DDTHH:MM:SS'
    cashier: str
    receipt_id: int | None
    receipt_number: str | None
    allocated: int
    voided: bool
    void_reason: str | None
    voided_at: str | None
    voided_by: str | None


@dataclass(frozen=True)
class PaymentLine:
    """What a payment paid on one charge."""

    charge_id: int
    description: str
    due_date: str
    amount: int
    # A month's charge: its group (« G2 · math 2AS ») and its dates; None for a fee.
    group_title: str | None = None
    month_start: str | None = None
    month_end: str | None = None


@dataclass(frozen=True)
class Debtor:
    student_id: int
    student_number: str
    student_name: str
    owed_now: int
    due: int  # months to come included
    oldest_overdue: str | None
    days_overdue: int


@dataclass(frozen=True)
class CashReport:
    """Money received on one day, as the drawer saw it, so a day already counted never
    changes: its payments count unless voided that same day (listed apart); a payment voided
    on a later day still counts on its own day, and is taken off the day of its void.
    Refunds are money going out, apart from the payments (never taken off them): « Encaissé »
    (total) is what came in, « Remboursé » what went back that day, « Net encaissé » the
    difference."""

    day: str
    payments: tuple[Payment, ...]  # every payment of the day, voided ones included
    payouts: tuple["Payout", ...] = ()  # teachers paid that day (the director's view only)
    voided_earlier: tuple[Payment, ...] = ()  # payments of earlier days voided on this day
    refunds: tuple["Refund", ...] = ()  # refunds whose money went back that day

    def voided_here(self, p: Payment) -> bool:
        return p.voided and p.voided_at[:10] == self.day

    @property
    def kept(self) -> tuple[Payment, ...]:
        """The day's payments it counts: all but those voided the same day."""
        return tuple(p for p in self.payments if not self.voided_here(p))

    @property
    def total(self) -> int:
        return (sum(p.amount for p in self.kept)
                - sum(p.amount for p in self.voided_earlier))

    @property
    def voided(self) -> tuple[Payment, ...]:
        """The day's payments voided the same day: never counted."""
        return tuple(p for p in self.payments if self.voided_here(p))

    def by_method(self) -> dict[str, int]:
        """Every method, 0 included, in PAYMENT_METHODS order; the earlier payments voided
        on this day taken off their method."""
        totals = dict.fromkeys(PAYMENT_METHODS, 0)
        for p in self.kept:
            totals[p.method] += p.amount
        for p in self.voided_earlier:
            totals[p.method] -= p.amount
        return totals

    def by_cashier(self) -> dict[str, int]:
        """Who took the day's money (the voids of earlier days are apart)."""
        totals: dict[str, int] = {}
        for p in self.kept:
            totals[p.cashier] = totals.get(p.cashier, 0) + p.amount
        return dict(sorted(totals.items()))

    @property
    def paid_to_teachers(self) -> int:
        return sum(p.amount_paid for p in self.payouts)

    @property
    def refunded(self) -> int:
        """« Remboursé »: the money handed back that day."""
        return sum(r.amount for r in self.refunds)

    @property
    def net(self) -> int:
        """« Net encaissé »: received (total) less handed back."""
        return self.total - self.refunded

    def refunded_by_method(self) -> dict[str, int]:
        """Every method, 0 included, in PAYMENT_METHODS order."""
        totals = dict.fromkeys(PAYMENT_METHODS, 0)
        for r in self.refunds:
            totals[r.method] += r.amount
        return totals

    @property
    def cash_in_drawer(self) -> int:
        """Cash received, less cash paid to teachers and cash handed back by refunds: what the
        drawer should hold from the day."""
        cash_out = sum(p.amount_paid for p in self.payouts if p.method == "cash")
        return self.by_method()["cash"] - cash_out - self.refunded_by_method()["cash"]


# ----- refunds -----


@dataclass(frozen=True)
class SessionsLeft:
    """The most a refund of a month can give back, before what was already refunded or asked
    on it: the month's sessions in the timetable (holidays left out), those from
    counted_from on, and their value: price × left ÷ total, rounded down to the dinar. With no
    session at all, the price if counted from the month's first day or before (none of it
    used), else 0. Kept with a request as it was counted then."""

    counted_from: str  # the first day not used (ISO)
    total: int
    left: int
    value: int


REFUND_STATUSES = ("pending", "approved", "rejected", "cancelled", "paid")


@dataclass(frozen=True)
class RefundableMonth:
    """A month paid in full, and the most a new request can ask on it now: the value of its
    sessions left, never more than was paid, less what refunds already hold on it (asked,
    approved or handed back, the archive's included: held). Nothing while the student still
    follows it (still_in)."""

    subscription_id: int
    charge_id: int
    group_title: str
    start_date: str
    end_date: str  # the day after the last day
    price: int
    paid: int
    held: int
    sessions: SessionsLeft | None  # None while the student still follows the month
    max_amount: int
    still_in: str | None = None  # the group they still follow it in (its own, or after a switch)


@dataclass(frozen=True)
class Refund:
    """A refund request on a month, with the count behind its maximum as it was asked."""

    id: int
    charge_id: int
    subscription_id: int
    student_id: int
    student_number: str
    student_name: str  # "Last First"
    group_title: str
    month_start: str
    month_end: str  # the day after the last day
    price: int
    counted_from: str
    sessions_total: int
    sessions_left: int
    sessions_value: int
    max_amount: int
    amount_requested: int
    amount_approved: int | None
    reason: str
    status: str  # REFUND_STATUSES
    requested_by_id: int
    requested_by: str
    requested_at: str
    decided_by: str | None
    decided_at: str | None
    cancelled_by: str | None
    cancelled_at: str | None
    close_reason: str | None  # why rejected or withdrawn
    number: str | None  # RB2026-00001, once paid
    method: str | None
    paid_by: str | None
    paid_at: str | None

    @property
    def amount(self) -> int:
        """What it holds: the amount approved once decided, else the one asked."""
        return self.amount_requested if self.amount_approved is None else self.amount_approved

    @property
    def open(self) -> bool:
        return self.status in ("pending", "approved")


# ----- teacher payouts -----

PAYOUT_STATUSES = ("draft", "approved", "paid")


@dataclass(frozen=True)
class Payout:
    id: int
    teacher_id: int
    teacher: str
    period_start: str  # the first day of its oldest month
    period_end: str  # the date it pays up to
    base_amount: int  # the months' full prices
    amount_due: int  # the teacher's share
    amount_paid: int
    receipt_number: str | None  # PE2026-00001, once paid
    status: str  # PAYOUT_STATUSES
    approved_by: str | None
    approved_at: str | None
    method: str | None
    paid_by: str | None
    paid_at: str | None
    created_at: str
    months: int  # subscription months counted


@dataclass(frozen=True)
class PayoutLine:
    """One group at one rate."""

    id: int
    group_id: int
    group_title: str
    revenue_basis: int
    percentage_bp: int
    amount: int
    months: int
    students: int


@dataclass(frozen=True)
class PayoutMonth:
    """One month a payout counts: whose, which group, at what rate."""

    charge_id: int
    student_number: str
    student_name: str
    group_title: str
    description: str
    accrual_date: str
    amount: int  # the month's full price
    percentage_bp: int

    @property
    def share(self) -> int:
        """The teacher's part of this month alone (the line rounds its total once)."""
        return self.amount * self.percentage_bp // 10000


@dataclass(frozen=True)
class PayoutDue:
    """What a teacher is owed up to a date, before any draft is made."""

    teacher_id: int
    teacher: str
    months: int
    revenue: int
    draft_id: int | None  # their draft, if one is waiting


@dataclass(frozen=True)
class Backup:
    id: int
    file_path: str
    size_bytes: int | None
    checksum: str | None  # sha256 of the file, hex
    type: str  # auto | manual
    status: str  # running | done | failed | verified
    created_at: str
    completed_at: str | None
    verified_at: str | None


# ----- dashboard -----

@dataclass(frozen=True)
class DashboardSession:
    id: int
    start_time: str
    end_time: str
    group_title: str
    room: str
    teacher: str
    status: str


@dataclass(frozen=True)
class GroupFill:
    group_id: int
    title: str
    enrolled: int
    seats: int

    @property
    def rate_bp(self) -> int:
        return self.enrolled * 10000 // self.seats if self.seats else 0


@dataclass(frozen=True)
class DayCash:
    day: str  # 'YYYY-MM-DD'
    amount: int  # payments received that day, not voided
    open: bool  # a session (cancelled ones too) or a payment that day


@dataclass(frozen=True)
class Dashboard:
    today: str
    now: str  # 'HH:MM'
    sessions: tuple[DashboardSession, ...]  # today's, cancelled ones included
    ending: tuple[Subscription, ...]  # months ending within 7 days
    lapsed: int  # months over and not renewed
    debt_total: int  # late, every student
    debtors: int
    top_debtors: tuple[Debtor, ...]
    groups: tuple[GroupFill, ...]  # running groups, fullest first
    # This month's money; None when the user may not see it (receptionist).
    charged: int | None = None  # months and fees starting this month
    settled: int | None = None  # paid on those
    collected: int | None = None  # payments received this month, not voided
    daily: tuple[DayCash, ...] | None = None  # each day of the month so far (director)
    # The rest of the page: debts by age, the day's hours, the weekdays without any slot in
    # the timetable, and today's backup ('verified', 'failed', 'none'; None: not shown).
    oldest_debtors: tuple[Debtor, ...] = ()
    opens_at: str = "08:00"
    closes_at: str = "20:00"
    closed_weekdays: tuple[int, ...] = ()
    backup: str | None = None

    @property
    def sessions_left(self) -> tuple[DashboardSession, ...]:
        """Still to come today (or under way), not cancelled."""
        return tuple(s for s in self.sessions
                     if s.status != "cancelled" and s.end_time > self.now)

    @property
    def next_session(self) -> DashboardSession | None:
        """The next one to start today, not cancelled."""
        return next((s for s in self.sessions
                     if s.status != "cancelled" and s.start_time > self.now), None)

    @property
    def ongoing(self) -> bool:
        return any(s.status != "cancelled" and s.start_time <= self.now < s.end_time
                   for s in self.sessions)

    @property
    def sessions_held(self) -> int:
        return sum(1 for s in self.sessions if s.status != "cancelled")

    @property
    def seats(self) -> int:
        return sum(g.seats for g in self.groups)

    @property
    def enrolled(self) -> int:
        return sum(g.enrolled for g in self.groups)


# ----- reports -----

@dataclass(frozen=True)
class ReportColumn:
    title: str
    kind: str = "text"  # text, number, money (DA), percent (basis points), date (ISO)


@dataclass(frozen=True)
class ReportTile:
    """One of the figures above a report: « Attendu · 412 500 DA »."""

    label: str
    value: int | None  # None: nothing to show (« — »)
    kind: str = "money"  # money, number, percent (basis points)
    note: str = ""  # the small line under the figure


@dataclass(frozen=True)
class ReportChart:
    """bars: a group of bars per label, one per series (« Attendu », « Encaissé »);
    rates: one horizontal bar per label, in basis points."""

    kind: str
    title: str
    labels: tuple[str, ...]
    series: tuple[tuple[str, tuple[int, ...]], ...]


@dataclass(frozen=True)
class Report:
    """A report as the screen, the PDF and the Excel file all show it, in raw values
    (amounts in DA, rates in basis points, ISO dates): the three always agree."""

    key: str  # names its files: 'recettes-par-mois'
    title: str
    period: str  # « Année 2026-2027 », « Du 01/10/2026 au 31/10/2026 »
    columns: tuple[ReportColumn, ...]
    rows: tuple[tuple, ...]
    total: tuple | None = None
    tiles: tuple[ReportTile, ...] = ()
    chart: ReportChart | None = None
    filters: tuple[tuple[str, str], ...] = ()  # (label, value) printed with the report
    note: str = ""  # how it is counted
    row_ids: tuple[int | None, ...] = ()  # what a double-click opens, row by row
    opens: str | None = None  # the page a row opens: 'students', 'groups' or 'teachers'
    tones: tuple[str | None, ...] = ()  # a row to look at: 'danger' (low attendance)
