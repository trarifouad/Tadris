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
