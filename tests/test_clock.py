"""The computer's clock at start, against the last operation saved."""

import json
from datetime import datetime, timedelta

import pytest

from tadris.services import clock

LAST = datetime(2026, 10, 30, 18, 0, 0)


@pytest.fixture
def worked(conn):
    """A database whose last operation was saved on LAST."""
    conn.execute("INSERT INTO audit_log(action, entity_name, created_at) VALUES (?, ?, ?)",
                 ("payment.record", "payments", LAST.isoformat(timespec="seconds")))
    return conn


def test_a_new_database_has_nothing_to_compare_with(conn):
    result = clock.check(conn, datetime(2001, 1, 1))
    assert (result.state, result.last) == ("ok", None)


@pytest.mark.parametrize("now", [
    LAST + timedelta(hours=14),  # the next morning
    LAST - timedelta(minutes=5),  # set back a little: tolerated
    LAST + timedelta(days=80),  # after the summer break
])
def test_a_plausible_date_is_ok(worked, now):
    assert clock.check(worked, now).state == "ok"


@pytest.mark.parametrize("now", [datetime(2001, 1, 1, 8, 0), LAST - timedelta(hours=1)])
def test_a_date_before_the_last_operation_is_behind(worked, now):
    result = clock.check(worked, now)
    assert (result.state, result.now, result.last) == ("behind", now, LAST)


def test_a_date_long_after_the_last_operation_is_ahead(worked):
    assert clock.check(worked, LAST + timedelta(days=121)).state == "ahead"
    assert clock.check(worked, LAST.replace(year=2027)).state == "ahead"  # wrong year typed


def test_going_on_anyway_is_audited_by_the_app(worked):
    now = datetime(2001, 1, 1, 8, 0)
    clock.went_on(worked, clock.check(worked, now))
    row = worked.execute("SELECT user_id, entity_name, new_value FROM audit_log "
                         "WHERE action = 'clock.behind'").fetchone()
    assert (row["user_id"], row["entity_name"]) == (None, "app")
    assert json.loads(row["new_value"]) == {"now": "2001-01-01T08:00:00",
                                            "last": "2026-10-30T18:00:00"}
