from datetime import date

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QLabel

from tadris.core import dates
from tadris.core.money import format_dzd
from tadris.domain.models import GroupInput, SlotInput, TeacherInput
from tadris.i18n.fr import t
from tadris.services import (
    auth,
    catalog,
    groups,
    rooms,
    school_years,
    settings,
    teachers,
    timetable,
)
from tadris.ui import group_dialogs
from tadris.ui.group_dialogs import ChangeTeacherDialog, GroupDialog, SlotDialog
from tadris.ui.main_window import MainWindow
from tadris.ui.pages import groups as groups_page
from tadris.ui.pages import setup_tabs
from tadris.ui.pages.groups import GroupDetailView, GroupsPage
from tadris.ui.pages.settings import SettingsPage
from tadris.ui.pages.teachers import TeacherDetailView, TeachersPage
from tadris.ui.pages.timetable import TimetablePage, week_start
from tadris.ui.setup_dialogs import NameDialog, RoomDialog, YearDialog
from tadris.ui.teacher_dialogs import TeacherDialog
from tadris.ui.theme import apply_theme, load_fonts
from tadris.ui.widgets.timetable_grid import GUTTER, HEADER, HOUR_HEIGHT

TODAY = date(2026, 10, 18)  # a Sunday


@pytest.fixture(autouse=True)
def theme(qapp, monkeypatch):
    load_fonts()
    apply_theme(qapp)
    monkeypatch.setattr(dates, "today", lambda: TODAY)


@pytest.fixture
def director(conn):
    return auth.bootstrap_director(conn, "directeur", "password1", "École Ennour")


@pytest.fixture
def receptionist(conn, director):
    auth.create_user(conn, director, "accueil", "password2", "receptionist")
    return auth.login(conn, "accueil", "password2")


@pytest.fixture
def school(conn, director):
    ids = {
        "year": school_years.create(conn, director, "2026-2027", date(2026, 9, 1),
                                    date(2027, 6, 30)),
        "4am": catalog.create(conn, director, "level", "4AM"),
        "3as": catalog.create(conn, director, "level", "3AS"),
        "maths": catalog.create(conn, director, "subject", "Mathématiques"),
        "physics": catalog.create(conn, director, "subject", "Physique"),
        "room_a": rooms.create(conn, director, "Salle A", 20),
        "room_b": rooms.create(conn, director, "Salle B", 12),
        "karim": teachers.create(conn, director, TeacherInput("Karim Haddad"), 6000,
                                 date(2026, 9, 1)),
        "samia": teachers.create(conn, director, TeacherInput("Samia Rahmani"), 5000,
                                 date(2026, 9, 1)),
    }
    ids["g1"] = groups.create(conn, director, GroupInput(
        ids["year"], ids["4am"], ids["maths"], "Maths 4AM G1", 3000, 12, date(2026, 9, 15)),
        ids["karim"])
    return ids


def click(qtbot, button):
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)


def auto_exec(monkeypatch, dialog_class, fill_and_submit):
    def exec_(self):
        fill_and_submit(self)
        return self.result()
    monkeypatch.setattr(dialog_class, "exec", exec_)


def rows(table) -> list[list[str]]:
    return [[table.item(r, c).text() for c in range(table.columnCount())]
            for r in range(table.rowCount())]


def visible(widget) -> bool:
    return not widget.isHidden()


def keep(qtbot, widget):
    qtbot.addWidget(widget)
    return widget


# ----- Paramètres -----

def test_settings_has_structure_tabs(qtbot, conn, director):
    page = keep(qtbot, SettingsPage(conn, director))
    assert [page.tabs.tabText(i) for i in range(page.tabs.count())] == [
        t[f"settings.tab.{k}"]
        for k in ("school", "users", "years", "levels", "subjects", "rooms", "holidays",
                  "backups", "about")]


def test_year_dialog_suggests_the_label(qtbot, conn, director):
    dialog = keep(qtbot, YearDialog(conn, director))
    qtbot.keyClicks(dialog.start, "01092026")
    assert dialog.label.text() == "2026-2027"
    qtbot.keyClicks(dialog.end, "30062027")
    click(qtbot, dialog.submit)
    assert school_years.get(conn, director, dialog.year_id).state == "open"


def test_year_dialog_shows_overlap(qtbot, conn, director, school):
    dialog = keep(qtbot, YearDialog(conn, director))
    dialog.label.setText("Été")
    dialog.start.set_value(date(2027, 6, 1))
    dialog.end.set_value(date(2027, 8, 31))
    click(qtbot, dialog.submit)
    assert dialog.banner.text() == t["year.overlap"].format(label="2026-2027")


def test_years_tab_open_and_close(qtbot, conn, director, school, monkeypatch):
    upcoming = school_years.create(conn, director, "2027-2028", date(2027, 9, 1),
                                   date(2028, 6, 30))
    tab = keep(qtbot, setup_tabs.YearsTab(conn, director))
    assert [r[3] for r in rows(tab.list.table)] == [t["year_state.upcoming"],
                                                     t["year_state.open"]]
    tab.list.select_id(upcoming)
    assert tab.open.isEnabled() and not tab.close_year.isEnabled()
    click(qtbot, tab.open)
    assert tab.list.error.text() == t["year.other_open"].format(label="2026-2027")
    monkeypatch.setattr(setup_tabs, "confirm", lambda *a: True)
    tab.list.select_id(school["year"])
    click(qtbot, tab.close_year)
    assert school_years.get(conn, director, school["year"]).state == "closed"
    assert groups.get(conn, director, school["g1"]).status == "closed"
    tab.list.select_id(upcoming)
    click(qtbot, tab.open)
    assert school_years.current(conn, director).id == upcoming


def test_levels_tab_add_move_and_deactivate(qtbot, conn, director, school, monkeypatch):
    tab = keep(qtbot, setup_tabs.CatalogTab(conn, director, "level"))
    auto_exec(monkeypatch, NameDialog, lambda d: (d.name.setText("1AM"), d.submit.click()))
    click(qtbot, tab.new)
    assert [r[0] for r in rows(tab.list.table)] == ["4AM", "3AS", "1AM"]
    assert tab.list.selected_id() is not None  # the new level stays selected
    assert tab.move_up.isEnabled() and not tab.move_down.isEnabled()
    click(qtbot, tab.move_up)
    click(qtbot, tab.move_up)
    assert [r[0] for r in rows(tab.list.table)] == ["1AM", "4AM", "3AS"]
    click(qtbot, tab.toggle)
    assert rows(tab.list.table)[0][1] == t["active.no"]
    assert tab.toggle.text() == t["action.activate"]


def test_name_dialog_refuses_duplicates(qtbot, conn, director, school):
    dialog = keep(qtbot, NameDialog(conn, director, "subject"))
    dialog.name.setText("mathematiques")
    click(qtbot, dialog.submit)
    assert dialog.banner.text() == t["name.taken"]


def test_room_dialog_cannot_shrink_below_its_students(qtbot, conn, director, school):
    timetable.add_slot(conn, director, SlotInput(school["g1"], school["room_a"], 2, "17:00",
                                                 "18:30"))
    conn.executescript(f"""
    INSERT INTO students(student_number, first_name, last_name) VALUES ('2026-0001', 'A', 'B');
    INSERT INTO students(student_number, first_name, last_name) VALUES ('2026-0002', 'C', 'D');
    INSERT INTO registrations(student_id, school_year_id, level_id, fee_amount)
      VALUES (1, {school["year"]}, {school["4am"]}, 0), (2, {school["year"]}, {school["4am"]}, 0);
    INSERT INTO enrollments(student_id, group_id, registration_id, enrolled_on)
      VALUES (1, {school["g1"]}, 1, '2026-09-15'), (2, {school["g1"]}, 2, '2026-09-15');
    """)
    room = next(r for r in rooms.list_rooms(conn, director) if r.id == school["room_a"])
    dialog = keep(qtbot, RoomDialog(conn, director, room))
    dialog.capacity.setValue(1)
    click(qtbot, dialog.submit)
    assert dialog.banner.text() == t["db.room_below_group"]


# ----- Enseignants -----

def test_receptionist_sees_teachers_without_rates(qtbot, conn, receptionist, school):
    page = keep(qtbot, TeachersPage(conn, receptionist))
    assert page.list.new_teacher.isHidden()
    headers = [page.list.list.table.horizontalHeaderItem(c).text()
               for c in range(page.list.list.table.columnCount())]
    assert t["teachers.col.rate"] not in headers
    page.open(school["karim"])
    assert page.detail.tabs.count() == 1  # no rate history
    assert page.detail.edit.isHidden() and page.detail.rate.text() == ""


def test_teacher_dialog_creates_with_rate(qtbot, conn, director):
    dialog = keep(qtbot, TeacherDialog(conn, director))
    dialog.full_name.setText("Nabil Cherif")
    dialog.phone.setText("0661 22 33 44")
    dialog.rate.setText("62,5")
    click(qtbot, dialog.submit)
    [rate] = teachers.rates(conn, director, dialog.teacher_id)
    assert (rate.percentage_bp, rate.valid_from) == (6250, "2026-10-18")


def test_teacher_dialog_rate_starts_on_the_arrival(qtbot, conn, director):
    dialog = keep(qtbot, TeacherDialog(conn, director))
    dialog.full_name.setText("DAYDA")
    dialog.rate.setText("40")
    dialog.hire_date.setText("18/10/2026")
    assert dialog.rate_from.text() == "18/10/2026"  # follows the arrival
    dialog.rate_from.setText("21/10/2026")  # chosen by hand: no longer follows
    dialog.hire_date.setText("17/10/2026")
    assert dialog.rate_from.text() == "21/10/2026"
    dialog.rate_from.setText("16/10/2026")  # before the arrival: refused
    click(qtbot, dialog.submit)
    assert dialog.banner.text() == t["rate.before_hire"].format(date="17/10/2026")


def test_teacher_dialog_moves_the_first_rate_earlier(qtbot, conn, director):
    """DAYDA: 40 % saved from 21/10; the same 40 % from 18/10 makes it start there."""
    dayda = teachers.create(conn, director, TeacherInput("DAYDA", hire_date=date(2026, 10, 18)),
                            4000, date(2026, 10, 21))
    dialog = keep(qtbot, TeacherDialog(conn, director, teachers.get(conn, director, dayda)))
    assert "depuis le 21/10/2026" in dialog.findChildren(QLabel, "caption")[-1].text()
    dialog.rate_from.setText("18/10/2026")
    click(qtbot, dialog.submit)
    assert dialog.rate_changed
    assert [(r.percentage_bp, r.valid_from) for r in teachers.rates(conn, director, dayda)] == [
        (4000, "2026-10-18")]


def test_teacher_dialog_invalid_rate(qtbot, conn, director):
    dialog = keep(qtbot, TeacherDialog(conn, director))
    dialog.full_name.setText("Nabil Cherif")
    dialog.rate.setText("120")
    click(qtbot, dialog.submit)
    assert dialog.banner.text() == t["percent.invalid"]


def test_teacher_detail_new_rate(qtbot, conn, director, school, monkeypatch):
    view = keep(qtbot, TeacherDetailView(conn, director, school["karim"]))
    assert rows(view.groups.table)[0][0] == "Maths 4AM G1"
    auto_exec(monkeypatch, TeacherDialog, lambda d: (
        d.rate.setText("65"), d.rate_from.set_value(date(2027, 1, 1)), d.submit.click()))
    click(qtbot, view.edit)  # the rate is in the same window as the rest
    assert [r[:2] for r in rows(view.rates.table)] == [["65 %", "01/01/2027"],
                                                       ["60 %", "01/09/2026"]]
    assert view.rate.text() == t["teacher_detail.rate"].format(rate="65 %")


def test_teacher_with_groups_cannot_be_deactivated(qtbot, conn, director, school, monkeypatch):
    from tadris.ui.pages import teachers as teachers_page
    monkeypatch.setattr(teachers_page, "confirm", lambda *a: True)
    view = keep(qtbot, TeacherDetailView(conn, director, school["karim"]))
    click(qtbot, view.deactivate)
    assert view.error.text() == t["teacher.has_groups"]


# ----- Groupes -----

def test_groups_list_and_filters(qtbot, conn, director, school):
    groups.create(conn, director, GroupInput(school["year"], school["3as"], school["physics"],
                                             "Physique 3AS", 3500, 12, date(2026, 9, 15)),
                  school["samia"])
    owner = keep(qtbot, GroupsPage(conn, director))
    page = owner.list
    assert [r[0] for r in rows(page.list.table)] == ["Maths 4AM G1", "Physique 3AS"]
    assert rows(page.list.table)[0][4:6] == ["3 000 DA", "0 / 12"]
    page.level.setCurrentIndex(page.level.findData(school["3as"]))
    assert [r[0] for r in rows(page.list.table)] == ["Physique 3AS"]
    page.level.setCurrentIndex(0)
    page.search.setText("karim")
    page.refresh()
    assert [r[0] for r in rows(page.list.table)] == ["Maths 4AM G1"]


def test_groups_filter_button_counts_and_resets(qtbot, conn, director, school):
    owner = keep(qtbot, GroupsPage(conn, director))
    page = owner.list
    assert page.filters.text() == t["filters.button"]
    page.level.setCurrentIndex(page.level.findData(school["3as"]))
    page.status.setCurrentIndex(page.status.findData("all"))
    assert page.filters.text() == "Filtres (2)"
    assert rows(page.list.table) == []
    page.filters.reset.click()
    assert page.filters.text() == t["filters.button"]
    assert (page.level.currentData(), page.status.currentData()) == (None, "open")
    assert [r[0] for r in rows(page.list.table)] == ["Maths 4AM G1"]


def test_receptionist_cannot_create_groups(qtbot, conn, receptionist, school):
    page = keep(qtbot, GroupsPage(conn, receptionist))
    assert page.list.new_group.isHidden()
    page.open(school["g1"])
    detail = page.detail
    assert detail.edit.isHidden() and detail.more.isHidden()
    assert not detail.change_teacher.isVisible()
    assert visible(detail.add_slot)  # the front desk manages the timetable


def test_groups_page_without_year(qtbot, conn, director):
    owner = keep(qtbot, GroupsPage(conn, director))
    assert owner.list.list.empty.text() == t["groups.no_year"]


def test_group_dialog_creates_group(qtbot, conn, director, school):
    dialog = keep(qtbot, GroupDialog(conn, director))
    assert dialog.start.text() == "18/10/2026"  # the year started: today
    dialog.level.setCurrentIndex(dialog.level.findData(school["3as"]))
    dialog.subject.setCurrentIndex(dialog.subject.findData(school["physics"]))
    dialog.name.setText("Physique 3AS")
    dialog.price.setText("3 500")
    dialog.capacity.setValue(10)
    dialog.teacher.setCurrentIndex(dialog.teacher.findData(school["samia"]))
    click(qtbot, dialog.submit)
    group = groups.get(conn, director, dialog.group_id)
    assert (group.name, group.price, group.capacity, group.teacher) == (
        "Physique 3AS", 3500, 10, "Samia Rahmani")


def test_group_dialog_errors(qtbot, conn, director, school):
    dialog = keep(qtbot, GroupDialog(conn, director))
    dialog.name.setText("maths 4am g1")
    dialog.price.setText("3000")
    click(qtbot, dialog.submit)
    assert dialog.banner.text() == t["group.name_taken"]
    dialog.price.setText("trois mille")
    click(qtbot, dialog.submit)
    assert dialog.banner.text() == t["money.invalid"]


def test_group_dialog_needs_a_teacher(qtbot, conn, director):
    school_years.create(conn, director, "2026-2027", date(2026, 9, 1), date(2027, 6, 30))
    dialog = keep(qtbot, GroupDialog(conn, director))
    assert not dialog.submit.isEnabled()


def test_group_dialog_starts_with_the_default_price(qtbot, conn, director, school):
    assert keep(qtbot, GroupDialog(conn, director)).price.text() == ""  # none set
    settings.save_school(conn, director, "École Ennour", "", "", "08:00", "20:00",
                         group_price=3500)
    assert keep(qtbot, GroupDialog(conn, director)).price.text() == "3 500 DA"
    existing = groups.search(conn, director)[0]
    edit = keep(qtbot, GroupDialog(conn, director, group=existing))
    assert edit.price.text() == format_dzd(existing.price)  # its own price, not the default


def test_group_detail_change_teacher_and_close(qtbot, conn, director, school, monkeypatch):
    view = keep(qtbot, GroupDetailView(conn, director, school["g1"]))
    assert [r[0] for r in rows(view.history.table)] == ["Karim Haddad"]
    assert visible(view.more)
    auto_exec(monkeypatch, ChangeTeacherDialog, lambda d: (
        d.valid_from.set_value(date(2026, 11, 1)), d.submit.click()))
    view.change_teacher.trigger()
    assert [r[0] for r in rows(view.history.table)] == ["Samia Rahmani", "Karim Haddad"]
    monkeypatch.setattr(groups_page, "confirm", lambda *a: True)
    view.close_group.trigger()
    assert view.status.kind() == "neutral"
    assert not view.close_group.isVisible() and view.reopen.isVisible()
    assert view.add_slot.isHidden()


def test_group_detail_slots(qtbot, conn, director, school, monkeypatch):
    view = keep(qtbot, GroupDetailView(conn, director, school["g1"]))
    auto_exec(monkeypatch, SlotDialog, lambda d: (
        d.room.setCurrentIndex(d.room.findData(school["room_a"])),
        d.day.setCurrentIndex(d.day.findData(2)),
        d.start.setCurrentText("17:00"),
        d.submit.click()))
    click(qtbot, view.add_slot)
    assert rows(view.slots.table) == [["Mardi", "17:00 – 18:30", "Salle A", "18/10/2026"]]


def test_group_detail_header_shows_price_and_places(qtbot, conn, director, school):
    lab = rooms.create(conn, director, "Labo", 8)
    timetable.add_slot(conn, director, SlotInput(school["g1"], lab, 2, "17:00", "18:30"))
    view = keep(qtbot, GroupDetailView(conn, director, school["g1"]))
    note = view.header.note
    assert note.wordWrap() and visible(note)
    assert note.text() == " · ".join([  # no teacher, no start date: they are elsewhere
        t["group_detail.price"].format(price=format_dzd(3000)),
        t["group_detail.places"].format(enrolled=0, seats=8)])  # the room's 8, not 12


# ----- slot dialog -----

def test_slot_dialog_end_follows_start(qtbot, conn, director, school):
    dialog = keep(qtbot, SlotDialog(conn, director, group_id=school["g1"]))
    assert not dialog.group.isEnabled()
    dialog.start.setCurrentText("09:00")
    assert dialog.end.currentText() == "10:30"
    dialog.end.setCurrentText("11:00")
    dialog._touch_end()
    dialog.start.setCurrentText("08:00")
    assert dialog.end.currentText() == "11:00"


def test_slot_dialog_shows_room_clash(qtbot, conn, director, school):
    g2 = groups.create(conn, director, GroupInput(school["year"], school["4am"], school["maths"],
                                                  "Maths 4AM G2", 3000, 12, date(2026, 9, 15)),
                       school["samia"])
    timetable.add_slot(conn, director, SlotInput(school["g1"], school["room_a"], 2, "17:00",
                                                 "18:30"))
    dialog = keep(qtbot, SlotDialog(conn, director, group_id=g2, room_id=school["room_a"],
                                    weekday=2, start="18:00"))
    click(qtbot, dialog.submit)
    assert dialog.banner.text() == t["slot.room_busy"].format(
        room="Salle A", day="mardi", start="17:00", end="18:30", group="Maths 4AM G1")


def test_slot_dialog_accepts_typed_times(qtbot, conn, director, school):
    dialog = keep(qtbot, SlotDialog(conn, director, group_id=school["g1"],
                                    room_id=school["room_a"], weekday=6))
    dialog.start.setCurrentText("9h")
    dialog.end.setCurrentText("1030")
    click(qtbot, dialog.submit)
    [added] = timetable.group_slots(conn, director, school["g1"])
    assert (added.start_time, added.end_time) == ("09:00", "10:30")


def test_slot_dialog_remove(qtbot, conn, director, school, monkeypatch):
    timetable.add_slot(conn, director, SlotInput(school["g1"], school["room_a"], 2, "17:00",
                                                 "18:30"))
    [slot] = timetable.group_slots(conn, director, school["g1"])
    dialog = keep(qtbot, SlotDialog(conn, director, slot))
    monkeypatch.setattr(group_dialogs, "confirm", lambda *a: True)
    click(qtbot, dialog.remove)
    assert dialog.removed
    assert timetable.group_slots(conn, director, school["g1"]) == []


# ----- timetable page and grid -----

def test_week_starts_on_saturday():
    assert week_start(date(2026, 10, 18)) == date(2026, 10, 17)  # Sunday -> Saturday
    assert week_start(date(2026, 10, 17)) == date(2026, 10, 17)
    assert week_start(date(2026, 10, 23)) == date(2026, 10, 17)  # Friday


def test_timetable_page_shows_the_room_week(qtbot, conn, director, school):
    timetable.add_slot(conn, director, SlotInput(school["g1"], school["room_a"], 2, "17:00",
                                                 "18:30"))
    page = keep(qtbot, TimetablePage(conn, director))
    page.resize(1100, 700)
    page.entity.setCurrentIndex(page.entity.findData(school["room_a"]))
    assert [s.group for s in page.grid.slots] == ["Maths 4AM G1"]
    assert page.grid.today_weekday == 7  # Sunday 18/10/2026
    page.mode.setCurrentIndex(page.mode.findData("teacher"))
    page.entity.setCurrentIndex(page.entity.findData(school["samia"]))
    assert page.grid.slots == []
    assert page.hint.text() == t["timetable.empty"]


def test_grid_geometry_and_clicks(qtbot, conn, director, school, monkeypatch):
    monkeypatch.setattr(SlotDialog, "exec", lambda self: 0)  # clicking a block opens it
    timetable.add_slot(conn, director, SlotInput(school["g1"], school["room_a"], 2, "17:00",
                                                 "18:30"))
    page = keep(qtbot, TimetablePage(conn, director))
    page.resize(1100, 700)
    page.show()
    page.entity.setCurrentIndex(page.entity.findData(school["room_a"]))
    grid = page.grid
    [slot] = grid.slots
    rect = grid.slot_rect(slot)
    assert rect.top() == pytest.approx(HEADER + 9 * HOUR_HEIGHT + 1)  # 17:00 from 08:00
    assert rect.height() == pytest.approx(1.5 * HOUR_HEIGHT - 2)
    assert grid.slot_at(rect.center()) is slot
    clicked = []
    grid.slot_clicked.connect(clicked.append)
    qtbot.mouseClick(grid, Qt.MouseButton.LeftButton, pos=rect.center().toPoint())
    assert clicked == [slot]
    width = (grid.width() - GUTTER - 1) / 7
    point = QPointF(GUTTER + width * 0.5, HEADER + 2.6 * HOUR_HEIGHT)  # Saturday ~10:36
    assert grid.cell_at(point) == (6, "10:30")
    assert grid.cell_at(QPointF(10, 100)) is None


def test_reschedule_one_session_from_the_timetable(qtbot, conn, director, school,
                                                   monkeypatch):
    """Tuesday 20/10 17:00 moves to Thursday 22/10 18:00, this week only: the slot stays, the
    grid shows it moved and its makeup at the new place; next week runs as usual."""
    from tadris.ui.pages import timetable as timetable_page
    from tadris.ui.session_dialogs import RescheduleDialog

    timetable.add_slot(conn, director, SlotInput(school["g1"], school["room_a"], 2, "17:00",
                                                 "18:30"))
    page = keep(qtbot, TimetablePage(conn, director))
    page.resize(1100, 700)
    page.show()
    page.mode.setCurrentIndex(page.mode.findData("group"))
    page.entity.setCurrentIndex(page.entity.findData(school["g1"]))
    grid = page.grid
    [slot] = grid.slots
    session = grid.week[slot.id]
    assert (session.date, session.status) == ("2026-10-20", "planned")
    assert page.slot_actions(slot) == ["reschedule", "edit"]

    seen = {}

    def fill(dialog):
        seen["range"] = (dialog.first, dialog.last)
        dialog.date.setText("24/10/2026")  # next week: refused
        dialog.reason.setText("Enseignant en formation")
        dialog._submit()
        seen["banner"] = dialog.banner.text()
        dialog.date.setText("22/10/2026")
        dialog.start.setCurrentText("18:00")
        dialog.end.setCurrentText("19:30")
        dialog.room.setCurrentIndex(dialog.room.findData(school["room_b"]))
        dialog._submit()
    auto_exec(monkeypatch, RescheduleDialog, fill)
    page.run_action("reschedule", slot, session.id)
    assert seen["range"] == (date(2026, 10, 18), date(2026, 10, 23))  # from today to Friday
    assert seen["banner"] == t["session.reschedule_week"].format(first="18/10/2026",
                                                                 last="23/10/2026")
    [slot] = grid.slots  # the slot is still there, unchanged
    assert (slot.weekday, slot.start_time, slot.room) == (2, "17:00", "Salle A")
    assert grid.moved(slot)
    [makeup] = grid.makeups
    assert (makeup.date, makeup.start_time, makeup.room, makeup.makeup_of_date) == (
        "2026-10-22", "18:00", "Salle B", "2026-10-20")
    assert page.slot_actions(slot) == ["undo", "edit"]
    assert page.makeup_actions(makeup) == ["undo"]
    answers = []
    monkeypatch.setattr(timetable_page, "confirm",
                        lambda *args: answers.append(args[3]) or False)
    clicked = []
    grid.makeup_clicked.connect(clicked.append)
    qtbot.mouseClick(grid, Qt.MouseButton.LeftButton,
                     pos=grid.makeup_rect(makeup).center().toPoint())
    assert clicked == [makeup]
    assert answers == [t["timetable.action.undo"]]  # its one action asks first; « no » here
    assert grid.makeups == [makeup]

    page.on.set_value(date(2026, 10, 27))  # next week: as usual
    assert not grid.moved(grid.slots[0]) and grid.makeups == []
    page.on.set_value(TODAY)

    monkeypatch.setattr(timetable_page, "confirm", lambda *args: True)
    page.run_action("undo", None, makeup.makeup_of_session_id)
    assert not grid.moved(grid.slots[0]) and grid.makeups == []
    assert grid.week[slot.id].status == "planned"


def test_the_desk_can_reschedule_too(qtbot, conn, director, receptionist, school):
    timetable.add_slot(conn, director, SlotInput(school["g1"], school["room_a"], 2, "17:00",
                                                 "18:30"))
    page = keep(qtbot, TimetablePage(conn, receptionist))
    page.mode.setCurrentIndex(page.mode.findData("group"))
    page.entity.setCurrentIndex(page.entity.findData(school["g1"]))
    [slot] = page.grid.slots
    assert page.slot_actions(slot) == ["reschedule", "edit"]
    page.on.set_value(date(2026, 11, 24))  # no session generated yet that far: the slot only
    assert page.slot_actions(page.grid.slots[0]) == ["edit"]


def test_double_click_on_grid_prefills_new_slot(qtbot, conn, director, school, monkeypatch):
    page = keep(qtbot, TimetablePage(conn, director))
    page.entity.setCurrentIndex(page.entity.findData(school["room_b"]))
    seen = {}

    def exec_(dialog):
        seen.update(room=dialog.room.currentData(), day=dialog.day.currentData(),
                    start=dialog.start.currentText(), end=dialog.end.currentText())
        dialog.submit.click()
        return dialog.result()
    monkeypatch.setattr(SlotDialog, "exec", exec_)
    page.grid.empty_double_clicked.emit(6, "10:30")
    assert seen == {"room": school["room_b"], "day": 6, "start": "10:30", "end": "12:00"}
    assert [s.weekday for s in page.grid.slots] == [6]


def test_grid_shows_the_school_hours(qtbot, conn, director, school):
    page = keep(qtbot, TimetablePage(conn, director))
    assert (page.grid.first_hour, page.grid.last_hour) == (8, 20)  # default 08:00-20:00
    settings.set_school_hours(conn, director, "07:30", "19:00")
    page.refresh()
    assert (page.grid.first_hour, page.grid.last_hour) == (7, 19)


def test_grid_widens_for_an_older_slot_outside_the_hours(qtbot, conn, director, school):
    timetable.add_slot(conn, director, SlotInput(school["g1"], school["room_a"], 2, "18:30",
                                                 "20:00"))
    # A slot saved before the hours existed (the service now refuses this).
    conn.execute("UPDATE timetable_slots SET end_time = '21:15'")
    page = keep(qtbot, TimetablePage(conn, director))
    page.entity.setCurrentIndex(page.entity.findData(school["room_a"]))
    assert (page.grid.first_hour, page.grid.last_hour) == (8, 22)


# ----- École tab (details and opening hours) -----

def test_school_tab_saves_details_and_hours(qtbot, conn, director):
    tab = keep(qtbot, setup_tabs.SchoolTab(conn, director))
    assert tab.name.text() == "École Ennour"
    assert (tab.opens_at.currentText(), tab.closes_at.currentText()) == ("08:00", "20:00")
    tab.phone.setText("048 55 12 30")
    tab.opens_at.setCurrentText("8h30")
    tab.closes_at.setCurrentText("19:00")
    click(qtbot, tab.save)
    assert tab.error.isHidden()
    assert settings.school_hours(conn) == ("08:30", "19:00")
    assert settings.get(conn, "school.phone") == "048 55 12 30"
    assert tab.opens_at.currentText() == "08:30"



def test_school_tab_saves_the_group_price_and_receipt_lines(qtbot, conn, director):
    tab = keep(qtbot, setup_tabs.SchoolTab(conn, director))
    assert (tab.group_price.text(), tab.receipt_header.text()) == ("", "")
    tab.group_price.setText("3500")
    tab.receipt_header.setText("Agrément n° 12")
    tab.receipt_footer.setText("Frais non remboursables.")
    click(qtbot, tab.save)
    assert tab.error.isHidden()
    assert groups.default_price(conn) == 3500
    assert settings.get(conn, "receipt.footer") == "Frais non remboursables."
    assert tab.group_price.text() == "3 500 DA"  # shown as saved
    tab.group_price.setText("")
    click(qtbot, tab.save)
    assert groups.default_price(conn) == 0
    assert tab.receipt_header.maxLength() == settings.RECEIPT_LINE_MAX


def test_school_tab_refuses_hours_that_cut_a_slot(qtbot, conn, director, school):
    timetable.add_slot(conn, director, SlotInput(school["g1"], school["room_a"], 2, "18:30",
                                                 "20:00"))
    tab = keep(qtbot, setup_tabs.SchoolTab(conn, director))
    tab.closes_at.setCurrentText("19:00")
    tab.phone.setText("0550 00 00 00")
    click(qtbot, tab.save)
    assert tab.error.text() == t["hours.slots_outside"].format(
        count=1, group="Maths 4AM G1", day="mardi", start="18:30", end="20:00")
    assert settings.school_hours(conn) == ("08:00", "20:00")
    assert settings.get(conn, "school.phone") is None  # nothing saved


def test_slot_dialog_offers_only_opening_hours(qtbot, conn, director, school):
    settings.set_school_hours(conn, director, "09:00", "18:00")
    dialog = keep(qtbot, SlotDialog(conn, director, group_id=school["g1"]))
    starts = [dialog.start.itemText(i) for i in range(dialog.start.count())]
    ends = [dialog.end.itemText(i) for i in range(dialog.end.count())]
    assert (starts[0], starts[-1]) == ("09:00", "17:45")
    assert (ends[0], ends[-1]) == ("09:15", "18:00")
    # 17:00 + 1 h 30 would pass closing: the default slot ends at 18:00.
    assert (dialog.start.currentText(), dialog.end.currentText()) == ("16:30", "18:00")
    dialog.start.setCurrentText("17:00")
    assert dialog.end.currentText() == "18:00"  # capped at closing
    dialog.end.setCurrentText("18:30")  # typed past closing
    dialog.room.setCurrentIndex(dialog.room.findData(school["room_a"]))
    click(qtbot, dialog.submit)
    assert dialog.banner.text() == t["slot.outside_hours"].format(opens="09:00", closes="18:00")


# ----- phase 3 acceptance -----

def test_phase_3_acceptance_ui(qtbot, conn, director, receptionist, school, monkeypatch):
    """The director sets up a group; the front desk builds its week on the grid and gets a
    readable message for a clash."""
    desk = keep(qtbot, MainWindow(conn, receptionist))
    click(qtbot, desk.nav_buttons["timetable"])
    page = desk.pages.currentWidget()
    assert isinstance(page, TimetablePage)
    page.mode.setCurrentIndex(page.mode.findData("group"))
    page.entity.setCurrentIndex(page.entity.findData(school["g1"]))

    def add(room, weekday, start):
        def fill(dialog):
            dialog.room.setCurrentIndex(dialog.room.findData(room))
            dialog.day.setCurrentIndex(dialog.day.findData(weekday))
            dialog.start.setCurrentText(start)
            dialog.submit.click()
            add.banner = dialog.banner.text()
        auto_exec(monkeypatch, SlotDialog, fill)
        click(qtbot, page.new_slot)

    add(school["room_a"], 6, "09:00")
    add(school["room_b"], 2, "17:00")
    assert [(s.weekday, s.start_time, s.room) for s in page.grid.slots] == [
        (2, "17:00", "Salle B"), (6, "09:00", "Salle A")]
    add(school["room_b"], 6, "10:00")  # the group is in Salle A until 10:30
    assert add.banner == t["slot.group_busy"].format(
        group="Maths 4AM G1", day="samedi", start="09:00", end="10:30")
    assert len(page.grid.slots) == 2


def test_count_spin_shows_its_value(qtbot):
    from tadris.ui.widgets.inputs import count_spin
    spin = keep(qtbot, count_spin(12))
    spin.resize(180, 38)
    spin.show()
    assert spin.lineEdit().width() > 100  # not squeezed by the stylesheet
    assert spin.lineEdit().text() == "12"


def test_finished_year_cannot_be_opened_from_the_tab(qtbot, conn, director, school,
                                                     monkeypatch):
    school_years.close(conn, director, school["year"])
    monkeypatch.setattr(dates, "today", lambda: date(2027, 7, 15))
    tab = keep(qtbot, setup_tabs.YearsTab(conn, director))
    tab.list.select_id(school["year"])
    assert not tab.open.isEnabled()


def test_pages_reload_when_shown_again(qtbot, conn, director, school):
    window = keep(qtbot, MainWindow(conn, director))
    click(qtbot, window.nav_buttons["timetable"])
    timetable_page = window.pages.currentWidget()
    click(qtbot, window.nav_buttons["groups"])
    groups_list = window.pages.currentWidget().list
    assert groups_list.list.table.rowCount() == 1
    # Changes made elsewhere (another page, the other workstation).
    rooms.create(conn, director, "Salle C", 30)
    groups.create(conn, director, GroupInput(school["year"], school["4am"], school["physics"],
                                             "Physique 4AM", 3000, 12, date(2026, 9, 15)),
                  school["samia"])
    click(qtbot, window.nav_buttons["timetable"])
    assert timetable_page.entity.findText("Salle C") >= 0
    click(qtbot, window.nav_buttons["groups"])
    assert groups_list.list.table.rowCount() == 2
