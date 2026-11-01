import secrets
import sqlite3
import time

from tadris.core.context import UserContext
from tadris.core.errors import NotFound, PermissionDenied, ValidationError
from tadris.core.permissions import require
from tadris.core.security import hash_password, verify_password
from tadris.db.connection import transaction
from tadris.db.errors import atomic, translate
from tadris.i18n.fr import t
from tadris.services import audit

MIN_PASSWORD_LEN = 8
FAILS_BEFORE_DELAY = 3
DELAY_SECONDS = 1.5
# The director's recovery code: only its hash is kept, in settings (not one of the keys
# Paramètres edits). 16 characters read from paper: no 0/O nor 1/I/L.
RECOVERY_KEY = "auth.recovery"
RECOVERY_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
RECOVERY_LENGTH, RECOVERY_GROUP = 16, 4

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
    with atomic(conn):
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


def logout(conn, ctx: UserContext) -> None:
    """The user leaves the workstation: written to the audit log (who and when)."""
    with transaction(conn):
        audit.log(conn, ctx, "user.logout", "users", ctx.user_id)


def list_users(conn, ctx: UserContext) -> list[dict]:
    require(ctx, "user.view")
    rows = conn.execute(
        "SELECT id, username, role, status, created_at FROM users ORDER BY username"
    ).fetchall()
    return [dict(row) for row in rows]


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


def disable_user(conn, ctx: UserContext, user_id: int) -> None:
    """Someone who left: they can no longer log in; what they did stays in the history.
    Never one's own account, so the director doing it stays active: the app always keeps
    a director who can log in."""
    if user_id == ctx.user_id:
        require(ctx, "user.disable")
        raise ValidationError(t["auth.cannot_disable_self"])
    _set_status(conn, ctx, user_id, "disabled")


def enable_user(conn, ctx: UserContext, user_id: int) -> None:
    _set_status(conn, ctx, user_id, "active")


def new_recovery_code(conn, ctx: UserContext) -> str:
    """A code the director writes down for the day a director's password is forgotten
    (« Mot de passe oublié ? » at login). Shown once: only its hash is kept. A new code
    replaces the old one. 'K7QM-4XRP-9TBW-2HDN'."""
    require(ctx, "user.recovery")
    raw = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(RECOVERY_LENGTH))
    with atomic(conn):
        conn.execute(
            """
            INSERT INTO settings(key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE
               SET value = excluded.value,
                   updated_at = strftime('%Y-%m-%dT%H:%M:%S','now','localtime')
            """,
            (RECOVERY_KEY, hash_password(raw)),
        )
        audit.log(conn, ctx, "user.recovery_code", "users", ctx.user_id)
    return "-".join(raw[i:i + RECOVERY_GROUP] for i in range(0, RECOVERY_LENGTH, RECOVERY_GROUP))


def recovery_code_made(conn, ctx: UserContext) -> str | None:
    """When the current code was made ('YYYY-MM-DDTHH:MM:SS'); None when there is none."""
    require(ctx, "user.recovery")
    row = conn.execute("SELECT updated_at FROM settings WHERE key = ?",
                       (RECOVERY_KEY,)).fetchone()
    return None if row is None else row[0]


def recover(conn, username: str, code: str, new_password: str) -> UserContext:
    """« Mot de passe oublié ? »: an active director chooses a new password with the
    recovery code, which is then used up (a new one is made in Paramètres). The same message
    whatever is wrong (name, role, code), and the same delay as login after repeated
    failures. Returns the director, logged in."""
    username = username.strip()
    if len(new_password) < MIN_PASSWORD_LEN:
        raise ValidationError(t["auth.password_short"])
    tries = f"recover:{username}"
    if _failed.get(tries, 0) >= FAILS_BEFORE_DELAY:
        _sleeper(DELAY_SECONDS)
    row = conn.execute(
        "SELECT id, username, role, status FROM users WHERE username = ?", (username,)
    ).fetchone()
    stored = conn.execute("SELECT value FROM settings WHERE key = ?",
                          (RECOVERY_KEY,)).fetchone()
    typed = "".join(ch for ch in code.upper() if ch.isalnum())  # dashes, spaces, case
    if (row is None or row["role"] != "director" or row["status"] != "active"
            or stored is None or not verify_password(typed, stored[0])):
        _failed[tries] = _failed.get(tries, 0) + 1
        raise PermissionDenied(t["auth.recovery_invalid"])
    _failed[tries] = 0
    ctx = _ctx_from_row(row)
    with atomic(conn):
        conn.execute(
            """
            UPDATE users
               SET password_hash = ?,
                   updated_at = strftime('%Y-%m-%dT%H:%M:%S','now','localtime')
             WHERE id = ?
            """,
            (hash_password(new_password), ctx.user_id),
        )
        conn.execute("DELETE FROM settings WHERE key = ?", (RECOVERY_KEY,))
        audit.log(conn, ctx, "user.recover", "users", ctx.user_id)
    return ctx


def _set_status(conn, ctx: UserContext, user_id: int, status: str) -> None:
    require(ctx, "user.disable")
    row = conn.execute("SELECT status FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise NotFound(t["not_found"])
    if row["status"] == status:
        return
    with atomic(conn):
        conn.execute(
            """
            UPDATE users
               SET status = ?,
                   updated_at = strftime('%Y-%m-%dT%H:%M:%S','now','localtime')
             WHERE id = ?
            """,
            (status, user_id),
        )
        audit.log(conn, ctx, "user.disable" if status == "disabled" else "user.enable",
                  "users", user_id, old={"status": row["status"]}, new={"status": status})
