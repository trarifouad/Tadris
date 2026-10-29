"""Who a WhatsApp message goes to: the contacts of a student, or of every student live in a
group. Only contacts who accept messages; a parent of two students of the group gets one
message naming both. The desk sends from WhatsApp itself.

A class group can also be linked to a WhatsApp group the desk created (Tadris cannot create
one): its invite link is kept, the parents are invited once each, and an announcement then
goes to the whole WhatsApp group in one send."""

from dataclasses import dataclass

from tadris.core import dates, whatsapp
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError, ValidationError
from tadris.core.permissions import require
from tadris.core.phones import is_mobile
from tadris.db.errors import atomic
from tadris.i18n.fr import t
from tadris.repositories import contacts as repo
from tadris.repositories import messages as repo_messages
from tadris.services import audit, groups, students


@dataclass(frozen=True)
class Recipient:
    contact_id: int
    full_name: str
    relation: str | None
    phone: str | None  # the first mobile of the contact; None: landlines only, no WhatsApp
    students: tuple[str, ...]  # first names, for {élève}


def _recipients(rows) -> list[Recipient]:
    by_contact: dict[int, list] = {}
    for row in rows:
        by_contact.setdefault(row["contact_id"], []).append(row)
    found = []
    for contact_id, own in by_contact.items():
        first = own[0]
        phone = next((p for p in (first["phone"], first["phone_2"]) if is_mobile(p)), None)
        names = tuple(dict.fromkeys(row["first_name"] for row in own))
        found.append(Recipient(contact_id, first["full_name"], first["relation"], phone, names))
    return found


def for_student(conn, ctx: UserContext, student_id: int) -> list[Recipient]:
    require(ctx, "message.send")
    students.get(conn, ctx, student_id)  # NotFound
    return _recipients(repo.reachable_for_student(conn, student_id))


def for_group(conn, ctx: UserContext, group_id: int) -> list[Recipient]:
    require(ctx, "message.send")
    groups.get(conn, ctx, group_id)  # NotFound
    return _recipients(repo.reachable_in_group(conn, group_id))


# ----- the WhatsApp group linked to a class group -----

def group_code(conn, ctx: UserContext, group_id: int) -> str | None:
    """The invite code of the group's WhatsApp group; None: not linked yet."""
    require(ctx, "message.send")
    groups.get(conn, ctx, group_id)  # NotFound
    return repo_messages.group_code(conn, group_id)


def link_group(conn, ctx: UserContext, group_id: int, link: str) -> str:
    """The WhatsApp group the desk created for this group, by its invite link. A new link
    (the old one revoked) forgets who was invited. Returns the code."""
    require(ctx, "message.send")
    code = whatsapp.invite_code(link)
    if code is None:
        raise ValidationError(t["whatsapp_group.link_invalid"])
    with atomic(conn):
        groups.get(conn, ctx, group_id)  # NotFound
        old = repo_messages.group_code(conn, group_id)
        if code == old:
            return code
        repo_messages.set_group_code(conn, group_id, code)
        repo_messages.clear_invites(conn, group_id)
        audit.log(conn, ctx, "whatsapp_group.link", "class_groups", group_id,
                  old={"whatsapp_code": old}, new={"whatsapp_code": code})
    return code


def unlink_group(conn, ctx: UserContext, group_id: int) -> None:
    require(ctx, "message.send")
    with atomic(conn):
        groups.get(conn, ctx, group_id)  # NotFound
        old = repo_messages.group_code(conn, group_id)
        if old is None:
            return
        repo_messages.set_group_code(conn, group_id, None)
        repo_messages.clear_invites(conn, group_id)
        audit.log(conn, ctx, "whatsapp_group.unlink", "class_groups", group_id,
                  old={"whatsapp_code": old}, new={"whatsapp_code": None})


def mark_invited(conn, ctx: UserContext, group_id: int, contact_id: int) -> None:
    """The parent's chat was opened with the invitation."""
    require(ctx, "message.send")
    with atomic(conn):
        if repo_messages.group_code(conn, group_id) is None:
            raise BusinessRuleError(t["whatsapp_group.not_linked"])
        repo_messages.add_invite(conn, group_id, contact_id, dates.iso(dates.today()))


def invited(conn, ctx: UserContext, group_id: int) -> dict[int, str]:
    """{contact_id: invited_at} of the parents already invited to the WhatsApp group."""
    require(ctx, "message.send")
    return repo_messages.invites(conn, group_id)
