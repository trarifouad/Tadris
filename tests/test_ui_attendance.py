from datetime import date

import pytest
from PySide6.QtCore import Qt

from tadris.core import dates
from tadris.domain.models import GroupInput, SlotInput, StudentInput, TeacherInput
from tadris.i18n.fr import t
from tadris.services import (
    attendance,
    auth,
    catalog,
    enrollments,
    groups,
    registrations,
    rooms,
    school_years,
    sessions,
    students,
    teachers,
    timetable,
)
from tadris.ui.pages import attendance_entry
from tadris.ui.pages.attendance import AttendancePage
from tadris.ui.pages.attendance_entry import AttendanceView
from tadris.ui.pages.student_detail import StudentDetailView
from tadris.ui.theme import apply_theme, load_fonts

MONDAY = date(2026, 10, 19)


@pytest.fixture(autouse=True)
def theme(qapp, monkeypatch):
    load_fonts()
    apply_theme(qapp)
    monkeypatch.setattr(dates, "today", lambda: MONDAY)


@pytest.fixture
def director(conn):
    return auth.bootstrap_director(conn, "directeur", "password1", "École Ennour")


@pytest.fixture
def desk(conn, director):
    auth.create_user(conn, director, "accueil", "password2", "receptionist")
    return auth.login(conn, "accueil", "password2")


@pytest.fixture
def school(conn, director):
    year = school_years.create(conn, director, "2026-2027", date(2026, 9, 1), date(2027, 6, 30))
    level = catalog.create(conn, director, "level", "4AM")
    room = rooms.create(conn, director, "Salle A", 20)
    karim = teachers.create(conn, director, TeacherInput("Karim Haddad"), 6000, date(2026, 9, 1))
    subject = catalog.create(conn, director, "subject", "Maths")
    maths = groups.create(conn, director, GroupInput(year, level, subject, "M1", 3000, 15,
                                                     date(2026, 9, 1)), karim)
    timetable.add_slot(conn, director, SlotInput(maths, room, 1, "17:00", "18:30"))
    pupils = {}
    for first, trial in (("Amine", False), ("Lina", False), ("Yanis", True)):
        sid = students.create(conn, director, StudentInput(first, "Benali"))
        registrations.register(conn, director, sid, level, 0)
        pupils[first] = enrollments.enroll(conn, director, sid, maths, trial=trial,
                                           enrolled_on=date(2026, 10, 1))
    return {"maths": maths, "level": level, "pupils": pupils,
            "amine_student": students.search(conn, director, "Amine")[0].id}


def session_on(conn, ctx, day):
    return sessions.listing(conn, ctx, day, day)[0]


def entry(qtbot, conn, ctx, day=MONDAY) -> AttendanceView:
    view = AttendanceView(conn, ctx, session_on(conn, ctx, day).id)
    qtbot.addWidget(view)
    return view


def click(qtbot, button):
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)


def notes(view) -> list[str]:
    return [view.table.item(r, 2).text() for r in range(view.table.rowCount())]


def test_roster_with_badges(qtbot, conn, desk, school):
    view = entry(qtbot, conn, desk)
    assert [view.table.item(r, 0).text() for r in range(3)] == [
        "Benali Amine", "Benali Lina", "Benali Yanis"]
    assert notes(view) == ["", "", t["attendance_view.trial"]]
    assert view.summary.text() == t["attendance_view.summary"].format(
        present=0, late=0, absent=0, excused=0, unmarked=3)
    assert not view.save.isEnabled()  # nothing changed yet


def test_mark_and_save(qtbot, conn, desk, school):
    view = entry(qtbot, conn, desk)
    amine, lina, yanis = (school["pupils"][k] for k in ("Amine", "Lina", "Yanis"))
    click(qtbot, view._marks[lina].buttons["absent"])
    assert view.save.isEnabled() and view.dirty()
    click(qtbot, view.all_present)  # the other two become present
    assert view.marks() == {amine: "present", lina: "absent", yanis: "present"}
    assert view.summary.text() == t["attendance_view.summary"].format(
        present=2, late=0, absent=1, excused=0, unmarked=0)
    click(qtbot, view.save)
    assert not view.dirty() and not view.save.isEnabled()
    assert view.status.text() == "Tenue"
    lines = attendance.roster(conn, desk, view.session_id)
    assert [line.status for line in lines] == ["present", "absent", "present"]
    view2 = entry(qtbot, conn, desk)  # opened again: what was saved
    assert view2._marks[lina].status() == "absent"


def test_a_correction(qtbot, conn, desk, school):
    lina = school["pupils"]["Lina"]
    attendance.save(conn, desk, session_on(conn, desk, MONDAY).id, {lina: "absent"})
    view = entry(qtbot, conn, desk)
    click(qtbot, view._marks[lina].buttons["excused"])
    click(qtbot, view.save)
    assert attendance.roster(conn, desk, view.session_id)[1].status == "excused"


def test_a_future_session_is_read_only(qtbot, conn, desk, school):
    view = entry(qtbot, conn, desk, date(2026, 10, 26))
    assert view.notice.text() == t["attendance.future"].format(date="26/10/2026")
    assert view.save.isHidden() and view.all_present.isHidden()
    assert not view._marks[school["pupils"]["Amine"]].buttons["present"].isEnabled()


def test_a_cancelled_session_is_read_only(qtbot, conn, desk, school):
    sessions.cancel(conn, desk, session_on(conn, desk, MONDAY).id, "Grève")
    view = entry(qtbot, conn, desk)
    assert view.notice.text() == t["attendance_view.cancelled"].format(reason="Grève")
    assert view.save.isHidden()


def test_month_not_renewed_badge(qtbot, conn, director, desk, school, monkeypatch):
    monkeypatch.setattr(dates, "today", lambda: date(2026, 11, 2))  # months ended on 01/11
    sessions.generate(conn, director)
    view = entry(qtbot, conn, desk, date(2026, 11, 2))
    assert notes(view) == [t["attendance_view.not_renewed"]] * 2 + [t["attendance_view.trial"]]


def test_leaving_with_unsaved_marks_asks(qtbot, conn, desk, school, monkeypatch):
    view = entry(qtbot, conn, desk)
    left = []
    view.back.connect(lambda: left.append(True))
    click(qtbot, view._marks[school["pupils"]["Amine"]].buttons["present"])
    monkeypatch.setattr(attendance_entry, "confirm", lambda *_a: False)
    click(qtbot, view.back_button)
    assert left == []  # stayed
    monkeypatch.setattr(attendance_entry, "confirm", lambda *_a: True)
    click(qtbot, view.back_button)
    assert left == [True]


def test_a_card_opens_the_attendance_and_back(qtbot, conn, desk, school):
    page = AttendancePage(conn, desk)
    qtbot.addWidget(page)
    first = page.sessions.cards[0].session.id
    click(qtbot, page.sessions.cards[0])
    assert isinstance(page.detail, AttendanceView) and page.detail.session_id == first
    click(qtbot, page.detail.back_button)  # nothing changed: no question
    assert page.detail is None and page.stack.currentWidget() is page.list


def test_a_lone_card_keeps_its_height(qtbot, conn, desk, school):
    page = AttendancePage(conn, desk)
    qtbot.addWidget(page)
    page.resize(1200, 900)
    page.show()
    qtbot.waitExposed(page)
    [card] = page.sessions.cards
    assert card.height() == card.sizeHint().height() < 120


def test_student_attendance_tab(qtbot, conn, desk, school):
    amine = school["pupils"]["Amine"]
    attendance.save(conn, desk, session_on(conn, desk, MONDAY).id, {amine: "late"})
    view = StudentDetailView(conn, desk, school["amine_student"])
    qtbot.addWidget(view)
    tab = view.attendance
    assert view.windows["sessions"].section is tab  # every session opens in a window
    assert view.open_sessions.text() == t["overview.sessions"].format(count=1)
    [line] = view.group_lines.lines
    assert line.attendance.text() == t["overview.attendance"].format(
        rate="100 %", sessions=1, absent=0)  # late counts as there
    table = tab.list.table
    assert [table.item(0, c).text() for c in range(4)] == [
        "19/10/2026", "17:00 – 18:30", "M1 · Maths 4AM", "En retard"]
    assert tab.summary.text() == t["student_attendance.summary"].format(
        present=0, late=1, absent=0, excused=0)
