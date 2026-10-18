import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest

from tadris.core.context import UserContext
from tadris.core.errors import PermissionDenied, ValidationError
from tadris.db.connection import connect, transaction
from tadris.db.migrate import migrate
from tadris.i18n.fr import t
from tadris.services import audit, auth, counters, settings


@pytest.fixture
def director(conn):
    return auth.bootstrap_director(conn, "directeur", "password1", "École Ennour")


@pytest.fixture
def receptionist(conn, director):
    user_id = auth.create_user(conn, director, "accueil", "password2", "receptionist")
    return UserContext(user_id=user_id, username="accueil", role="receptionist")


# ----- counters -----

def test_counter_is_sequential_and_per_name(conn):
    with transaction(conn):
        receipts = [counters.next_value(conn, "receipt:2026") for _ in range(3)]
        student = counters.next_value(conn, "student:2026")
        next_year = counters.next_value(conn, "receipt:2027")
    assert receipts == [1, 2, 3]
    assert student == 1
    assert next_year == 1


def test_counter_has_no_gap_after_rollback(conn):
    with transaction(conn):
        assert counters.next_value(conn, "receipt:2026") == 1
    with pytest.raises(RuntimeError), transaction(conn):
        assert counters.next_value(conn, "receipt:2026") == 2
        raise RuntimeError("insert failed")
    with transaction(conn):
        assert counters.next_value(conn, "receipt:2026") == 2


def test_counter_two_connections_do_not_collide(tmp_path):
    path = tmp_path / "tadris.db"
    setup = connect(path)
    migrate(setup)
    setup.close()

    per_thread = 25

    def worker() -> list[int]:
        c = connect(path)
        try:
            values = []
            for _ in range(per_thread):
                with transaction(c):
                    values.append(counters.next_value(c, "receipt:2026"))
            return values
        finally:
            c.close()

    # future.result() re-raises any error from the worker thread.
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker) for _ in range(2)]
        results = [value for future in futures for value in future.result()]

    assert sorted(results) == list(range(1, 2 * per_thread + 1))


# ----- settings -----

def test_settings_get_default_and_typed_value(conn, director):
    assert settings.get(conn, "school.name") == "École Ennour"
    assert settings.get(conn, "school.phone", "") == ""
    settings.set_value(conn, director, "defaults.registration_fee", "2000")
    assert settings.get(conn, "defaults.registration_fee") == 2000


def test_settings_audit_records_the_key(conn, director):
    settings.set_value(conn, director, "school.phone", "048 55 12 30")
    settings.set_value(conn, director, "school.phone", "048 55 12 31")
    rows = conn.execute(
        "SELECT old_value, new_value FROM audit_log WHERE action = 'settings.set' ORDER BY id"
    ).fetchall()
    assert [json.loads(r["new_value"]) for r in rows] == [
        {"key": "school.phone", "value": "048 55 12 30"},
        {"key": "school.phone", "value": "048 55 12 31"},
    ]
    assert json.loads(rows[1]["old_value"]) == {"key": "school.phone", "value": "048 55 12 30"}


def test_settings_unknown_key(conn, director):
    with pytest.raises(ValidationError) as exc:
        settings.get(conn, "school.color")
    assert exc.value.message == t["settings.unknown_key"]
    with pytest.raises(ValidationError):
        settings.set_value(conn, director, "school.color", "violet")


def test_settings_validation(conn, director):
    with pytest.raises(ValidationError):
        settings.set_value(conn, director, "defaults.registration_fee", "deux mille")
    with pytest.raises(ValidationError) as exc:
        settings.set_value(conn, director, "school.name", "   ")
    assert exc.value.message == t["auth.school_name_required"]


def test_receptionist_cannot_change_settings(conn, receptionist):
    with pytest.raises(PermissionDenied):
        settings.set_value(conn, receptionist, "school.phone", "0550 00 00 00")
    assert settings.get(conn, "school.phone") is None


# ----- audit -----

def test_audit_serializes_dates_and_accents(conn, director):
    with transaction(conn):
        audit.log(
            conn, director, "subscription.create", "subscriptions", 7,
            new={"start_date": date(2026, 9, 1), "groupe": "Mathématiques"},
        )
    row = conn.execute(
        "SELECT entity_name, entity_id, old_value, new_value FROM audit_log "
        "WHERE action = 'subscription.create'"
    ).fetchone()
    assert (row["entity_name"], row["entity_id"], row["old_value"]) == ("subscriptions", 7, None)
    assert "Mathématiques" in row["new_value"]
    assert json.loads(row["new_value"]) == {"start_date": "2026-09-01", "groupe": "Mathématiques"}
