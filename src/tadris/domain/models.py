from dataclasses import dataclass, field
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
    fee_paid: int

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
    paid: int
    in_payout: bool

    @property
    def due(self) -> int:
        """What remains to pay (0 once cancelled or for a free group)."""
        if self.status == "cancelled" or self.charge_id is None:
            return 0
        return max(self.price - self.paid, 0)


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
