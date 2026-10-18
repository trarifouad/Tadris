from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError, NotFound, ValidationError
from tadris.core.permissions import require
from tadris.core.text import clean
from tadris.db.errors import atomic
from tadris.domain.models import Room
from tadris.i18n.fr import t
from tadris.repositories import rooms as repo
from tadris.services import audit


def _require_row(conn, room_id: int):
    row = repo.get(conn, room_id)
    if row is None:
        raise NotFound(t["room.not_found"])
    return row


def require_active(conn, room_id: int):
    row = _require_row(conn, room_id)
    if row["status"] != "active":
        raise ValidationError(t["room.inactive"])
    return row


def list_rooms(conn, ctx: UserContext, active_only: bool = False) -> list[Room]:
    require(ctx, "academic.view")
    rooms = [
        Room(id=r["id"], name=r["name"], capacity=r["capacity"], status=r["status"],
             slot_count=r["slot_count"])
        for r in repo.list_all(conn, dates.iso(dates.today()))
    ]
    return [r for r in rooms if r.status == "active"] if active_only else rooms


def _validate(conn, name: str, capacity: int, exclude_id: int | None) -> str:
    name = clean(name)
    if not name:
        raise ValidationError(t["name.required"])
    if capacity < 1:
        raise ValidationError(t["room.capacity_invalid"])
    if repo.name_taken(conn, name, exclude_id):
        raise ValidationError(t["name.taken"])
    return name


def create(conn, ctx: UserContext, name: str, capacity: int) -> int:
    require(ctx, "academic.manage")
    with atomic(conn):
        name = _validate(conn, name, capacity, None)
        room_id = repo.insert(conn, name, capacity)
        audit.log(conn, ctx, "room.create", "rooms", room_id,
                  new={"name": name, "capacity": capacity})
        return room_id


def update(conn, ctx: UserContext, room_id: int, name: str, capacity: int) -> None:
    """A room cannot shrink below a group that uses it (trigger)."""
    require(ctx, "academic.manage")
    with atomic(conn):
        row = _require_row(conn, room_id)
        name = _validate(conn, name, capacity, room_id)
        old = {"name": row["name"], "capacity": row["capacity"]}
        new = {"name": name, "capacity": capacity}
        if old == new:
            return
        repo.update(conn, room_id, name, capacity)
        audit.log(conn, ctx, "room.update", "rooms", room_id, old=old, new=new)


def set_active(conn, ctx: UserContext, room_id: int, active: bool) -> None:
    require(ctx, "academic.manage")
    with atomic(conn):
        row = _require_row(conn, room_id)
        status = "active" if active else "inactive"
        if row["status"] == status:
            return
        if not active and repo.live_slot_count(conn, room_id, dates.iso(dates.today())):
            raise BusinessRuleError(t["room.in_use"])
        repo.set_status(conn, room_id, status)
        audit.log(conn, ctx, f"room.{'activate' if active else 'deactivate'}", "rooms",
                  room_id, old={"status": row["status"]}, new={"status": status})
