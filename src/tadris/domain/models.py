from dataclasses import dataclass, field, replace
from datetime import date

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

    @property
    def group_title(self) -> str:
        return f"{self.group_name} · {self.subject} {self.group_level}"

    @property
    def is_live(self) -> bool:
        return self.status in ("trial", "active")

    @property
    def other_level(self) -> bool:
        """In a group of another level: only enrollments made before migration 0010, when the
        director could override the level, can be."""
        return self.group_level != self.registration_level


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

    @property
    def due(self) -> int:
        """What remains to pay (0 once cancelled or for a free group)."""
        if self.status == "cancelled" or self.charge_id is None:
            return 0
        return max(self.price - self.paid, 0)

    @property
    def can_cancel(self) -> bool:
        """Nothing paid on it (V1 has no refunds) and no teacher paid for it yet."""
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


def standing(month: Subscription | None) -> str:
    """Where a student stands in a group, from its latest month: active (a month runs, or the
    next one is already made), expiring (ends within 7 days, nothing after), ended (over, not
    renewed) or none (no month left)."""
    if month is None:
        return "none"
    return "active" if month.state in ("active", "upcoming") else month.state


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
    owed: int  # after the student's credit
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
        """(present + late) / (present + late + absent), in basis points; an excused
        absence is left out. None before any mark counts."""
        counted = self.present + self.late + self.absent
        return None if counted == 0 else (self.present + self.late) * 10000 // counted


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
    credit: int  # money received and not allocated to a charge yet

    @property
    def due(self) -> int:
        """Left to pay on every open charge, months to come included."""
        return sum(c.due for c in self.charges)

    @property
    def overdue(self) -> int:
        """Left to pay on charges already due (due date today or before)."""
        return sum(c.due for c in self.charges if c.due_date <= self.as_of)

    @property
    def balance(self) -> int:
        """Above 0: the student owes it; below 0: the school owes it (credit)."""
        return self.due - self.credit

    @property
    def owed_now(self) -> int:
        """What is late now, after the credit: what the debtors list shows."""
        return max(self.overdue - self.credit, 0)

    @property
    def oldest_overdue(self) -> str | None:
        """The due date of the oldest late charge that the credit does not cover."""
        late = [c.due_date for c in self.after_credit().charges if c.due_date <= self.as_of]
        return min(late) if late else None

    def after_credit(self) -> "Debt":
        """The debt as every screen shows it: the credit pays the oldest charges first, as
        the next payment will. A charge it covers whole is left out, one it covers in part
        counts that part as paid, and `credit` is what is left of it once every charge is
        paid. owed_now and balance stay the same."""
        credit = self.credit
        charges = []
        for c in self.charges:
            used = min(credit, c.due)
            credit -= used
            if used < c.due:
                charges.append(replace(c, paid=c.paid + used))
        return replace(self, charges=tuple(charges), credit=credit)


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

    @property
    def unallocated(self) -> int:
        """The part kept as credit (0 once voided)."""
        return 0 if self.voided else self.amount - self.allocated


@dataclass(frozen=True)
class PaymentLine:
    """What a payment paid on one charge."""

    charge_id: int
    description: str
    due_date: str
    amount: int
    from_credit: int = 0  # on a receipt: the part paid by the credit of earlier payments


@dataclass(frozen=True)
class Debtor:
    student_id: int
    student_number: str
    student_name: str
    owed_now: int
    due: int  # months to come included, after the credit
    credit: int
    oldest_overdue: str | None
    days_overdue: int


@dataclass(frozen=True)
class CashReport:
    """Money received on one day: payments not voided count; voided ones are listed apart."""

    day: str
    payments: tuple[Payment, ...]  # every payment of the day, voided ones included
    payouts: tuple["Payout", ...] = ()  # teachers paid that day (the director's view only)

    @property
    def kept(self) -> tuple[Payment, ...]:
        return tuple(p for p in self.payments if not p.voided)

    @property
    def total(self) -> int:
        return sum(p.amount for p in self.kept)

    @property
    def voided(self) -> tuple[Payment, ...]:
        return tuple(p for p in self.payments if p.voided)

    def by_method(self) -> dict[str, int]:
        """Every method, 0 included, in PAYMENT_METHODS order."""
        totals = dict.fromkeys(PAYMENT_METHODS, 0)
        for p in self.kept:
            totals[p.method] += p.amount
        return totals

    def by_cashier(self) -> dict[str, int]:
        totals: dict[str, int] = {}
        for p in self.kept:
            totals[p.cashier] = totals.get(p.cashier, 0) + p.amount
        return dict(sorted(totals.items()))

    @property
    def paid_to_teachers(self) -> int:
        return sum(p.amount_paid for p in self.payouts)

    @property
    def cash_in_drawer(self) -> int:
        """Cash received minus cash paid to teachers: what the drawer should hold from the
        day."""
        cash_out = sum(p.amount_paid for p in self.payouts if p.method == "cash")
        return self.by_method()["cash"] - cash_out


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
    debt_total: int  # late, after credit, every student
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
