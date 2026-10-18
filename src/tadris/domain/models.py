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
