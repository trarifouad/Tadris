import json

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
    real_transaction = auth.transaction
    state = {"raced": False}

    def racing_transaction(c):
        if not state["raced"]:
            state["raced"] = True
            auth.bootstrap_director(c, "premier", "password1", "École A")
        return real_transaction(c)

    monkeypatch.setattr(auth, "transaction", racing_transaction)
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
