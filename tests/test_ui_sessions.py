from datetime import date

import pytest
from PySide6.QtCore import Qt

from tadris.core import dates
from tadris.domain.models import GroupInput, Session, SlotInput, TeacherInput
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
from tadris.ui.pages import attendance
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


def cards(page) -> list[tuple]:
    return [(c.start.text(), c.end.text(), c.title.text(), c.where.text(), c.badge.text(),
             c.count.text(), c.note.text()) for c in page.cards]


def shown(widget) -> bool:
    return not widget.isHidden()


@pytest.fixture(autouse=True)
def morning(monkeypatch):
    monkeypatch.setattr(attendance, "now_time", lambda: "10:00")


def test_the_day_and_its_week(qtbot, conn, desk, school):
    page = view(qtbot, conn, desk)
    assert page.period.text() == "Lundi 19 octobre"
    assert page.summary.text() == "1 séance"
    assert cards(page) == [("17:00", "18:30", "M1", "Salle A · Karim Haddad", "Prévue", "0 / 0",
                            "")]
    assert page.cards[0].main_key == "take"
    # Saturday to Friday: a dot for Monday's and Wednesday's sessions; today outlined.
    assert [len(chip.states) for chip in page.chips] == [0, 0, 1, 0, 1, 0, 0]
    assert page.chips[2].isChecked() and page.chips[2].is_today
    click(qtbot, page.chips[4])
    assert page.on.text() == "21/10/2026" and page.period.text() == "Mercredi 21 octobre"
    assert [c.title.text() for c in page.cards] == ["P1"]
    assert page.cards[0].main_key == "roster"  # a day to come: the list, not the attendance


def test_moving_through_days_and_weeks(qtbot, conn, desk, school):
    page = view(qtbot, conn, desk)
    click(qtbot, page.chips[3])
    assert page.cards == [] and shown(page.empty)
    assert page.empty.text() == t["sessions_page.day_empty"]
    click(qtbot, page.following)
    assert page.on.text() == "27/10/2026"  # same weekday, a week later
    for _ in range(2):
        click(qtbot, page.following)
    assert page.empty.text() == t["sessions_page.empty"]  # nothing generated that far
    click(qtbot, page.today)
    assert page.on.text() == "19/10/2026"
    qtbot.keyClick(page.chips[2], Qt.Key.Key_Left)  # unused by the chip: the page moves
    assert page.period.text() == "Dimanche 18 octobre"
    qtbot.keyClick(page.chips[1], Qt.Key.Key_PageDown)
    assert page.period.text() == "Dimanche 25 octobre"


def test_states_through_the_day(qtbot, conn, desk, school, monkeypatch):
    monkeypatch.setattr(attendance, "now_time", lambda: "17:30")
    page = view(qtbot, conn, desk)
    card = page.cards[0]
    assert (card.badge.text(), card.main_key) == ("En cours", "take")
    assert card.main.property("variant") == "primary"
    lines = page._cards
    assert isinstance(lines.itemAt(1).widget(), attendance.NowLine)  # after what started
    monkeypatch.setattr(attendance, "now_time", lambda: "19:00")
    page.refresh()
    assert page.cards[0].badge.text() == "Appel à faire"
    assert page.summary.text() == "1 séance · 1 appel(s) à faire"


def test_session_state_and_summary():
    def at(status, day="2026-10-19", start="17:00", end="18:30"):
        return Session(id=1, group_id=1, group_title="G", group_name="G", slot_id=None,
                       room_id=1, room="A", teacher_id=1, teacher="K",
                       scheduled_teacher_id=None, date=day, start_time=start, end_time=end,
                       status=status, source="generated", cancellation_reason=None,
                       makeup_of_session_id=None, makeup_id=None, makeup_date=None,
                       makeup_of_date=None, attendance_count=0)
    today = "2026-10-19"
    assert attendance.session_state(at("planned"), today, "16:59") == "planned"
    assert attendance.session_state(at("planned"), today, "17:00") == "ongoing"
    assert attendance.session_state(at("planned"), today, "18:30") == "due"
    assert attendance.session_state(at("planned", "2026-10-18"), today, "08:00") == "due"
    assert attendance.session_state(at("held"), today, "08:00") == "held"
    assert attendance.session_state(at("cancelled"), today, "20:00") == "cancelled"
    assert attendance.day_summary([]) == ""
    assert attendance.day_summary(["held", "cancelled", "due"]) == (
        "3 séances · 1 annulée(s) · 1 appel(s) à faire")


def test_clicking_a_card_opens_its_attendance(qtbot, conn, desk, school):
    page = view(qtbot, conn, desk)
    opened = []
    page.opened.connect(opened.append)
    click(qtbot, page.cards[0])
    click(qtbot, page.cards[0].main)
    assert opened == [page.cards[0].session.id] * 2


def test_filters_by_group_and_teacher(qtbot, conn, desk, school):
    page = view(qtbot, conn, desk)
    page.teacher.setCurrentIndex(page.teacher.findData(school["samia"]))
    assert [len(chip.states) for chip in page.chips] == [0, 0, 0, 0, 1, 0, 0]
    assert page.filters.text() == "Filtres (1)"
    page.teacher.setCurrentIndex(0)
    page.group.setCurrentIndex(page.group.findData(school["maths"]))
    assert [len(chip.states) for chip in page.chips] == [0, 0, 1, 0, 0, 0, 0]


def test_cancel_then_restore(qtbot, conn, desk, school, monkeypatch):
    def fill(dialog):
        dialog.reason.setText("Enseignant malade")
        dialog._submit()
    auto_exec(monkeypatch, CancelSessionDialog, fill)
    page = view(qtbot, conn, desk)
    assert set(page.cards[0].actions_by_key) == {"substitute", "cancel"}
    page.cards[0].actions_by_key["cancel"].trigger()
    card = page.cards[0]
    assert cards(page)[0][4:] == ("Annulée", "", "Enseignant malade")
    assert card.main_key == "makeup" and set(card.actions_by_key) == {"restore"}
    card.actions_by_key["restore"].trigger()
    assert page.cards[0].badge.text() == "Prévue"


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
    click(qtbot, page.cards[0].main)
    assert seen["date"] == "20/10/2026"  # the day after, by default
    card = page.cards[0]
    assert card.note.text() == "Grève · Rattrapée le 22/10/2026"
    assert card.main is None and not shown(card.more)  # nothing left to do
    click(qtbot, page.chips[5])
    assert cards(page) == [("09:00", "10:30", "M1", "Salle A · Karim Haddad", "Prévue", "0 / 0",
                            "Rattrapage du 19/10/2026")]


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
    page.cards[0].actions_by_key["substitute"].trigger()
    card = page.cards[0]
    assert card.where.text() == "Salle A · Samia Rahmani" and shown(card.substitute_badge)


def test_reading_only_without_the_right(qtbot, conn, desk, school, monkeypatch):
    from tadris.ui.pages import attendance as page_module

    monkeypatch.setattr(page_module, "allowed", lambda _ctx, action: action != "session.manage")
    page = view(qtbot, conn, desk)
    assert page.cards[0].actions_by_key == {} and not shown(page.cards[0].more)
    assert not page.regenerate.isVisible()


def test_regenerate_reports_what_it_did(qtbot, conn, director, desk, school):
    conn.execute("DELETE FROM sessions WHERE date = '2026-10-26'")
    page = view(qtbot, conn, desk)
    page.regenerate.trigger()
    assert not shown(page.error)
    assert len(sessions.listing(conn, desk, date(2026, 10, 26), date(2026, 10, 26))) == 1
    conn.execute("DELETE FROM sessions WHERE date = '2026-10-26'")
    conn.execute(  # a makeup of P1 now holds Salle A on 26/10 at 17:00
        "INSERT INTO sessions(group_id, room_id, teacher_id, date, start_time, end_time, "
        "source) VALUES (?, ?, ?, '2026-10-26', '17:00', '18:00', 'makeup')",
        (school["physics"], school["room_a"], school["samia"]))
    page.regenerate.trigger()
    assert page.error.text() == t["sessions_page.conflicts"].format(
        count=1, lines=t["sessions_page.conflict_line"].format(
            date="26/10/2026", message=t["db.room_session_overlap"]))


def test_the_page_in_the_sidebar(qtbot, conn, desk, school):
    from tadris.ui.main_window import MainWindow

    window = MainWindow(conn, desk)
    qtbot.addWidget(window)
    window.nav_buttons["attendance"].click()
    page = window.pages.currentWidget()
    assert len(page.sessions.cards) == 1
    assert page.sessions.regenerate.isVisible()  # both roles manage sessions
