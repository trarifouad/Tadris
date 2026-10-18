import re
import sqlite3

import pytest

from tadris.core.errors import BusinessRuleError
from tadris.db.connection import transaction
from tadris.db.errors import _TRIGGER_MESSAGES, translate
from tadris.db.migrate import MIGRATIONS_DIR
from tadris.i18n.fr import t

_RAISE = re.compile(r"RAISE\(ABORT,\s*'([^']+)'\)")


def _trigger_messages() -> set[str]:
    found = set()
    for path in MIGRATIONS_DIR.glob("*.sql"):
        found.update(_RAISE.findall(path.read_text(encoding="utf-8")))
    return found


def test_migrations_raise_messages():
    assert len(_trigger_messages()) > 40


@pytest.mark.parametrize("message", sorted(_trigger_messages()))
def test_every_trigger_message_has_its_own_translation(message):
    err = translate(sqlite3.IntegrityError(message))
    assert isinstance(err, BusinessRuleError)
    assert err.message != t["db.integrity"]


def test_every_translation_key_exists():
    for _, key in _TRIGGER_MESSAGES:
        assert key in t


def test_no_needle_matches_a_different_trigger_message():
    # Substring matching must not let one needle capture another trigger's message.
    for message in _trigger_messages():
        first = next(needle for needle, _ in _TRIGGER_MESSAGES if needle in message)
        assert first == message


@pytest.mark.parametrize("raw", [
    "UNIQUE constraint failed: students.student_number",
    "CHECK constraint failed: amount > 0",
    "NOT NULL constraint failed: students.first_name",
    "FOREIGN KEY constraint failed",
])
def test_plain_constraint_errors_fall_back_to_generic_message(raw):
    assert translate(sqlite3.IntegrityError(raw)).message == t["db.integrity"]


def test_real_trigger_error_translates(seeded):
    with pytest.raises(sqlite3.IntegrityError) as exc:
        seeded.execute("UPDATE payments SET amount = 1 WHERE id = 1")
    assert translate(exc.value).message == t["db.payments_immutable"]


# ----- transaction() -----

def test_transaction_commits(conn):
    with transaction(conn):
        conn.execute("INSERT INTO settings(key, value) VALUES ('k', 'v')")
    assert not conn.in_transaction
    assert conn.execute("SELECT value FROM settings WHERE key = 'k'").fetchone()[0] == "v"


def test_transaction_rolls_back_on_error(conn):
    with pytest.raises(RuntimeError), transaction(conn):
        conn.execute("INSERT INTO settings(key, value) VALUES ('k', 'v')")
        raise RuntimeError("boom")
    assert not conn.in_transaction
    assert conn.execute("SELECT COUNT(*) FROM settings WHERE key = 'k'").fetchone()[0] == 0


def test_transaction_keeps_original_error_when_already_rolled_back(conn):
    with pytest.raises(RuntimeError, match="original"), transaction(conn):
        conn.execute("ROLLBACK")
        raise RuntimeError("original")
