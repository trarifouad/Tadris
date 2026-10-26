from datetime import date

import pytest
from PySide6.QtCore import Qt

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import PermissionDenied
from tadris.domain.models import GroupInput, SlotInput, StudentInput, TeacherInput
from tadris.i18n.fr import t
from tadris.services import (
    attendance,
    auth,
    catalog,
    enrollments,
    groups,
    printing,
    registrations,
    rooms,
    school_years,
    sessions,
    settings,
    students,
    teachers,
    timetable,
)

MONDAY = date(2026, 10, 19)
SATURDAY = date(2026, 10, 17)  # the week of MONDAY starts on Saturday


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(dates, "today", lambda: MONDAY)


@pytest.fixture
def director(conn):
    return auth.bootstrap_director(conn, "directeur", "password1", "École Ennour")


@pytest.fixture
def desk(conn, director):
    user_id = auth.create_user(conn, director, "accueil", "password2", "receptionist")
    return UserContext(user_id=user_id, username="accueil", role="receptionist")


@pytest.fixture
def school(conn, director):
    settings.save_school(conn, director, "École Ennour", "0550 12 34 56", "Oran", "08:00",
                         "20:00")
    year = school_years.create(conn, director, "2026-2027", date(2026, 9, 1), date(2027, 6, 30))
    level = catalog.create(conn, director, "level", "4AM")
    room = rooms.create(conn, director, "Salle A", 20)
    karim = teachers.create(conn, director, TeacherInput("Karim Haddad"), 6000, date(2026, 9, 1))
    subject = catalog.create(conn, director, "subject", "Maths")
    maths = groups.create(conn, director, GroupInput(year, level, subject, "M1 & co", 3000, 15,
                                                     date(2026, 9, 1)), karim)
    timetable.add_slot(conn, director, SlotInput(maths, room, 1, "17:00", "18:30"))  # Monday
    timetable.add_slot(conn, director, SlotInput(maths, room, 3, "17:00", "18:30"))  # Wednesday
    pupils = {}
    for first, trial, entered in (("Amine", False, date(2026, 10, 1)),
                                  ("Yanis", True, date(2026, 10, 1)),
                                  ("Lina", False, date(2026, 10, 20))):  # from Tuesday
        sid = students.create(conn, director, StudentInput(first, "Benali"))
        registrations.register(conn, director, sid, level, 0)
        pupils[first] = enrollments.enroll(conn, director, sid, maths, trial=trial,
                                           enrolled_on=entered)
    monday = sessions.listing(conn, director, MONDAY, MONDAY)[0].id
    wednesday = sessions.listing(conn, director, date(2026, 10, 21), date(2026, 10, 21))[0].id
    return {"maths": maths, "pupils": pupils, "monday": monday, "wednesday": wednesday}


def logged(conn) -> list[tuple]:
    return [tuple(r) for r in conn.execute(
        "SELECT document_type, document_id, printed_by FROM print_log ORDER BY id")]


# ----- the session sheet -----

def test_session_sheet_content(conn, desk, school):
    amine, yanis = school["pupils"]["Amine"], school["pupils"]["Yanis"]
    attendance.save(conn, desk, school["monday"], {amine: "present", yanis: "absent"})
    sheet = printing.session_sheet_content(conn, desk, school["monday"])
    assert (sheet.school.name, sheet.school.address, sheet.school.phone) == (
        "École Ennour", "Oran", "0550 12 34 56")
    assert sheet.heading == "M1 & co · Maths 4AM"
    assert sheet.details == ["lundi 19/10/2026, de 17:00 à 18:30",
                             "Salle : Salle A · Enseignant : Karim Haddad"]
    assert sheet.rows == [  # Lina enters on Tuesday: not on Monday's sheet
        ["2026-0001", "Benali Amine", "", "X", "", "", "", ""],
        ["2026-0002", "Benali Yanis", "Essai", "", "", "X", "", ""],
    ]
    assert sheet.footer.printed.endswith("par accueil")


def test_session_sheet_pdf_and_log(conn, desk, school, tmp_path):
    path = printing.session_sheet(conn, desk, school["monday"], tmp_path)
    assert path.name == "presence_m1-co_2026-10-19.pdf"
    data = path.read_bytes()
    assert data.startswith(b"%PDF") and data.count(b"/Type /Page\n") + data.count(
        b"/Type /Page ") >= 1
    assert logged(conn) == [(printing.SESSION_SHEET, school["monday"], desk.user_id)]


def test_a_cancelled_session_says_so(conn, desk, school, tmp_path):
    sessions.cancel(conn, desk, school["wednesday"], "Grève")
    sheet = printing.session_sheet_content(conn, desk, school["wednesday"])
    assert sheet.details[-1] == t["print.session_cancelled"].format(reason="Grève")
    printing.session_sheet(conn, desk, school["wednesday"], tmp_path)  # still printable


def test_an_empty_session_prints(conn, director, desk, school, tmp_path):
    g = groups.get(conn, director, school["maths"])
    teacher = teachers.create(conn, director, TeacherInput("Samia"), 5000, date(2026, 9, 1))
    subject = catalog.create(conn, director, "subject", "Arabe")
    empty = groups.create(conn, director, GroupInput(g.school_year_id, g.level_id, subject,
                                                     "A1", 2000, 10, date(2026, 9, 1)), teacher)
    room = rooms.create(conn, director, "Salle B", 10)
    timetable.add_slot(conn, director, SlotInput(empty, room, 1, "10:00", "11:00"))
    session_id = sessions.listing(conn, desk, MONDAY, MONDAY, group_id=empty)[0].id
    assert printing.session_sheet_content(conn, desk, session_id).rows == []
    assert printing.session_sheet(conn, desk, session_id, tmp_path).exists()


# ----- the week sheet -----

def test_week_sheet_content(conn, desk, school, monkeypatch):
    amine, yanis, lina = (school["pupils"][k] for k in ("Amine", "Yanis", "Lina"))
    attendance.save(conn, desk, school["monday"], {amine: "late", yanis: "excused"})
    sessions.cancel(conn, desk, school["wednesday"], "Grève")
    sheet = printing.week_sheet_content(conn, desk, school["maths"], SATURDAY)
    assert sheet.details[0] == t["print.week_when"].format(first="17/10/2026",
                                                           last="23/10/2026")
    assert sheet.columns[2:] == ["lun 19/10<br/>17:00", "mer 21/10<br/>17:00<br/>Annulée"]
    assert sheet.cancelled_columns == [3]
    assert sheet.rows == [
        ["2026-0001", "Benali Amine", "R", ""],
        ["2026-0003", "Benali Lina", "—", ""],  # not yet in the group on Monday
        ["2026-0002", "Benali Yanis", "E", ""],
    ]
    assert lina


def test_week_sheet_pdf_and_log(conn, director, school, tmp_path):
    path = printing.week_sheet(conn, director, school["maths"], SATURDAY, tmp_path)
    assert path.name == "presence-semaine_m1-co_2026-10-17.pdf"
    assert path.read_bytes().startswith(b"%PDF")
    assert logged(conn) == [(printing.WEEK_SHEET, school["maths"], director.user_id)]


def test_a_week_without_sessions(conn, director, school, tmp_path):
    later = date(2027, 8, 7)  # after the year: no session
    assert printing.week_sheet_content(conn, director, school["maths"], later).rows == []
    assert printing.week_sheet(conn, director, school["maths"], later, tmp_path).exists()


def test_printing_needs_the_permission(conn, school, tmp_path):
    ghost = UserContext(user_id=1, username="x", role="teacher")
    with pytest.raises(PermissionDenied):
        printing.session_sheet(conn, ghost, school["monday"], tmp_path)


# ----- the buttons -----

@pytest.fixture
def themed(qapp):
    from tadris.ui.theme import apply_theme, load_fonts

    load_fonts()
    apply_theme(qapp)


def test_print_buttons(qtbot, themed, conn, desk, school, monkeypatch, tmp_path):
    from tadris import config
    from tadris.ui.pages.attendance_entry import AttendanceView
    from tadris.ui.widgets import common

    monkeypatch.setattr(config, "documents_dir", lambda: tmp_path)
    opened = []
    monkeypatch.setattr(common, "open_document", opened.append)
    view = AttendanceView(conn, desk, school["monday"])
    qtbot.addWidget(view)
    qtbot.mouseClick(view.print_sheet, Qt.MouseButton.LeftButton)
    assert [p.name for p in opened] == ["presence_m1-co_2026-10-19.pdf"]
    assert len(logged(conn)) == 1
