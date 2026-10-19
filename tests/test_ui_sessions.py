from datetime import date

import pytest
from PySide6.QtCore import Qt

from tadris.core import dates
from tadris.domain.models import GroupInput, SlotInput, TeacherInput
from tadris.i18n.fr import t
from tadris.services import (
    auth,
    catalog,
    groups,
    rooms,
    school_years,
    sessions,
    teachers,
    timetable,
)
from tadris.ui.pages.attendance import SessionsView
from tadris.ui.session_dialogs import CancelSessionDialog, MakeupDialog, SubstituteDialog
from tadris.ui.theme import apply_theme, load_fonts


@pytest.fixture(autouse=True)
def theme(qapp, monkeypatch):
    load_fonts()
    apply_theme(qapp)
    monkeypatch.setattr(dates, "today", lambda: date(2026, 10, 19))  # a Monday


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
    room_a, room_b = rooms.create(conn, director, "Salle A", 20), rooms.create(conn, director,
                                                                               "Salle B", 20)
    karim = teachers.create(conn, director, TeacherInput("Karim Haddad"), 6000, date(2026, 9, 1))
    samia = teachers.create(conn, director, TeacherInput("Samia Rahmani"), 5000,
                            date(2026, 9, 1))

    def group(name, subject, who):
        subject_id = catalog.create(conn, director, "subject", subject)
        return groups.create(conn, director, GroupInput(year, level, subject_id, name, 3000, 15,
                                                        date(2026, 9, 1)), who)

    maths, physics = group("M1", "Maths", karim), group("P1", "Physique", samia)
    timetable.add_slot(conn, director, SlotInput(maths, room_a, 1, "17:00", "18:30"))  # Mon
    timetable.add_slot(conn, director, SlotInput(physics, room_b, 3, "17:00", "18:30"))  # Wed
    return {"maths": maths, "physics": physics, "karim": karim, "samia": samia,
            "room_a": room_a, "room_b": room_b}


def click(qtbot, button):
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)


def auto_exec(monkeypatch, dialog_class, fill_and_submit):
    def exec_(self):
        fill_and_submit(self)
        return self.result()
    monkeypatch.setattr(dialog_class, "exec", exec_)


def view(qtbot, conn, ctx) -> SessionsView:
    page = SessionsView(conn, ctx)
    qtbot.addWidget(page)
    return page


def rows(page) -> list[list[str]]:
    table = page.list.table
    return [[table.item(r, c).text() for c in range(table.columnCount())]
            for r in range(table.rowCount())]


def shown(widget) -> bool:
    return not widget.isHidden()


def test_today_then_the_week(qtbot, conn, desk, school):
    page = view(qtbot, conn, desk)
    assert page.period.text() == "lundi 19/10/2026"
    assert rows(page) == [["lundi 19/10/2026", "17:00 – 18:30", "M1 · Maths 4AM", "Salle A",
                           "Karim Haddad", "Prévue", "0 / 0", ""]]
    page.mode.setCurrentIndex(1)  # week, from Saturday
    assert page.period.text() == t["sessions_page.period_week"].format(first="17/10/2026",
                                                                       last="23/10/2026")
    assert [r[2] for r in rows(page)] == ["M1 · Maths 4AM", "P1 · Physique 4AM"]


def test_moving_through_days_and_weeks(qtbot, conn, desk, school):
    page = view(qtbot, conn, desk)
    click(qtbot, page.following)
    assert page.period.text() == "mardi 20/10/2026" and rows(page) == []
    assert shown(page.list.empty)
    page.mode.setCurrentIndex(1)
    click(qtbot, page.following)
    assert page.period.text().startswith("Semaine du 24/10/2026")
    click(qtbot, page.today)
    assert page.on.text() == "19/10/2026"


def test_filters_by_group_and_teacher(qtbot, conn, desk, school):
    page = view(qtbot, conn, desk)
    page.mode.setCurrentIndex(1)
    page.teacher.setCurrentIndex(page.teacher.findData(school["samia"]))
    assert [r[2] for r in rows(page)] == ["P1 · Physique 4AM"]
    page.teacher.setCurrentIndex(0)
    page.group.setCurrentIndex(page.group.findData(school["maths"]))
    assert [r[2] for r in rows(page)] == ["M1 · Maths 4AM"]


def test_cancel_then_restore(qtbot, conn, desk, school, monkeypatch):
    def fill(dialog):
        dialog.reason.setText("Enseignant malade")
        dialog._submit()
    auto_exec(monkeypatch, CancelSessionDialog, fill)
    page = view(qtbot, conn, desk)
    page.list.table.selectRow(0)
    assert page.cancel.isEnabled() and not page.restore.isEnabled()
    click(qtbot, page.cancel)
    assert rows(page)[0][5:] == ["Annulée", "—", "Enseignant malade"]
    assert page.restore.isEnabled() and page.makeup.isEnabled()
    assert not page.cancel.isEnabled() and not page.substitute.isEnabled()
    click(qtbot, page.restore)
    assert rows(page)[0][5] == "Prévue"


def test_makeup_from_the_page(qtbot, conn, desk, school, monkeypatch):
    monday = sessions.listing(conn, desk, date(2026, 10, 19), date(2026, 10, 19))[0]
    sessions.cancel(conn, desk, monday.id, "Grève")
    seen = {}

    def fill(dialog):
        seen["date"] = dialog.date.text()
        dialog.date.setText("22/10/2026")
        dialog.start.setCurrentText("09:00")
        dialog.end.setCurrentText("10:30")
        dialog._submit()
    auto_exec(monkeypatch, MakeupDialog, fill)
    page = view(qtbot, conn, desk)
    page.list.table.selectRow(0)
    click(qtbot, page.makeup)
    assert seen["date"] == "20/10/2026"  # the day after, by default
    assert rows(page)[0][7] == "Grève · Rattrapée le 22/10/2026"
    assert not page.makeup.isEnabled() and not page.restore.isEnabled()
    page.mode.setCurrentIndex(1)
    makeup_row = next(r for r in rows(page) if r[0] == "jeudi 22/10/2026")
    assert makeup_row[1:] == ["09:00 – 10:30", "M1 · Maths 4AM", "Salle A", "Karim Haddad",
                              "Prévue", "0 / 0", "Rattrapage du 19/10/2026"]


def test_makeup_clash_shows_in_the_dialog(qtbot, conn, desk, school):
    monday = sessions.listing(conn, desk, date(2026, 10, 19), date(2026, 10, 19))[0]
    sessions.cancel(conn, desk, monday.id, "Grève")
    dialog = MakeupDialog(conn, desk, sessions.get(conn, desk, monday.id))
    qtbot.addWidget(dialog)
    dialog.date.setText("21/10/2026")  # Wednesday 17:00: P1 holds Salle B
    dialog.room.setCurrentIndex(dialog.room.findData(school["room_b"]))
    dialog._submit()
    assert dialog.banner.text() == t["slot.room_busy"].format(
        room="Salle B", day="21/10/2026", start="17:00", end="18:30", group="P1")


def test_substitute_from_the_page(qtbot, conn, desk, school, monkeypatch):
    def fill(dialog):
        dialog.teacher.setCurrentIndex(dialog.teacher.findData(school["samia"]))
        dialog._submit()
    auto_exec(monkeypatch, SubstituteDialog, fill)
    page = view(qtbot, conn, desk)
    page.list.table.selectRow(0)
    click(qtbot, page.substitute)
    assert rows(page)[0][4] == "Samia Rahmani · remplaçant"


def test_regenerate_reports_what_it_did(qtbot, conn, director, desk, school):
    conn.execute("DELETE FROM sessions WHERE date = '2026-10-26'")
    page = view(qtbot, conn, desk)
    click(qtbot, page.regenerate)
    assert not shown(page.list.error)
    assert len(sessions.listing(conn, desk, date(2026, 10, 26), date(2026, 10, 26))) == 1
    conn.execute("DELETE FROM sessions WHERE date = '2026-10-26'")
    conn.execute(  # a makeup of P1 now holds Salle A on 26/10 at 17:00
        "INSERT INTO sessions(group_id, room_id, teacher_id, date, start_time, end_time, "
        "source) VALUES (?, ?, ?, '2026-10-26', '17:00', '18:00', 'makeup')",
        (school["physics"], school["room_a"], school["samia"]))
    click(qtbot, page.regenerate)
    assert page.list.error.text() == t["sessions_page.conflicts"].format(
        count=1, lines=t["sessions_page.conflict_line"].format(
            date="26/10/2026", message=t["db.room_session_overlap"]))


def test_the_page_in_the_sidebar(qtbot, conn, desk, school):
    from tadris.ui.main_window import MainWindow

    window = MainWindow(conn, desk)
    qtbot.addWidget(window)
    window.nav_buttons["attendance"].click()
    page = window.pages.currentWidget()
    assert page.sessions.list.table.rowCount() == 1
    assert shown(page.sessions.regenerate)  # both roles manage sessions
