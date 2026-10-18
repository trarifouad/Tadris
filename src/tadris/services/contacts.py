from dataclasses import dataclass

from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError, NotFound, ValidationError
from tadris.core.permissions import require
from tadris.core.phones import normalize_phone
from tadris.core.text import clean
from tadris.db.errors import atomic
from tadris.domain.models import ContactInput, ContactLink, ExistingContact, StudentContact
from tadris.i18n.fr import t
from tadris.repositories import contacts as repo
from tadris.repositories import students as students_repo
from tadris.services import audit

DEFAULT_LINK = ContactLink()

# Rule: a student with contacts always has exactly one main contact. The first contact
# becomes main; changing the main contact clears and sets it in one transaction.


@dataclass(frozen=True)
class CleanContact:
    full_name: str
    phone: str
    phone_2: str | None
    address: str | None

    def snapshot(self) -> dict:
        return {
            "full_name": self.full_name,
            "phone": self.phone,
            "phone_2": self.phone_2,
            "address": self.address,
        }


def clean_contact(data: ContactInput) -> CleanContact:
    full_name = clean(data.full_name)
    if not full_name:
        raise ValidationError(t["contact.name_required"])
    phone = normalize_phone(data.phone)
    if phone is None:
        raise ValidationError(t["contact.phone_required"])
    phone_2 = normalize_phone(data.phone_2)
    if phone_2 == phone:
        phone_2 = None
    address = clean(data.address) or None
    return CleanContact(full_name, phone, phone_2, address)


def _link_snapshot(relation: str | None, is_main: bool, can_receive_sms: bool) -> dict:
    return {"relation": relation, "is_main": is_main, "can_receive_sms": can_receive_sms}


def _require_student(conn, student_id: int) -> None:
    if students_repo.get(conn, student_id) is None:
        raise NotFound(t["student.not_found"])


def _require_link(conn, student_id: int, contact_id: int):
    row = repo.get_link(conn, student_id, contact_id)
    if row is None:
        raise NotFound(t["contact.not_linked"])
    return row


def _link_in_transaction(conn, ctx, student_id: int, contact_id: int, link: ContactLink) -> None:
    relation = clean(link.relation) or None
    first = repo.count_for_student(conn, student_id) == 0
    is_main = link.is_main or first
    repo.link(conn, student_id, contact_id, relation, False, link.can_receive_sms)
    if is_main:
        repo.set_main(conn, student_id, contact_id)
    audit.log(
        conn, ctx, "contact.link", "student_contacts", student_id,
        new={"contact_id": contact_id, **_link_snapshot(relation, is_main, link.can_receive_sms)},
    )


def add_in_transaction(conn, ctx, student_id: int, values: CleanContact,
                       link: ContactLink) -> int:
    """Insert a new contact and link it, inside the caller's transaction."""
    contact_id = repo.insert(conn, values.full_name, values.phone, values.phone_2, values.address)
    audit.log(conn, ctx, "contact.create", "contacts", contact_id, new=values.snapshot())
    _link_in_transaction(conn, ctx, student_id, contact_id, link)
    return contact_id


def add(conn, ctx: UserContext, student_id: int, data: ContactInput,
        link: ContactLink = DEFAULT_LINK) -> int:
    require(ctx, "student.update")
    values = clean_contact(data)
    with atomic(conn):
        _require_student(conn, student_id)
        return add_in_transaction(conn, ctx, student_id, values, link)


def link_existing(conn, ctx: UserContext, student_id: int, contact_id: int,
                  link: ContactLink = DEFAULT_LINK) -> None:
    """Link a contact already on file (a sibling's parent) to this student."""
    require(ctx, "student.update")
    with atomic(conn):
        _require_student(conn, student_id)
        if repo.get(conn, contact_id) is None:
            raise NotFound(t["not_found"])
        if repo.get_link(conn, student_id, contact_id) is not None:
            raise BusinessRuleError(t["contact.already_linked"])
        _link_in_transaction(conn, ctx, student_id, contact_id, link)


def find_by_phone(conn, ctx: UserContext, phone: str,
                  student_id: int | None = None) -> list[ExistingContact]:
    """Contacts on file with this phone, not already linked to student_id."""
    require(ctx, "student.view")
    try:
        normalized = normalize_phone(phone)
    except ValidationError:
        return []
    if normalized is None:
        return []
    found = []
    for row in repo.with_phone(conn, normalized):
        if student_id is not None and repo.get_link(conn, student_id, row["id"]) is not None:
            continue
        students = tuple(
            f"{s['last_name']} {s['first_name']}" for s in repo.students_of(conn, row["id"])
        )
        found.append(ExistingContact(row["id"], row["full_name"], row["phone"], students))
    return found


def list_for_student(conn, ctx: UserContext, student_id: int) -> list[StudentContact]:
    require(ctx, "student.view")
    _require_student(conn, student_id)
    result = []
    for row in repo.for_student(conn, student_id):
        others = repo.students_of(conn, row["contact_id"], exclude_student_id=student_id)
        result.append(
            StudentContact(
                contact_id=row["contact_id"],
                full_name=row["full_name"],
                phone=row["phone"],
                phone_2=row["phone_2"],
                address=row["address"],
                relation=row["relation"] or "",
                is_main=bool(row["is_main"]),
                can_receive_sms=bool(row["can_receive_sms"]),
                shared_with=tuple(f"{s['last_name']} {s['first_name']}" for s in others),
            )
        )
    return result


def update(conn, ctx: UserContext, student_id: int, contact_id: int, data: ContactInput,
           link: ContactLink) -> None:
    """Edit a contact (shared by every student it is linked to) and its link to this student."""
    require(ctx, "student.update")
    values = clean_contact(data)
    relation = clean(link.relation) or None
    with atomic(conn):
        old_link = _require_link(conn, student_id, contact_id)
        was_main = bool(old_link["is_main"])
        if was_main and not link.is_main:
            raise BusinessRuleError(t["contact.main_required_first"])
        row = repo.get(conn, contact_id)
        old = {key: row[key] for key in ("full_name", "phone", "phone_2", "address")}
        new = values.snapshot()
        if old != new:
            repo.update(conn, contact_id, values.full_name, values.phone, values.phone_2,
                        values.address)
            changed = [key for key in new if old[key] != new[key]]
            audit.log(
                conn, ctx, "contact.update", "contacts", contact_id,
                old={key: old[key] for key in changed},
                new={key: new[key] for key in changed},
            )
        old_l = _link_snapshot(old_link["relation"], was_main,
                               bool(old_link["can_receive_sms"]))
        new_l = _link_snapshot(relation, link.is_main, link.can_receive_sms)
        if old_l != new_l:
            repo.update_link(conn, student_id, contact_id, relation, link.can_receive_sms)
            if link.is_main and not was_main:
                repo.set_main(conn, student_id, contact_id)
            audit.log(
                conn, ctx, "contact.update_link", "student_contacts", student_id,
                old={"contact_id": contact_id, **old_l},
                new={"contact_id": contact_id, **new_l},
            )


def set_main(conn, ctx: UserContext, student_id: int, contact_id: int) -> None:
    require(ctx, "student.update")
    with atomic(conn):
        _require_link(conn, student_id, contact_id)
        previous = repo.main_contact_id(conn, student_id)
        if previous == contact_id:
            return
        repo.set_main(conn, student_id, contact_id)
        audit.log(
            conn, ctx, "contact.set_main", "student_contacts", student_id,
            old={"main_contact_id": previous}, new={"main_contact_id": contact_id},
        )


def unlink(conn, ctx: UserContext, student_id: int, contact_id: int) -> None:
    """Remove the link only; the contact stays on file (it may belong to a sibling)."""
    require(ctx, "student.update")
    with atomic(conn):
        row = _require_link(conn, student_id, contact_id)
        if row["is_main"] and repo.count_for_student(conn, student_id) > 1:
            raise BusinessRuleError(t["contact.main_required_first"])
        repo.unlink(conn, student_id, contact_id)
        audit.log(
            conn, ctx, "contact.unlink", "student_contacts", student_id,
            old={
                "contact_id": contact_id,
                **_link_snapshot(row["relation"], bool(row["is_main"]),
                                 bool(row["can_receive_sms"])),
            },
        )
