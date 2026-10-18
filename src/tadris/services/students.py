import re

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError, NotFound, ValidationError
from tadris.core.permissions import require
from tadris.core.phones import digits, normalize_phone
from tadris.core.text import clean, fold
from tadris.db.errors import atomic
from tadris.domain.models import (
    ContactInput,
    ContactLink,
    DuplicateMatch,
    Student,
    StudentInput,
    StudentListItem,
)
from tadris.i18n.fr import t
from tadris.repositories import students as repo
from tadris.services import audit, counters
from tadris.services import contacts as contacts_service

STATUSES = ("active", "inactive")
# A query made only of digits and separators is a student number or a phone, kept whole.
_NUMERIC_QUERY = re.compile(r"[0-9٠-٩\s+.\-/]+")
MIN_PHONE_DIGITS = 3


def _clean_input(data: StudentInput) -> tuple[str, str, str | None, str | None]:
    first_name = clean(data.first_name)
    last_name = clean(data.last_name)
    if not last_name:
        raise ValidationError(t["student.last_name_required"])
    if not first_name:
        raise ValidationError(t["student.first_name_required"])
    if data.birth_date is not None and data.birth_date > dates.today():
        raise ValidationError(t["student.birth_date_future"])
    birth = None if data.birth_date is None else dates.iso(data.birth_date)
    notes = data.notes.strip() or None
    return first_name, last_name, birth, notes


def _snapshot(first_name, last_name, birth, notes) -> dict:
    return {"first_name": first_name, "last_name": last_name, "birth_date": birth, "notes": notes}


def _to_student(row) -> Student:
    return Student(
        id=row["id"],
        student_number=row["student_number"],
        first_name=row["first_name"],
        last_name=row["last_name"],
        birth_date=row["birth_date"],
        status=row["status"],
        notes=row["notes"] or "",
        created_at=row["created_at"],
    )


def _require_row(conn, student_id: int):
    row = repo.get(conn, student_id)
    if row is None:
        raise NotFound(t["student.not_found"])
    return row


def next_number(conn) -> str:
    """Next 'YYYY-NNNN' number. Call inside the transaction that inserts the student."""
    year = dates.today().year
    return f"{year}-{counters.next_value(conn, f'student:{year}'):04d}"


def get(conn, ctx: UserContext, student_id: int) -> Student:
    require(ctx, "student.view")
    return _to_student(_require_row(conn, student_id))


def create(
    conn,
    ctx: UserContext,
    data: StudentInput,
    contact: ContactInput | None = None,
    link: ContactLink | None = None,
) -> int:
    """Create a student, optionally with a first contact, which becomes the main contact."""
    require(ctx, "student.create")
    first_name, last_name, birth, notes = _clean_input(data)
    if contact is not None:
        contact_values = contacts_service.clean_contact(contact)
    with atomic(conn):
        number = next_number(conn)
        student_id = repo.insert(conn, number, first_name, last_name, birth, notes)
        audit.log(
            conn, ctx, "student.create", "students", student_id,
            new={"student_number": number, **_snapshot(first_name, last_name, birth, notes)},
        )
        if contact is not None:
            contacts_service.add_in_transaction(
                conn, ctx, student_id, contact_values, link or ContactLink()
            )
        return student_id


def update(conn, ctx: UserContext, student_id: int, data: StudentInput) -> None:
    require(ctx, "student.update")
    first_name, last_name, birth, notes = _clean_input(data)
    with atomic(conn):
        row = _require_row(conn, student_id)
        old = _snapshot(row["first_name"], row["last_name"], row["birth_date"], row["notes"])
        new = _snapshot(first_name, last_name, birth, notes)
        if old == new:
            return
        repo.update(conn, student_id, first_name, last_name, birth, notes)
        changed = [key for key in new if old[key] != new[key]]
        audit.log(
            conn, ctx, "student.update", "students", student_id,
            old={key: old[key] for key in changed},
            new={key: new[key] for key in changed},
        )


def deactivate(conn, ctx: UserContext, student_id: int) -> None:
    """Students are never deleted. Deactivation hides them from the default list."""
    require(ctx, "student.deactivate")
    with atomic(conn):
        row = _require_row(conn, student_id)
        if row["status"] == "inactive":
            raise BusinessRuleError(t["student.already_inactive"])
        if repo.count_live_enrollments(conn, student_id) > 0:
            raise BusinessRuleError(t["student.has_live_enrollments"])
        repo.set_status(conn, student_id, "inactive")
        audit.log(
            conn, ctx, "student.deactivate", "students", student_id,
            old={"status": "active"}, new={"status": "inactive"},
        )


def reactivate(conn, ctx: UserContext, student_id: int) -> None:
    require(ctx, "student.reactivate")
    with atomic(conn):
        row = _require_row(conn, student_id)
        if row["status"] == "active":
            raise BusinessRuleError(t["student.already_active"])
        repo.set_status(conn, student_id, "active")
        audit.log(
            conn, ctx, "student.reactivate", "students", student_id,
            old={"status": "inactive"}, new={"status": "active"},
        )


def _terms(query: str) -> list[tuple[str, str | None]]:
    query = clean(query)
    if not query:
        return []
    if _NUMERIC_QUERY.fullmatch(query):
        number = digits(query)
        # Keep the dash for student numbers ("2026-0001"); match phones on digits only.
        text = fold(query.replace(" ", ""))
        return [(text, number if len(number) >= MIN_PHONE_DIGITS else None)]
    return [
        (fold(word), digits(word) if len(digits(word)) >= MIN_PHONE_DIGITS else None)
        for word in query.split()
    ]


def search(
    conn, ctx: UserContext, query: str = "", status: str | None = "active"
) -> list[StudentListItem]:
    """Find students by name, number or contact phone. status=None returns every status."""
    require(ctx, "student.view")
    if status is not None and status not in STATUSES:
        raise ValidationError(t["validation.generic"])
    rows = repo.search(conn, _terms(query), status)
    return [StudentListItem(**dict(row)) for row in rows]


def possible_duplicates(
    conn,
    ctx: UserContext,
    data: StudentInput,
    phones: tuple[str, ...] = (),
    exclude_id: int | None = None,
) -> list[DuplicateMatch]:
    """Warn, never block: same name (and birth date when both are known) or a shared phone.

    A shared phone often means a sibling, which the front desk confirms.
    """
    require(ctx, "student.view")
    first_name, last_name = clean(data.first_name), clean(data.last_name)
    matches: dict[int, DuplicateMatch] = {}
    if first_name and last_name:
        birth = None if data.birth_date is None else dates.iso(data.birth_date)
        for row in repo.same_name(conn, first_name, last_name, birth, exclude_id):
            matches[row["id"]] = _match(row, "name")
    normalized = []
    for phone in phones:
        try:
            if value := normalize_phone(phone):
                normalized.append(value)
        except ValidationError:
            continue  # the form reports invalid phones when it saves
    for row in repo.sharing_phone(conn, normalized, exclude_id):
        matches.setdefault(row["id"], _match(row, "phone"))
    return list(matches.values())


def _match(row, reason: str) -> DuplicateMatch:
    return DuplicateMatch(
        student_id=row["id"],
        student_number=row["student_number"],
        full_name=f"{row['last_name']} {row['first_name']}",
        reason=reason,
    )

