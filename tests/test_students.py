import json
from datetime import date

import pytest

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError, NotFound, PermissionDenied, ValidationError
from tadris.domain.models import ContactInput, ContactLink, StudentInput
from tadris.i18n.fr import t
from tadris.services import auth, contacts, students


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(dates, "today", lambda: date(2026, 10, 18))


@pytest.fixture
def director(conn):
    return auth.bootstrap_director(conn, "directeur", "password1", "École Ennour")


@pytest.fixture
def receptionist(conn, director):
    user_id = auth.create_user(conn, director, "accueil", "password2", "receptionist")
    return UserContext(user_id=user_id, username="accueil", role="receptionist")


def amine(**overrides) -> StudentInput:
    values = {"first_name": "Amine", "last_name": "Benali", "birth_date": date(2012, 3, 14)}
    values.update(overrides)
    return StudentInput(**values)


FATHER = ContactInput(full_name="Karim Benali", phone="0661 90 25 47")
MOTHER = ContactInput(full_name="Nadia Benali", phone="+213 770 11 22 33")


def main_flags(conn, student_id) -> list[tuple[int, int]]:
    return [
        (row["contact_id"], row["is_main"])
        for row in conn.execute(
            "SELECT contact_id, is_main FROM student_contacts WHERE student_id = ? "
            "ORDER BY contact_id",
            (student_id,),
        )
    ]


def audit_actions(conn) -> list[str]:
    return [row[0] for row in conn.execute("SELECT action FROM audit_log ORDER BY id")]


# ----- create -----

def test_create_gets_sequential_numbers(conn, receptionist):
    ids = [students.create(conn, receptionist, amine(first_name=f"E{i}")) for i in range(3)]
    numbers = [students.get(conn, receptionist, i).student_number for i in ids]
    assert numbers == ["2026-0001", "2026-0002", "2026-0003"]


def test_numbers_restart_each_year(conn, director, monkeypatch):
    students.create(conn, director, amine())
    monkeypatch.setattr(dates, "today", lambda: date(2027, 1, 4))
    student_id = students.create(conn, director, amine(first_name="Yanis"))
    assert students.get(conn, director, student_id).student_number == "2027-0001"


def test_create_cleans_and_stores_fields(conn, director):
    student_id = students.create(
        conn, director,
        StudentInput(first_name="  Amine ", last_name=" Ben   Ali ", birth_date=date(2012, 3, 14),
                     notes="  Allergie aux arachides  "),
    )
    student = students.get(conn, director, student_id)
    assert (student.first_name, student.last_name) == ("Amine", "Ben Ali")
    assert student.birth_date == "2012-03-14"
    assert student.notes == "Allergie aux arachides"
    assert student.status == "active"
    assert student.full_name == "Ben Ali Amine"


@pytest.mark.parametrize("data, key", [
    (amine(last_name="  "), "student.last_name_required"),
    (amine(first_name=""), "student.first_name_required"),
    (amine(birth_date=date(2026, 10, 19)), "student.birth_date_future"),
])
def test_create_validation(conn, director, data, key):
    with pytest.raises(ValidationError) as exc:
        students.create(conn, director, data)
    assert exc.value.message == t[key]
    assert conn.execute("SELECT COUNT(*) FROM students").fetchone()[0] == 0


def test_create_with_contact_makes_it_main_in_one_transaction(conn, director):
    student_id = students.create(conn, director, amine(), FATHER, ContactLink(relation="Père"))
    [contact] = contacts.list_for_student(conn, director, student_id)
    assert contact.is_main and contact.can_receive_sms
    assert contact.phone == "0661902547"
    assert contact.relation == "Père"
    assert audit_actions(conn)[-3:] == ["student.create", "contact.create", "contact.link"]


def test_create_with_invalid_contact_creates_nothing(conn, director):
    with pytest.raises(ValidationError) as exc:
        students.create(conn, director, amine(), ContactInput(full_name="Karim", phone="12345"))
    assert exc.value.message == t["phone.invalid"]
    assert conn.execute("SELECT COUNT(*) FROM students").fetchone()[0] == 0
    # The counter did not move either: the next student still gets number 1.
    student_id = students.create(conn, director, amine())
    assert students.get(conn, director, student_id).student_number == "2026-0001"


def test_create_writes_audit(conn, receptionist):
    student_id = students.create(conn, receptionist, amine())
    row = conn.execute(
        "SELECT user_id, entity_id, new_value FROM audit_log WHERE action = 'student.create'"
    ).fetchone()
    assert (row["user_id"], row["entity_id"]) == (receptionist.user_id, student_id)
    assert json.loads(row["new_value"])["student_number"] == "2026-0001"


# ----- update -----

def test_update_audits_only_changed_fields(conn, receptionist):
    student_id = students.create(conn, receptionist, amine())
    students.update(conn, receptionist, student_id, amine(first_name="Amine Rayan"))
    row = conn.execute(
        "SELECT old_value, new_value FROM audit_log WHERE action = 'student.update'"
    ).fetchone()
    assert json.loads(row["old_value"]) == {"first_name": "Amine"}
    assert json.loads(row["new_value"]) == {"first_name": "Amine Rayan"}


def test_update_without_change_writes_no_audit(conn, director):
    student_id = students.create(conn, director, amine())
    students.update(conn, director, student_id, amine())
    assert "student.update" not in audit_actions(conn)


def test_update_unknown_student(conn, director):
    with pytest.raises(NotFound):
        students.update(conn, director, 99, amine())


# ----- deactivate -----

def test_receptionist_can_create_and_edit_but_not_deactivate(conn, receptionist):
    student_id = students.create(conn, receptionist, amine())
    students.update(conn, receptionist, student_id, amine(notes="Lunettes"))
    with pytest.raises(PermissionDenied):
        students.deactivate(conn, receptionist, student_id)
    assert students.get(conn, receptionist, student_id).status == "active"


def test_deactivate_and_reactivate_never_delete(conn, director):
    student_id = students.create(conn, director, amine())
    students.deactivate(conn, director, student_id)
    assert students.get(conn, director, student_id).status == "inactive"
    with pytest.raises(BusinessRuleError) as exc:
        students.deactivate(conn, director, student_id)
    assert exc.value.message == t["student.already_inactive"]
    students.reactivate(conn, director, student_id)
    assert students.get(conn, director, student_id).status == "active"
    assert conn.execute("SELECT COUNT(*) FROM students").fetchone()[0] == 1
    assert audit_actions(conn)[-2:] == ["student.deactivate", "student.reactivate"]


def test_receptionist_cannot_reactivate(conn, director, receptionist):
    student_id = students.create(conn, director, amine())
    students.deactivate(conn, director, student_id)
    with pytest.raises(PermissionDenied):
        students.reactivate(conn, receptionist, student_id)


def test_deactivate_refused_while_enrolled(conn, director):
    student_id = students.create(conn, director, amine())
    conn.executescript(f"""
    INSERT INTO school_years(label,start_date,end_date) VALUES('2026-2027','2026-09-01','2027-06-30');
    INSERT INTO levels(name) VALUES('3AM');
    INSERT INTO subjects(name) VALUES('Math');
    INSERT INTO registrations(student_id,school_year_id,level_id,fee_amount)
      VALUES({student_id},1,1,2000);
    INSERT INTO class_groups(school_year_id,level_id,subject_id,name,price,capacity,start_date)
      VALUES(1,1,1,'G1',3000,10,'2026-09-01');
    INSERT INTO enrollments(student_id,group_id,registration_id,enrolled_on)
      VALUES({student_id},1,1,'2026-09-01');
    """)
    with pytest.raises(BusinessRuleError) as exc:
        students.deactivate(conn, director, student_id)
    assert exc.value.message == t["student.has_live_enrollments"]
    assert students.get(conn, director, student_id).status == "active"


# ----- search -----

@pytest.fixture
def school(conn, director):
    ids = {
        "amine": students.create(conn, director, amine(), FATHER),
        "helene": students.create(
            conn, director, StudentInput("Hélène", "Mansouri"),
            ContactInput("Samia Mansouri", "0550 12 34 56"),
        ),
        "yanis": students.create(conn, director, StudentInput("Yanis", "Benaissa")),
    }
    students.deactivate(conn, director, ids["yanis"])
    return ids


def found(conn, ctx, query="", status="active") -> set[str]:
    return {s.first_name for s in students.search(conn, ctx, query, status)}


def test_search_partial_name_any_case_and_accent(conn, director, school):
    assert found(conn, director, "ben") == {"Amine"}
    assert found(conn, director, "ben", status=None) == {"Amine", "Yanis"}
    assert found(conn, director, "HELENE") == {"Hélène"}
    assert found(conn, director, "mansou hél") == {"Hélène"}
    assert found(conn, director, "amine benali") == {"Amine"}
    assert found(conn, director, "amine mansouri") == set()


def test_search_by_phone_with_any_spacing(conn, director, school):
    assert found(conn, director, "0661902547") == {"Amine"}
    assert found(conn, director, "0661 90 25") == {"Amine"}
    assert found(conn, director, "+213 550") == set()  # prefix is not rewritten in a search
    assert found(conn, director, "12 34 56") == {"Hélène"}


def test_search_by_number(conn, director, school):
    assert found(conn, director, "2026-0002") == {"Hélène"}
    assert found(conn, director, "0003", status=None) == {"Yanis"}


def test_search_status_filter_and_list_columns(conn, director, school):
    assert found(conn, director) == {"Amine", "Hélène"}
    assert found(conn, director, status="inactive") == {"Yanis"}
    first = students.search(conn, director)[0]
    assert (first.last_name, first.main_contact, first.main_phone) == (
        "Benali", "Karim Benali", "0661902547"
    )


def test_search_escapes_like_wildcards(conn, director, school):
    assert found(conn, director, "%", status=None) == set()
    assert found(conn, director, "_", status=None) == set()


def test_search_rejects_unknown_status(conn, director):
    with pytest.raises(ValidationError):
        students.search(conn, director, status="deleted")


# ----- duplicates -----

def test_duplicate_warning_same_name_and_birth_date(conn, director):
    existing = students.create(conn, director, amine())
    [match] = students.possible_duplicates(conn, director, amine(first_name="amine "))
    assert (match.student_id, match.reason, match.full_name) == (existing, "name", "Benali Amine")
    assert students.possible_duplicates(conn, director, amine(birth_date=date(2013, 1, 1))) == []
    # Unknown birth date on one side still warns.
    assert len(students.possible_duplicates(conn, director, amine(birth_date=None))) == 1


def test_duplicate_warning_same_phone_and_not_a_block(conn, director):
    existing = students.create(conn, director, amine(), FATHER)
    sister = StudentInput("Lina", "Benali")
    [match] = students.possible_duplicates(conn, director, sister, phones=("+213661902547",))
    assert (match.student_id, match.reason) == (existing, "phone")
    students.create(conn, director, sister, FATHER)  # a warning only
    assert len(students.search(conn, director, "benali")) == 2


def test_duplicate_check_excludes_the_student_being_edited(conn, director):
    student_id = students.create(conn, director, amine(), FATHER)
    assert students.possible_duplicates(
        conn, director, amine(), phones=(FATHER.phone,), exclude_id=student_id
    ) == []


def test_duplicate_check_ignores_invalid_phones(conn, director):
    students.create(conn, director, amine(), FATHER)
    assert students.possible_duplicates(conn, director, StudentInput("X", "Y"), ("abc",)) == []


# ----- contacts -----

@pytest.fixture
def student_id(conn, receptionist):
    return students.create(conn, receptionist, amine())


def test_first_contact_becomes_main_even_if_not_asked(conn, receptionist, student_id):
    father = contacts.add(conn, receptionist, student_id, FATHER, ContactLink(is_main=False))
    assert main_flags(conn, student_id) == [(father, 1)]


def test_student_with_two_contacts(conn, receptionist, student_id):
    father = contacts.add(conn, receptionist, student_id, FATHER, ContactLink("Père"))
    mother = contacts.add(conn, receptionist, student_id, MOTHER,
                          ContactLink("Mère", can_receive_sms=False))
    listed = contacts.list_for_student(conn, receptionist, student_id)
    assert [(c.contact_id, c.is_main, c.can_receive_sms) for c in listed] == [
        (father, True, True), (mother, False, False),
    ]
    assert listed[1].phone == "0770112233"


def test_adding_a_main_contact_swaps_the_main(conn, receptionist, student_id):
    father = contacts.add(conn, receptionist, student_id, FATHER)
    mother = contacts.add(conn, receptionist, student_id, MOTHER, ContactLink(is_main=True))
    assert main_flags(conn, student_id) == [(father, 0), (mother, 1)]


def test_set_main_never_leaves_two_or_zero(conn, receptionist, student_id):
    father = contacts.add(conn, receptionist, student_id, FATHER)
    mother = contacts.add(conn, receptionist, student_id, MOTHER)
    for target in (mother, father, father, mother):
        contacts.set_main(conn, receptionist, student_id, target)
        flags = main_flags(conn, student_id)
        assert sum(is_main for _, is_main in flags) == 1
        assert (target, 1) in flags
    rows = conn.execute(
        "SELECT old_value, new_value FROM audit_log WHERE action = 'contact.set_main' ORDER BY id"
    ).fetchall()
    assert len(rows) == 3  # setting the current main again is a no-op
    assert json.loads(rows[0]["new_value"]) == {"main_contact_id": mother}


def test_set_main_on_unlinked_contact(conn, director, receptionist, student_id):
    other = students.create(conn, director, StudentInput("Lina", "Haddad"), MOTHER)
    [contact] = contacts.list_for_student(conn, director, other)
    with pytest.raises(NotFound):
        contacts.set_main(conn, receptionist, student_id, contact.contact_id)


def test_update_cannot_drop_the_main_flag(conn, receptionist, student_id):
    father = contacts.add(conn, receptionist, student_id, FATHER)
    with pytest.raises(BusinessRuleError) as exc:
        contacts.update(conn, receptionist, student_id, father, FATHER, ContactLink(is_main=False))
    assert exc.value.message == t["contact.main_required_first"]
    assert main_flags(conn, student_id) == [(father, 1)]


def test_update_contact_and_link(conn, receptionist, student_id):
    father = contacts.add(conn, receptionist, student_id, FATHER)
    mother = contacts.add(conn, receptionist, student_id, MOTHER)
    contacts.update(
        conn, receptionist, student_id, mother,
        ContactInput("Nadia Benali", "0770 11 22 33", phone_2="048 55 12 30", address="Sidi Bel Abbès"),
        ContactLink("Mère", is_main=True, can_receive_sms=False),
    )
    by_id = {c.contact_id: c for c in contacts.list_for_student(conn, receptionist, student_id)}
    assert by_id[mother].phone_2 == "048551230"
    assert by_id[mother].address == "Sidi Bel Abbès"
    assert (by_id[mother].is_main, by_id[mother].can_receive_sms) == (True, False)
    assert by_id[father].is_main is False
    assert audit_actions(conn)[-2:] == ["contact.update", "contact.update_link"]


def test_unlink_main_refused_while_others_remain(conn, receptionist, student_id):
    father = contacts.add(conn, receptionist, student_id, FATHER)
    mother = contacts.add(conn, receptionist, student_id, MOTHER)
    with pytest.raises(BusinessRuleError) as exc:
        contacts.unlink(conn, receptionist, student_id, father)
    assert exc.value.message == t["contact.main_required_first"]
    contacts.unlink(conn, receptionist, student_id, mother)
    contacts.unlink(conn, receptionist, student_id, father)  # last contact: allowed
    assert main_flags(conn, student_id) == []
    # The contact rows stay on file.
    assert conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0] == 2


def test_sibling_shares_a_contact(conn, director, receptionist, student_id):
    father = contacts.add(conn, receptionist, student_id, FATHER)
    sister = students.create(conn, director, StudentInput("Lina", "Benali"))
    [existing] = contacts.find_by_phone(conn, receptionist, "0661 90 25 47", sister)
    assert (existing.contact_id, existing.students) == (father, ("Benali Amine",))
    contacts.link_existing(conn, receptionist, sister, father, ContactLink("Père"))
    [linked] = contacts.list_for_student(conn, receptionist, sister)
    assert linked.is_main and linked.shared_with == ("Benali Amine",)
    # Already linked: no longer offered, and linking again is refused.
    assert contacts.find_by_phone(conn, receptionist, "0661902547", sister) == []
    with pytest.raises(BusinessRuleError) as exc:
        contacts.link_existing(conn, receptionist, sister, father)
    assert exc.value.message == t["contact.already_linked"]
    # Editing the shared contact changes it for both children.
    contacts.update(conn, receptionist, sister, father,
                    ContactInput("Karim Benali", "0661 90 25 48"), ContactLink("Père", True))
    [for_amine] = contacts.list_for_student(conn, receptionist, student_id)
    assert for_amine.phone == "0661902548"


@pytest.mark.parametrize("data, key", [
    (ContactInput(full_name=" ", phone="0661902547"), "contact.name_required"),
    (ContactInput(full_name="Karim", phone=""), "contact.phone_required"),
    (ContactInput(full_name="Karim", phone="0661902547", phone_2="99"), "phone.invalid"),
])
def test_contact_validation(conn, receptionist, student_id, data, key):
    with pytest.raises(ValidationError) as exc:
        contacts.add(conn, receptionist, student_id, data)
    assert exc.value.message == t[key]


def test_second_phone_equal_to_first_is_dropped(conn, receptionist, student_id):
    contacts.add(conn, receptionist, student_id,
                 ContactInput("Karim", "0661902547", phone_2="0661 90 25 47"))
    [contact] = contacts.list_for_student(conn, receptionist, student_id)
    assert contact.phone_2 is None


def test_contact_on_unknown_student(conn, receptionist):
    with pytest.raises(NotFound):
        contacts.add(conn, receptionist, 99, FATHER)
