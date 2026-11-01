import json
import re

import pytest

from tadris.core.errors import NotFound, PermissionDenied, ValidationError
from tadris.i18n.fr import t
from tadris.services import auth


@pytest.fixture
def director(conn):
    return auth.bootstrap_director(conn, "directeur", "password1", "École Ennour")


@pytest.fixture
def receptionist(conn, director):
    auth.create_user(conn, director, "accueil", "password2", "receptionist")
    return auth.login(conn, "accueil", "password2")


@pytest.fixture
def sleeps(monkeypatch):
    calls = []
    monkeypatch.setattr(auth, "_sleeper", calls.append)
    return calls


# ----- first run -----

def test_bootstrap_creates_director_school_name_and_audit(conn, director):
    assert director.role == "director"
    assert auth.user_count(conn) == 1
    name = conn.execute("SELECT value FROM settings WHERE key = 'school.name'").fetchone()[0]
    assert name == "École Ennour"
    row = conn.execute("SELECT user_id, action, new_value FROM audit_log").fetchone()
    assert row["user_id"] == director.user_id
    assert row["action"] == "user.bootstrap"
    assert json.loads(row["new_value"]) == {"username": "directeur", "role": "director"}


def test_bootstrap_only_once(conn, director):
    with pytest.raises(ValidationError) as exc:
        auth.bootstrap_director(conn, "autre", "password1", "École")
    assert exc.value.message == t["auth.already_initialized"]


def test_bootstrap_rechecks_inside_the_transaction(conn, monkeypatch):
    # Two first-run windows: another one finishes between our check and our write.
    real_atomic = auth.atomic
    state = {"raced": False}

    def racing_atomic(c):
        if not state["raced"]:
            state["raced"] = True
            auth.bootstrap_director(c, "premier", "password1", "École A")
        return real_atomic(c)

    monkeypatch.setattr(auth, "atomic", racing_atomic)
    with pytest.raises(ValidationError) as exc:
        auth.bootstrap_director(conn, "second", "password1", "École B")
    assert exc.value.message == t["auth.already_initialized"]
    assert auth.user_count(conn) == 1


@pytest.mark.parametrize("username, password, school, key", [
    ("  ", "password1", "École", "auth.username_required"),
    ("dir", "short", "École", "auth.password_short"),
    ("dir", "password1", "   ", "auth.school_name_required"),
])
def test_bootstrap_validation(conn, username, password, school, key):
    with pytest.raises(ValidationError) as exc:
        auth.bootstrap_director(conn, username, password, school)
    assert exc.value.message == t[key]
    assert auth.user_count(conn) == 0


# ----- login -----

def test_login_returns_context(conn, director):
    ctx = auth.login(conn, "  directeur ", "password1")
    assert (ctx.user_id, ctx.username, ctx.role) == (director.user_id, "directeur", "director")


@pytest.mark.parametrize("username, password", [("directeur", "wrong-pass"), ("personne", "password1")])
def test_login_rejects_wrong_password_and_unknown_user_with_same_message(
    conn, director, username, password
):
    with pytest.raises(PermissionDenied) as exc:
        auth.login(conn, username, password)
    assert exc.value.message == t["auth.invalid"]


def test_login_rejects_disabled_user(conn, receptionist):
    conn.execute("UPDATE users SET status = 'disabled' WHERE id = ?", (receptionist.user_id,))
    with pytest.raises(PermissionDenied) as exc:
        auth.login(conn, "accueil", "password2")
    assert exc.value.message == t["auth.disabled"]


def test_disabled_status_not_revealed_without_the_right_password(conn, receptionist):
    conn.execute("UPDATE users SET status = 'disabled' WHERE id = ?", (receptionist.user_id,))
    with pytest.raises(PermissionDenied) as exc:
        auth.login(conn, "accueil", "wrong-pass")
    assert exc.value.message == t["auth.invalid"]


def test_delay_after_three_failures_and_reset_on_success(conn, director, sleeps):
    for _ in range(auth.FAILS_BEFORE_DELAY):
        with pytest.raises(PermissionDenied):
            auth.login(conn, "directeur", "wrong-pass")
    assert sleeps == []

    with pytest.raises(PermissionDenied):
        auth.login(conn, "directeur", "wrong-pass")
    assert sleeps == [auth.DELAY_SECONDS]

    auth.login(conn, "directeur", "password1")  # delayed, then succeeds
    sleeps.clear()
    auth.login(conn, "directeur", "password1")
    assert sleeps == []


def test_failures_never_lock_the_account(conn, director, sleeps):
    for _ in range(10):
        with pytest.raises(PermissionDenied):
            auth.login(conn, "directeur", "wrong-pass")
    assert auth.login(conn, "directeur", "password1").role == "director"


# ----- users -----

def test_create_user_and_audit(conn, director):
    user_id = auth.create_user(conn, director, " accueil ", "password2", "receptionist")
    row = conn.execute("SELECT username, role, status FROM users WHERE id = ?", (user_id,)).fetchone()
    assert tuple(row) == ("accueil", "receptionist", "active")
    audit = conn.execute(
        "SELECT entity_id FROM audit_log WHERE action = 'user.create'"
    ).fetchone()
    assert audit["entity_id"] == user_id


def test_list_users_sorted_with_roles(conn, director, receptionist):
    users = auth.list_users(conn, director)
    assert [(u["username"], u["role"], u["status"]) for u in users] == [
        ("accueil", "receptionist", "active"),
        ("directeur", "director", "active"),
    ]
    assert "password_hash" not in users[0]


def test_receptionist_cannot_list_users(conn, receptionist):
    with pytest.raises(PermissionDenied):
        auth.list_users(conn, receptionist)


def test_receptionist_cannot_create_users(conn, receptionist):
    with pytest.raises(PermissionDenied):
        auth.create_user(conn, receptionist, "autre", "password3", "receptionist")


def test_create_user_duplicate_username(conn, director):
    with pytest.raises(ValidationError) as exc:
        auth.create_user(conn, director, "directeur", "password2", "receptionist")
    assert exc.value.message == t["auth.username_taken"]


@pytest.mark.parametrize("username, password, role, key", [
    ("", "password2", "receptionist", "auth.username_required"),
    ("accueil", "short", "receptionist", "auth.password_short"),
    ("accueil", "password2", "teacher", "validation.generic"),
])
def test_create_user_validation(conn, director, username, password, role, key):
    with pytest.raises(ValidationError) as exc:
        auth.create_user(conn, director, username, password, role)
    assert exc.value.message == t[key]


# ----- passwords -----

def test_change_own_password(conn, receptionist):
    auth.change_password(conn, receptionist, receptionist.user_id, "nouveau-pass", "password2")
    assert auth.login(conn, "accueil", "nouveau-pass").user_id == receptionist.user_id
    with pytest.raises(PermissionDenied):
        auth.login(conn, "accueil", "password2")


@pytest.mark.parametrize("current", [None, "wrong-pass"])
def test_change_own_password_needs_current_password(conn, receptionist, current):
    with pytest.raises(PermissionDenied) as exc:
        auth.change_password(conn, receptionist, receptionist.user_id, "nouveau-pass", current)
    assert exc.value.message == t["auth.wrong_current_password"]


def test_director_resets_another_users_password(conn, director, receptionist):
    auth.change_password(conn, director, receptionist.user_id, "reinit-pass")
    assert auth.login(conn, "accueil", "reinit-pass").user_id == receptionist.user_id
    row = conn.execute(
        "SELECT user_id, entity_id FROM audit_log WHERE action = 'user.change_password'"
    ).fetchone()
    assert (row["user_id"], row["entity_id"]) == (director.user_id, receptionist.user_id)


def test_receptionist_cannot_reset_another_users_password(conn, director, receptionist):
    with pytest.raises(PermissionDenied):
        auth.change_password(conn, receptionist, director.user_id, "pirate-pass")


def test_change_password_validation(conn, director):
    with pytest.raises(ValidationError):
        auth.change_password(conn, director, director.user_id, "short", "password1")
    with pytest.raises(NotFound):
        auth.change_password(conn, director, 999, "nouveau-pass")


# ----- disabling an account -----

def test_disabled_user_cannot_log_in_and_it_is_audited(conn, director, receptionist):
    auth.disable_user(conn, director, receptionist.user_id)
    with pytest.raises(PermissionDenied) as exc:
        auth.login(conn, "accueil", "password2")
    assert exc.value.message == t["auth.disabled"]
    row = conn.execute(
        "SELECT user_id, entity_id, old_value, new_value FROM audit_log "
        "WHERE action = 'user.disable'"
    ).fetchone()
    assert (row["user_id"], row["entity_id"]) == (director.user_id, receptionist.user_id)
    assert json.loads(row["old_value"]) == {"status": "active"}
    assert json.loads(row["new_value"]) == {"status": "disabled"}


def test_enabled_again_the_user_logs_in(conn, director, receptionist):
    auth.disable_user(conn, director, receptionist.user_id)
    auth.enable_user(conn, director, receptionist.user_id)
    assert auth.login(conn, "accueil", "password2").user_id == receptionist.user_id
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'user.enable'"
                        ).fetchone()[0] == 1


def test_disabling_twice_changes_nothing_more(conn, director, receptionist):
    auth.disable_user(conn, director, receptionist.user_id)
    auth.disable_user(conn, director, receptionist.user_id)
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'user.disable'"
                        ).fetchone()[0] == 1


def test_a_director_cannot_disable_their_own_account(conn, director):
    with pytest.raises(ValidationError) as exc:
        auth.disable_user(conn, director, director.user_id)
    assert exc.value.message == t["auth.cannot_disable_self"]
    assert auth.login(conn, "directeur", "password1").role == "director"


def test_another_director_can_be_disabled_one_always_stays(conn, director):
    other = auth.create_user(conn, director, "adjoint", "password3", "director")
    auth.disable_user(conn, director, other)
    active = conn.execute("SELECT COUNT(*) FROM users WHERE role = 'director' "
                          "AND status = 'active'").fetchone()[0]
    assert active == 1


@pytest.mark.parametrize("action", [auth.disable_user, auth.enable_user])
def test_receptionist_cannot_change_an_account_status(conn, director, receptionist, action):
    with pytest.raises(PermissionDenied):
        action(conn, receptionist, director.user_id)
    with pytest.raises(PermissionDenied):
        action(conn, receptionist, receptionist.user_id)


def test_disable_unknown_user(conn, director):
    with pytest.raises(NotFound):
        auth.disable_user(conn, director, 999)


# ----- the recovery code: a forgotten director password -----

def code_rows(conn) -> list:
    return conn.execute("SELECT value FROM settings WHERE key = ?",
                        (auth.RECOVERY_KEY,)).fetchall()


def test_a_recovery_code_is_shown_once_and_only_its_hash_kept(conn, director):
    assert auth.recovery_code_made(conn, director) is None
    code = auth.new_recovery_code(conn, director)
    assert re.fullmatch(r"[A-HJKMNP-Z2-9]{4}(-[A-HJKMNP-Z2-9]{4}){3}", code)
    stored = code_rows(conn)[0][0]
    assert stored.startswith("scrypt$") and code.replace("-", "") not in stored
    assert auth.recovery_code_made(conn, director) is not None
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'user.recovery_code'"
                        ).fetchone()[0] == 1


def test_a_director_gets_back_in_with_the_code_which_is_then_used_up(conn, director):
    code = auth.new_recovery_code(conn, director)
    typed = code.replace("-", " ").lower()  # read from paper: spaces, small letters
    ctx = auth.recover(conn, " directeur ", typed, "nouveau-pass")
    assert (ctx.user_id, ctx.role) == (director.user_id, "director")
    assert auth.login(conn, "directeur", "nouveau-pass").user_id == director.user_id
    assert code_rows(conn) == []
    row = conn.execute("SELECT user_id, entity_id FROM audit_log WHERE action = 'user.recover'"
                       ).fetchone()
    assert tuple(row) == (director.user_id, director.user_id)
    with pytest.raises(PermissionDenied) as exc:
        auth.recover(conn, "directeur", code, "autre-pass1")
    assert exc.value.message == t["auth.recovery_invalid"]


def test_a_new_code_replaces_the_old_one(conn, director):
    old = auth.new_recovery_code(conn, director)
    new = auth.new_recovery_code(conn, director)
    with pytest.raises(PermissionDenied):
        auth.recover(conn, "directeur", old, "nouveau-pass")
    auth.recover(conn, "directeur", new, "nouveau-pass")


@pytest.mark.parametrize("username, code_ok", [
    ("directeur", False),  # a wrong code
    ("accueil", True),  # the front desk: the director resets their password
    ("personne", True),
])
def test_the_code_works_only_for_a_director_with_the_right_code(
        conn, director, receptionist, username, code_ok):
    code = auth.new_recovery_code(conn, director)
    with pytest.raises(PermissionDenied) as exc:
        auth.recover(conn, username, code if code_ok else "AAAA-AAAA-AAAA-AAAA",
                     "nouveau-pass")
    assert exc.value.message == t["auth.recovery_invalid"]
    assert len(code_rows(conn)) == 1  # still there


def test_no_code_no_way_back(conn, director):
    with pytest.raises(PermissionDenied):
        auth.recover(conn, "directeur", "AAAA-AAAA-AAAA-AAAA", "nouveau-pass")


def test_a_disabled_director_cannot_use_the_code(conn, director):
    other = auth.create_user(conn, director, "adjoint", "password3", "director")
    auth.disable_user(conn, director, other)
    code = auth.new_recovery_code(conn, director)
    with pytest.raises(PermissionDenied):
        auth.recover(conn, "adjoint", code, "nouveau-pass")


def test_the_new_password_must_be_long_enough(conn, director):
    code = auth.new_recovery_code(conn, director)
    with pytest.raises(ValidationError) as exc:
        auth.recover(conn, "directeur", code, "court")
    assert exc.value.message == t["auth.password_short"]
    assert len(code_rows(conn)) == 1


def test_wrong_codes_are_slowed_down_like_logins(conn, director, sleeps):
    auth.new_recovery_code(conn, director)
    for _ in range(auth.FAILS_BEFORE_DELAY + 1):
        with pytest.raises(PermissionDenied):
            auth.recover(conn, "directeur", "AAAA-AAAA-AAAA-AAAA", "nouveau-pass")
    assert sleeps == [auth.DELAY_SECONDS]


def test_the_front_desk_cannot_make_or_see_a_code(conn, receptionist):
    for call in (auth.new_recovery_code, auth.recovery_code_made):
        with pytest.raises(PermissionDenied):
            call(conn, receptionist)
