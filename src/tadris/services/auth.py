import sqlite3
import time

from tadris.core.context import UserContext
from tadris.core.errors import PermissionDenied, ValidationError
from tadris.core.permissions import require
from tadris.core.security import hash_password, verify_password
from tadris.db.connection import transaction
from tadris.db.errors import translate
from tadris.i18n.fr import t
from tadris.services import audit

MIN_PASSWORD_LEN = 8
FAILS_BEFORE_DELAY = 3
DELAY_SECONDS = 1.5

_failed: dict[str, int] = {}
_sleeper = time.sleep


def _reset_failures() -> None:
    _failed.clear()


def user_count(conn) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])


def _ctx_from_row(row) -> UserContext:
    return UserContext(user_id=row["id"], username=row["username"], role=row["role"])


def bootstrap_director(conn, username: str, password: str, school_name: str) -> UserContext:
    username = username.strip()
    school_name = school_name.strip()
    if user_count(conn) > 0:
        raise ValidationError(t["auth.already_initialized"])
    if not username:
        raise ValidationError(t["auth.username_required"])
    if not school_name:
        raise ValidationError(t["auth.school_name_required"])
    if len(password) < MIN_PASSWORD_LEN:
        raise ValidationError(t["auth.password_short"])
    try:
        with transaction(conn):
            # Re-check under the write lock: another first-run window may have finished.
            if user_count(conn) > 0:
                raise ValidationError(t["auth.already_initialized"])
            conn.execute(
                "INSERT INTO users(username, password_hash, role) VALUES (?, ?, 'director')",
                (username, hash_password(password)),
            )
            user_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
            conn.execute(
                "INSERT INTO settings(key, value) VALUES ('school.name', ?)",
                (school_name,),
            )
            ctx = UserContext(user_id=user_id, username=username, role="director")
            audit.log(
                conn,
                ctx,
                "user.bootstrap",
                "users",
                user_id,
                new={"username": username, "role": "director"},
            )
            return ctx
    except sqlite3.IntegrityError as exc:
        raise translate(exc) from exc


def login(conn, username: str, password: str) -> UserContext:
    username = username.strip()
    if _failed.get(username, 0) >= FAILS_BEFORE_DELAY:
        _sleeper(DELAY_SECONDS)
    row = conn.execute(
        "SELECT id, username, password_hash, role, status FROM users WHERE username = ?",
        (username,),
    ).fetchone()
    if row is None or not verify_password(password, row["password_hash"]):
        _failed[username] = _failed.get(username, 0) + 1
        raise PermissionDenied(t["auth.invalid"])
    if row["status"] != "active":
        raise PermissionDenied(t["auth.disabled"])
    _failed[username] = 0
    return _ctx_from_row(row)


def create_user(conn, ctx: UserContext, username: str, password: str, role: str) -> int:
    require(ctx, "user.create")
    username = username.strip()
    if not username:
        raise ValidationError(t["auth.username_required"])
    if len(password) < MIN_PASSWORD_LEN:
        raise ValidationError(t["auth.password_short"])
    if role not in ("director", "receptionist"):
        raise ValidationError(t["validation.generic"])
    try:
        with transaction(conn):
            conn.execute(
                "INSERT INTO users(username, password_hash, role) VALUES (?, ?, ?)",
                (username, hash_password(password), role),
            )
            user_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
            audit.log(
                conn,
                ctx,
                "user.create",
                "users",
                user_id,
                new={"username": username, "role": role},
            )
            return user_id
    except sqlite3.IntegrityError as exc:
        if "UNIQUE constraint failed: users.username" in str(exc):
            raise ValidationError(t["auth.username_taken"]) from exc
        raise translate(exc) from exc


def change_password(
    conn,
    ctx: UserContext,
    user_id: int,
    new_password: str,
    current_password: str | None = None,
) -> None:
    if len(new_password) < MIN_PASSWORD_LEN:
        raise ValidationError(t["auth.password_short"])
    row = conn.execute(
        "SELECT id, username, password_hash FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if row is None:
        from tadris.core.errors import NotFound

        raise NotFound(t["not_found"])
    if ctx.user_id != user_id:
        require(ctx, "user.create")
    else:
        if current_password is None or not verify_password(current_password, row["password_hash"]):
            raise PermissionDenied(t["auth.wrong_current_password"])
    with transaction(conn):
        conn.execute(
            """
            UPDATE users
               SET password_hash = ?,
                   updated_at = strftime('%Y-%m-%dT%H:%M:%S','now','localtime')
             WHERE id = ?
            """,
            (hash_password(new_password), user_id),
        )
        audit.log(conn, ctx, "user.change_password", "users", user_id)
