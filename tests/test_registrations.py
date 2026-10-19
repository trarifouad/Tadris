import json
import sqlite3
from datetime import date

import pytest

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError, NotFound, PermissionDenied, ValidationError
from tadris.domain.models import GroupInput, StudentInput, TeacherInput
from tadris.i18n.fr import t
from tadris.services import (
    auth,
    catalog,
    groups,
    registrations,
    school_years,
    settings,
    students,
    teachers,
)

TODAY = date(2026, 10, 18)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(dates, "today", lambda: TODAY)


@pytest.fixture
def director(conn):
    return auth.bootstrap_director(conn, "directeur", "password1", "École Ennour")


@pytest.fixture
def receptionist(conn, director):
    user_id = auth.create_user(conn, director, "accueil", "password2", "receptionist")
    return UserContext(user_id=user_id, username="accueil", role="receptionist")


@pytest.fixture
def year(conn, director):
    return school_years.create(conn, director, "2026-2027", date(2026, 9, 1), date(2027, 6, 30))


@pytest.fixture
def level(conn, director):
    return catalog.create(conn, director, "level", "4AM")


@pytest.fixture
def other_level(conn, director):
    return catalog.create(conn, director, "level", "3AS")


@pytest.fixture
def amine(conn, director):
    return students.create(conn, director, StudentInput("Amine", "Benali"))


def fee_charge(conn, registration_id):
    return conn.execute("SELECT * FROM charges WHERE registration_id = ? ORDER BY id DESC",
                        (registration_id,)).fetchone()


def last_audit(conn, action):
    return conn.execute("SELECT * FROM audit_log WHERE action = ? ORDER BY id DESC",
                        (action,)).fetchone()


def pay(conn, director, student_id, charge_id, amount):
    """Phase 7 is not written yet: record an allocated payment by hand."""
    cur = conn.execute("INSERT INTO payments(student_id, amount, method, paid_at, received_by) "
                       "VALUES (?, ?, 'cash', '2026-10-18T10:00:00', ?)",
                       (student_id, amount, director.user_id))
    conn.execute("INSERT INTO payment_allocations(payment_id, charge_id, amount) VALUES (?, ?, ?)",
                 (cur.lastrowid, charge_id, amount))
    return cur.lastrowid


def make_group(conn, director, year_id, level_id, name="G1", subject="Mathématiques"):
    teacher = teachers.create(conn, director, TeacherInput(f"Prof {name} {subject}"), 6000,
                              date(2026, 9, 1))
    subject_id = catalog.create(conn, director, "subject", subject)
    return groups.create(conn, director, GroupInput(year_id, level_id, subject_id, name, 3000,
                                                    10, date(2026, 9, 1)), teacher)


def place(conn, student_id, group_id, registration_id):
    """Phase 4 task 3 adds the enrollment service; place the student by hand meanwhile."""
    conn.execute("INSERT INTO enrollments(student_id, group_id, registration_id, enrolled_on) "
                 "VALUES (?, ?, ?, '2026-10-18')", (student_id, group_id, registration_id))


def enroll_by_hand(conn, director, registration_id, student_id, level_id, year_id):
    group = make_group(conn, director, year_id, level_id)
    place(conn, student_id, group, registration_id)
    return group


# ----- register -----

def test_register_with_the_default_fee_creates_the_charge(conn, director, receptionist, year,
                                                          level, amine):
    settings.set_value(conn, director, "defaults.registration_fee", 2000)
    reg_id = registrations.register(conn, receptionist, amine, level)
    reg = registrations.get(conn, receptionist, reg_id)
    assert (reg.school_year_id, reg.level_id, reg.level, reg.status) == (year, level, "4AM",
                                                                        "active")
    assert (reg.fee_amount, reg.fee_paid, reg.fee_due) == (2000, 0, 2000)
    charge = fee_charge(conn, reg_id)
    assert charge["id"] == reg.fee_charge_id
    assert (charge["amount"], charge["status"], charge["subscription_id"]) == (2000, "open", None)
    assert charge["description"] == "Frais d'inscription 2026-2027"
    assert charge["due_date"] == charge["accrual_date"] == "2026-10-18"
    entry = json.loads(last_audit(conn, "registration.create")["new_value"])
    assert entry["fee_amount"] == entry["default_fee"] == 2000
    assert entry["charge_id"] == charge["id"]


def test_typed_fee_is_a_snapshot_and_the_default_is_audited(conn, director, receptionist, year,
                                                            level, amine):
    settings.set_value(conn, director, "defaults.registration_fee", 2000)
    reg_id = registrations.register(conn, receptionist, amine, level, fee_amount=1500)
    settings.set_value(conn, director, "defaults.registration_fee", 2500)
    assert registrations.get(conn, director, reg_id).fee_amount == 1500
    entry = json.loads(last_audit(conn, "registration.create")["new_value"])
    assert (entry["fee_amount"], entry["default_fee"]) == (1500, 2000)


def test_free_registration_has_no_charge(conn, director, year, level, amine):
    reg_id = registrations.register(conn, director, amine, level)  # no default set: 0
    reg = registrations.get(conn, director, reg_id)
    assert (reg.fee_amount, reg.fee_charge_id, reg.fee_due) == (0, None, 0)
    assert fee_charge(conn, reg_id) is None


def test_negative_fee_is_refused(conn, director, year, level, amine):
    with pytest.raises(ValidationError, match="frais"):
        registrations.register(conn, director, amine, level, fee_amount=-1)


def test_register_needs_an_open_year(conn, director, level, amine):
    with pytest.raises(BusinessRuleError) as exc:
        registrations.register(conn, director, amine, level)
    assert exc.value.message == t["registration.no_open_year"]


def test_register_goes_to_the_open_year_not_an_upcoming_one(conn, director, year, level,
                                                            amine):
    upcoming = school_years.create(conn, director, "2027-2028", date(2027, 9, 1),
                                   date(2028, 6, 30))
    reg_id = registrations.register(conn, director, amine, level)
    assert registrations.get(conn, director, reg_id).school_year_id == year != upcoming


def test_one_registration_per_student_and_year(conn, director, year, level, other_level, amine):
    registrations.register(conn, director, amine, level)
    with pytest.raises(BusinessRuleError) as exc:
        registrations.register(conn, director, amine, other_level)
    assert exc.value.message == t["registration.exists"].format(label="2026-2027", level="4AM")


def test_already_registered_message_points_to_group_enrollment(conn, director, year, level,
                                                               amine):
    registrations.register(conn, director, amine, level)
    with pytest.raises(BusinessRuleError) as exc:
        registrations.register(conn, director, amine, level)
    assert "inscription annuelle 2026-2027 (4AM)" in exc.value.message
    assert "Inscrire dans un groupe" in exc.value.message


# ----- one registration, several groups -----

def test_one_registration_carries_several_groups(conn, director, year, level, amine):
    settings.set_value(conn, director, "defaults.registration_fee", 2000)
    reg_id = registrations.register(conn, director, amine, level)
    maths = make_group(conn, director, year, level, "G1", "Mathématiques")
    physics = make_group(conn, director, year, level, "G2", "Physique")
    french = make_group(conn, director, year, level, "G3", "Français")
    for group in (maths, physics, french):
        place(conn, amine, group, reg_id)
    reg = registrations.get(conn, director, reg_id)
    assert reg.live_enrollments == 3
    # Still one registration and one fee, whatever the number of groups.
    assert [r.id for r in registrations.for_student(conn, director, amine)] == [reg_id]
    assert conn.execute("SELECT COUNT(*) FROM charges WHERE registration_id = ?",
                        (reg_id,)).fetchone()[0] == 1
    assert reg.fee_due == 2000


def test_same_group_twice_at_once_is_refused(conn, director, year, level, amine):
    reg_id = registrations.register(conn, director, amine, level)
    group = make_group(conn, director, year, level)
    place(conn, amine, group, reg_id)
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        place(conn, amine, group, reg_id)


def test_siblings_share_a_group_with_their_own_registrations(conn, director, year, level,
                                                             amine):
    yanis = students.create(conn, director, StudentInput("Yanis", "Benali"))
    group = make_group(conn, director, year, level)
    for student in (amine, yanis):
        place(conn, student, group, registrations.register(conn, director, student, level))
    assert groups.get(conn, director, group).enrolled == 2


def test_inactive_student_or_level_is_refused(conn, director, year, level, amine):
    catalog.set_active(conn, director, "level", level, False)
    with pytest.raises(ValidationError):
        registrations.register(conn, director, amine, level)
    catalog.set_active(conn, director, "level", level, True)
    students.deactivate(conn, director, amine)
    with pytest.raises(BusinessRuleError) as exc:
        registrations.register(conn, director, amine, level)
    assert exc.value.message == t["registration.student_inactive"]


def test_unknown_student(conn, director, year, level):
    with pytest.raises(NotFound):
        registrations.register(conn, director, 999, level)


def test_current_and_history(conn, director, year, level, amine):
    assert registrations.current(conn, director, amine) is None
    reg_id = registrations.register(conn, director, amine, level)
    assert registrations.current(conn, director, amine).id == reg_id
    assert [r.id for r in registrations.for_student(conn, director, amine)] == [reg_id]


# ----- change level -----

def test_change_level_while_in_no_group(conn, receptionist, director, year, level, other_level,
                                        amine):
    reg_id = registrations.register(conn, receptionist, amine, level)
    registrations.change_level(conn, receptionist, reg_id, other_level)
    assert registrations.get(conn, director, reg_id).level == "3AS"
    entry = last_audit(conn, "registration.change_level")
    assert json.loads(entry["old_value"]) == {"level_id": level}
    with pytest.raises(ValidationError):
        registrations.change_level(conn, receptionist, reg_id, other_level)


def test_change_level_refused_while_in_a_group(conn, director, year, level, other_level, amine):
    reg_id = registrations.register(conn, director, amine, level)
    enroll_by_hand(conn, director, reg_id, amine, level, year)
    with pytest.raises(BusinessRuleError) as exc:
        registrations.change_level(conn, director, reg_id, other_level)
    assert exc.value.message == t["registration.has_live_enrollments"].format(count=1)


# ----- cancel -----

def test_cancel_cancels_the_fee_charge_and_is_audited(conn, director, year, level, amine):
    settings.set_value(conn, director, "defaults.registration_fee", 2000)
    reg_id = registrations.register(conn, director, amine, level)
    registrations.cancel(conn, director, reg_id, "  Erreur de saisie ")
    reg = registrations.get(conn, director, reg_id)
    assert (reg.status, reg.fee_due) == ("cancelled", 0)
    assert fee_charge(conn, reg_id)["status"] == "cancelled"
    assert registrations.current(conn, director, amine) is None
    entry = json.loads(last_audit(conn, "registration.cancel")["new_value"])
    assert entry["reason"] == "Erreur de saisie"
    with pytest.raises(BusinessRuleError):
        registrations.cancel(conn, director, reg_id, "encore")


def test_cancel_is_director_only_and_needs_a_reason(conn, director, receptionist, year, level,
                                                    amine):
    reg_id = registrations.register(conn, receptionist, amine, level)
    with pytest.raises(PermissionDenied):
        registrations.cancel(conn, receptionist, reg_id, "motif")
    with pytest.raises(ValidationError):
        registrations.cancel(conn, director, reg_id, "   ")


def test_cancel_refused_while_in_a_group(conn, director, year, level, amine):
    reg_id = registrations.register(conn, director, amine, level)
    enroll_by_hand(conn, director, reg_id, amine, level, year)
    with pytest.raises(BusinessRuleError, match="groupe"):
        registrations.cancel(conn, director, reg_id, "motif")


def test_cancel_refused_once_the_fee_was_paid(conn, director, year, level, amine):
    reg_id = registrations.register(conn, director, amine, level, fee_amount=2000)
    pay(conn, director, amine, fee_charge(conn, reg_id)["id"], 500)
    reg = registrations.get(conn, director, reg_id)
    assert (reg.fee_paid, reg.fee_due) == (500, 1500)
    with pytest.raises(BusinessRuleError) as exc:
        registrations.cancel(conn, director, reg_id, "motif")
    assert exc.value.message == t["registration.fee_paid"].format(amount="500 DA")


def test_voided_payment_does_not_count_as_paid(conn, director, year, level, amine):
    reg_id = registrations.register(conn, director, amine, level, fee_amount=2000)
    payment = pay(conn, director, amine, fee_charge(conn, reg_id)["id"], 2000)
    conn.execute("INSERT INTO payment_voids(payment_id, reason, voided_by) VALUES (?, 'x', ?)",
                 (payment, director.user_id))
    assert registrations.get(conn, director, reg_id).fee_paid == 0
    registrations.cancel(conn, director, reg_id, "motif")


def test_register_again_after_cancel_reuses_the_row(conn, director, year, level, other_level,
                                                    amine):
    first = registrations.register(conn, director, amine, level, fee_amount=2000)
    registrations.cancel(conn, director, first, "Erreur de niveau")
    again = registrations.register(conn, director, amine, other_level, fee_amount=1500)
    assert again == first
    reg = registrations.get(conn, director, again)
    assert (reg.status, reg.level, reg.fee_amount, reg.fee_due) == ("active", "3AS", 1500, 1500)
    charges = conn.execute("SELECT amount, status FROM charges WHERE registration_id = ? "
                           "ORDER BY id", (again,)).fetchall()
    assert [tuple(c) for c in charges] == [(2000, "cancelled"), (1500, "open")]


def test_register_again_for_free_shows_no_fee(conn, director, year, level, amine):
    first = registrations.register(conn, director, amine, level, fee_amount=2000)
    registrations.cancel(conn, director, first, "Erreur")
    registrations.register(conn, director, amine, level, fee_amount=0)
    reg = registrations.get(conn, director, first)
    assert (reg.fee_charge_id, reg.fee_due) == (None, 0)


def test_closed_year_registration_is_frozen(conn, director, year, level, other_level, amine):
    reg_id = registrations.register(conn, director, amine, level)
    school_years.close(conn, director, year)
    with pytest.raises(BusinessRuleError, match="clôturée"):
        registrations.change_level(conn, director, reg_id, other_level)
    with pytest.raises(BusinessRuleError, match="clôturée"):
        registrations.cancel(conn, director, reg_id, "motif")
    assert registrations.current(conn, director, amine) is None
