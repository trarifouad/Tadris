"""Levels (ordered) and subjects: named lists the director maintains in Paramètres.

kind is "level" or "subject". Deactivating hides an item from new groups; existing groups
keep it. An open level (« Tous niveaux »: calligraphie, arts, …) takes students of every level
in its groups, next to the groups of their own level; it goes back to its own students only
while none of another level is in its groups. A workshop subject (calligraphie, arts, …) is
offered for the groups of an open level, the other subjects for the other levels.
"""

from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError, NotFound, ValidationError
from tadris.core.permissions import require
from tadris.core.text import clean
from tadris.db.errors import atomic
from tadris.domain.models import NamedItem
from tadris.i18n.fr import t
from tadris.repositories import catalog as repo
from tadris.services import audit

KINDS = ("level", "subject")


def _check_kind(kind: str) -> None:
    if kind not in KINDS:
        raise ValueError(kind)


def _require_row(conn, kind: str, item_id: int):
    row = repo.get(conn, kind, item_id)
    if row is None:
        raise NotFound(t[f"{kind}.not_found"])
    return row


def require_active(conn, kind: str, item_id: int):
    """Inside a transaction: the row, if new groups may use it."""
    row = _require_row(conn, kind, item_id)
    if not row["is_active"]:
        raise ValidationError(t[f"{kind}.inactive"])
    return row


def list_items(conn, ctx: UserContext, kind: str, active_only: bool = False) -> list[NamedItem]:
    _check_kind(kind)
    require(ctx, "academic.view")
    items = [
        NamedItem(id=row["id"], name=row["name"], is_active=bool(row["is_active"]),
                  order_index=row["order_index"], group_count=row["group_count"],
                  is_open=bool(row["is_open"]), is_workshop=bool(row["is_workshop"]))
        for row in repo.list_all(conn, kind)
    ]
    return [i for i in items if i.is_active] if active_only else items


def _clean_name(conn, kind: str, name: str, exclude_id: int | None) -> str:
    name = clean(name)
    if not name:
        raise ValidationError(t["name.required"])
    if repo.name_taken(conn, kind, name, exclude_id):
        raise ValidationError(t["name.taken"])
    return name


def create(conn, ctx: UserContext, kind: str, name: str) -> int:
    _check_kind(kind)
    require(ctx, "academic.manage")
    with atomic(conn):
        name = _clean_name(conn, kind, name, None)
        item_id = repo.insert(conn, kind, name)
        audit.log(conn, ctx, f"{kind}.create", repo.TABLES[kind], item_id, new={"name": name})
        return item_id


def rename(conn, ctx: UserContext, kind: str, item_id: int, name: str) -> None:
    _check_kind(kind)
    require(ctx, "academic.manage")
    with atomic(conn):
        row = _require_row(conn, kind, item_id)
        name = _clean_name(conn, kind, name, item_id)
        if name == row["name"]:
            return
        repo.rename(conn, kind, item_id, name)
        audit.log(conn, ctx, f"{kind}.rename", repo.TABLES[kind], item_id,
                  old={"name": row["name"]}, new={"name": name})


def set_active(conn, ctx: UserContext, kind: str, item_id: int, active: bool) -> None:
    _check_kind(kind)
    require(ctx, "academic.manage")
    with atomic(conn):
        row = _require_row(conn, kind, item_id)
        if bool(row["is_active"]) == active:
            return
        repo.set_active(conn, kind, item_id, active)
        audit.log(conn, ctx, f"{kind}.{'activate' if active else 'deactivate'}",
                  repo.TABLES[kind], item_id,
                  old={"is_active": not active}, new={"is_active": active})


def set_open(conn, ctx: UserContext, level_id: int, is_open: bool) -> None:
    """Open the level's groups to students of every level, or keep them to its own."""
    require(ctx, "academic.manage")
    with atomic(conn):
        row = _require_row(conn, "level", level_id)
        if bool(row["is_open"]) == is_open:
            return
        if not is_open:
            others = repo.other_level_students(conn, level_id)
            if others:
                raise BusinessRuleError(t["level.open_in_use"].format(
                    level=row["name"], count=others))
        repo.set_open(conn, level_id, is_open)
        audit.log(conn, ctx, f"level.{'open' if is_open else 'restrict'}", "levels", level_id,
                  old={"is_open": not is_open}, new={"is_open": is_open})


def set_workshop(conn, ctx: UserContext, subject_id: int, is_workshop: bool) -> None:
    """Mark a subject as a workshop, or as a school subject. Existing groups keep it."""
    require(ctx, "academic.manage")
    with atomic(conn):
        row = _require_row(conn, "subject", subject_id)
        if bool(row["is_workshop"]) == is_workshop:
            return
        repo.set_workshop(conn, subject_id, is_workshop)
        audit.log(conn, ctx, f"subject.{'workshop' if is_workshop else 'academic'}",
                  "subjects", subject_id,
                  old={"is_workshop": not is_workshop}, new={"is_workshop": is_workshop})


def move_level(conn, ctx: UserContext, level_id: int, offset: int) -> None:
    """Move a level up (-1) or down (+1) in the display order."""
    require(ctx, "academic.manage")
    with atomic(conn):
        _require_row(conn, "level", level_id)
        ids = [row["id"] for row in repo.list_all(conn, "level")]
        index = ids.index(level_id)
        target = index + offset
        if not 0 <= target < len(ids):
            return
        ids[index], ids[target] = ids[target], ids[index]
        repo.set_order(conn, ids)
        audit.log(conn, ctx, "level.reorder", "levels", level_id, new={"order": ids})
