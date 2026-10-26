from datetime import date

import pytest
from PySide6.QtCore import Qt

from tadris.core import dates
from tadris.domain.models import GroupInput, StudentInput, TeacherInput
from tadris.i18n.fr import t
from tadris.services import (
    auth,
    catalog,
    enrollments,
    groups,
    payments,
    registrations,
    school_years,
    students,
    subscriptions,
    teachers,
)
from tadris.ui.enrollment_dialogs import EnrollDialog, LeaveDialog, SwitchDialog
from tadris.ui.pages.student_detail import StudentDetailView
from tadris.ui.pages.student_groups_tab import StudentGroupsTab
from tadris.ui.theme import apply_theme, load_fonts
from tadris.ui.widgets.date_edit import DateLineEdit


@pytest.fixture(autouse=True)
def theme(qapp, monkeypatch):
    load_fonts()
    apply_theme(qapp)
    monkeypatch.setattr(dates, "today", lambda: date(2026, 10, 18))


@pytest.fixture
def director(conn):
    return auth.bootstrap_director(conn, "directeur", "password1", "École Ennour")


@pytest.fixture
def receptionist(conn, director):
    auth.create_user(conn, director, "accueil", "password2", "receptionist")
    return auth.login(conn, "accueil", "password2")


class School:
    def __init__(self, conn, ctx):
        self.year = school_years.create(conn, ctx, "2026-2027", date(2026, 9, 1),
                                        date(2027, 6, 30))
        self.l4am = catalog.create(conn, ctx, "level", "4AM")
        self.l3am = catalog.create(conn, ctx, "level", "3AM")
        teacher = teachers.create(conn, ctx, TeacherInput("Karim Haddad"), 6000,
                                  date(2026, 9, 1))
        subjects = {name: catalog.create(conn, ctx, "subject", name)
                    for name in ("Maths", "Physique", "Français", "Arabe")}

        def group(name, level, subject, capacity=10, start=date(2026, 9, 1)):
            # One teacher everywhere: no timetable slots, so no teacher clash.
            return groups.create(conn, ctx, GroupInput(self.year, level, subjects[subject],
                                                       name, 3000, capacity, start), teacher)

        self.maths = group("M1", self.l4am, "Maths")
        self.physics = group("P1", self.l4am, "Physique")
        self.french = group("F1", self.l4am, "Français", start=date(2026, 11, 2))
        self.full = group("A1", self.l4am, "Arabe", capacity=1)
        self.maths_3am = group("M3", self.l3am, "Maths")


@pytest.fixture
def school(conn, director):
    s = School(conn, director)
    filler = students.create(conn, director, StudentInput("Plein", "Groupe"))
    registrations.register(conn, director, filler, s.l4am, 0)
    enrollments.enroll(conn, director, filler, s.full)
    return s


@pytest.fixture
def amine(conn, director, school):
    student = students.create(conn, director, StudentInput("Amine", "Benali"))
    registrations.register(conn, director, student, school.l4am, 0)
    return student


def click(qtbot, button):
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)


def auto_exec(monkeypatch, dialog_class, fill_and_submit):
    def exec_(self):
        fill_and_submit(self)
        return self.result()
    monkeypatch.setattr(dialog_class, "exec", exec_)


def make_tab(qtbot, conn, ctx, student_id) -> StudentGroupsTab:
    tab = StudentGroupsTab(conn, ctx, student_id)
    qtbot.addWidget(tab)
    return tab


def rows(tab) -> list[list[str]]:
    table = tab.list.table
    return [[table.item(r, c).text() for c in range(table.columnCount())]
            for r in range(table.rowCount())]


def offered_ids(dialog) -> list[int]:
    return list(dialog.picker.options)


def shown(widget) -> bool:
    return not widget.isHidden()


# ----- tab states -----

def test_not_registered_points_to_the_registration(qtbot, conn, receptionist, school):
    student = students.create(conn, receptionist, StudentInput("Sans", "Inscription"))
    tab = make_tab(qtbot, conn, receptionist, student)
    assert tab.list.empty.text() == t["student_groups.not_registered"]
    assert not shown(tab.enroll)


def test_registered_without_groups(qtbot, conn, receptionist, amine):
    tab = make_tab(qtbot, conn, receptionist, amine)
    assert tab.list.empty.text() == t["student_groups.empty"]
    assert shown(tab.enroll) and shown(tab.list.empty)
    assert not tab.switch.isEnabled() and not tab.leave.isEnabled()


# ----- the enroll dialog -----

def test_dialog_offers_only_valid_groups(qtbot, conn, director, receptionist, school, amine):
    enrollments.enroll(conn, receptionist, amine, school.physics)
    desk = EnrollDialog(conn, receptionist, students.get(conn, receptionist, amine))
    qtbot.addWidget(desk)
    # Not P1 (already in), not A1 (full), not M3 (another level: never).
    assert sorted(offered_ids(desk)) == sorted([school.maths, school.french])
    assert desk.full_note.text() == t["enroll_dialog.full_hidden"].format(count=1)
    boss = EnrollDialog(conn, director, students.get(conn, director, amine))
    qtbot.addWidget(boss)
    assert school.maths_3am not in offered_ids(boss)


def test_enroll_from_the_tab(qtbot, conn, receptionist, school, amine, monkeypatch):
    def fill(dialog):
        dialog.picker.select(school.maths)
        dialog._submit()
    auto_exec(monkeypatch, EnrollDialog, fill)
    tab = make_tab(qtbot, conn, receptionist, amine)
    click(qtbot, tab.enroll)
    assert rows(tab) == [["M1 · Maths 4AM", "Actif", "18/10/2026", "", ""]]
    assert tab.selected().group_id == school.maths  # the new row is selected
    assert tab.leave.isEnabled() and not tab.confirm_trial.isEnabled()


def test_no_group_picked(qtbot, conn, receptionist, amine):
    dialog = EnrollDialog(conn, receptionist, students.get(conn, receptionist, amine))
    qtbot.addWidget(dialog)
    dialog._submit()
    assert dialog.banner.text() == t["enroll_dialog.group_required"]


def test_group_not_started_proposes_its_first_day(qtbot, conn, receptionist, school, amine):
    dialog = EnrollDialog(conn, receptionist, students.get(conn, receptionist, amine))
    qtbot.addWidget(dialog)
    dialog.picker.select(school.french)
    assert dialog.date.text() == "02/11/2026"
    dialog.picker.select(school.maths)
    assert dialog.date.text() == "18/10/2026"


def test_trial_then_confirm(qtbot, conn, receptionist, school, amine, monkeypatch):
    def fill(dialog):
        dialog.picker.select(school.maths)
        dialog.trial.setChecked(True)
        dialog._submit()
    auto_exec(monkeypatch, EnrollDialog, fill)
    tab = make_tab(qtbot, conn, receptionist, amine)
    click(qtbot, tab.enroll)
    assert rows(tab)[0][1] == "Essai"
    assert tab.confirm_trial.isEnabled()
    click(qtbot, tab.confirm_trial)
    assert rows(tab)[0][1:5:3] == ["Actif", "Commencé en essai"]
    # The trial is used: the next dialog cannot offer one.
    dialog = EnrollDialog(conn, receptionist, students.get(conn, receptionist, amine))
    qtbot.addWidget(dialog)
    assert not dialog.trial.isEnabled()


def test_an_old_enrollment_of_another_level_is_still_marked(qtbot, conn, director, school,
                                                            amine):
    """Made before 0010 (director override): it shows its note and can still be left."""
    enrollment_id = enrollments.enroll(conn, director, amine, school.maths)
    conn.execute("UPDATE registrations SET level_id = ? WHERE student_id = ?",
                 (school.l3am, amine))
    tab = make_tab(qtbot, conn, director, amine)
    assert rows(tab)[0][4] == "Autre niveau (inscrit en 3AM)"
    enrollments.leave(conn, director, enrollment_id)


def test_full_group_refused_at_submit_shows_in_the_dialog(qtbot, conn, director, receptionist,
                                                         school, amine):
    dialog = EnrollDialog(conn, receptionist, students.get(conn, receptionist, amine))
    qtbot.addWidget(dialog)
    dialog.picker.select(school.maths)
    groups.update(conn, director, school.maths, GroupInput(  # someone fills it meanwhile
        school.year, school.l4am, groups.get(conn, director, school.maths).subject_id, "M1",
        3000, 1, date(2026, 9, 1)))
    other = students.create(conn, director, StudentInput("Lina", "Haddad"))
    registrations.register(conn, director, other, school.l4am, 0)
    enrollments.enroll(conn, director, other, school.maths)
    dialog._submit()
    assert "complet" in dialog.banner.text()
    assert not dialog.result()


# ----- switch and leave -----

def test_switch_from_the_tab(qtbot, conn, receptionist, school, amine, monkeypatch):
    old = enrollments.enroll(conn, receptionist, amine, school.maths)

    def fill(dialog):
        assert school.maths not in dialog.picker.options  # not the current group
        dialog.picker.select(school.physics)
        dialog._submit()
    auto_exec(monkeypatch, SwitchDialog, fill)
    tab = make_tab(qtbot, conn, receptionist, amine)
    tab.list.select_id(old)
    click(qtbot, tab.switch)
    assert rows(tab) == [
        ["P1 · Physique 4AM", "Actif", "18/10/2026", "", "Vient de M1"],
        ["M1 · Maths 4AM", "Changé de groupe", "18/10/2026", "18/10/2026", ""],
    ]


def test_leave_from_the_tab(qtbot, conn, receptionist, school, amine, monkeypatch):
    enrollment_id = enrollments.enroll(conn, receptionist, amine, school.maths,
                                       enrolled_on=date(2026, 9, 20))

    def fill(dialog):
        dialog.date.setText("10/10/2026")
        dialog.reason.setText("Déménagement")
        dialog._submit()
    auto_exec(monkeypatch, LeaveDialog, fill)
    tab = make_tab(qtbot, conn, receptionist, amine)
    tab.list.select_id(enrollment_id)
    click(qtbot, tab.leave)
    assert rows(tab) == [["M1 · Maths 4AM", "Sorti", "20/09/2026", "10/10/2026", ""]]
    tab.list.select_id(enrollment_id)
    assert not tab.leave.isEnabled() and not tab.switch.isEnabled()


def test_leave_in_the_future_shows_in_the_dialog(qtbot, conn, receptionist, school, amine):
    enrollment_id = enrollments.enroll(conn, receptionist, amine, school.maths)
    dialog = LeaveDialog(conn, receptionist, enrollments.get(conn, receptionist, enrollment_id))
    qtbot.addWidget(dialog)
    assert isinstance(dialog.date, DateLineEdit) and dialog.date.text() == "18/10/2026"
    dialog.date.setText("19/10/2026")
    dialog._submit()
    assert dialog.banner.text() == t["enrollment.leave_future"]


def test_leave_dialog_says_what_happens_to_the_months_to_come(qtbot, conn, receptionist,
                                                               school, amine, monkeypatch):
    enrollment_id = enrollments.enroll(conn, receptionist, amine, school.maths)  # 18/10
    monkeypatch.setattr(dates, "today", lambda: date(2026, 11, 14))
    [month] = subscriptions.for_enrollment(conn, receptionist, enrollment_id)
    subscriptions.renew(conn, receptionist, month.id)  # 18/11 -> 18/12, ahead
    dialog = LeaveDialog(conn, receptionist, enrollments.get(conn, receptionist, enrollment_id))
    qtbot.addWidget(dialog)
    assert dialog.months_note.text() == t["leave.months_cancelled"].format(
        months="18 nov. → 18 déc. (3 000 DA)")
    dialog.date.setText("18/11/2026")  # that month runs on the last day: kept as it is
    assert dialog.months_note.isHidden()
    dialog.date.setText("14/11/2026")
    payments.record(conn, receptionist, amine, 4000, "cash")  # 1 000 paid on the month ahead
    dialog._months()
    assert dialog.months_note.text() == t["leave.months_kept"].format(
        months="18 nov. → 18 déc. (déjà payé 1 000 DA)")


# ----- the student page ties both tabs -----

def test_tabs_refresh_each_other(qtbot, conn, receptionist, school, amine, monkeypatch):
    def fill(dialog):
        dialog.picker.select(school.maths)
        dialog._submit()
    auto_exec(monkeypatch, EnrollDialog, fill)
    view = StudentDetailView(conn, receptionist, amine)
    qtbot.addWidget(view)
    assert shown(view.registration.change_level)
    click(qtbot, view.groups.enroll)
    assert view.registration.groups.text() == "1"
    assert not shown(view.registration.change_level)  # fixed once in a group


# ----- the group page's Élèves tab -----

def group_view(qtbot, conn, ctx, group_id):
    from tadris.ui.pages.groups import GroupDetailView

    view = GroupDetailView(conn, ctx, group_id)
    qtbot.addWidget(view)
    return view


def student_rows(view) -> list[list[str]]:
    table = view.students.list.table
    return [[table.item(r, c).text() for c in range(table.columnCount())]
            for r in range(table.rowCount())]


def test_group_page_opens_on_its_students(qtbot, conn, receptionist, school, amine):
    yanis = students.create(conn, receptionist, StudentInput("Yanis", "Haddad"))
    registrations.register(conn, receptionist, yanis, school.l4am, 0)
    enrollments.enroll(conn, receptionist, yanis, school.maths, trial=True)
    enrollments.enroll(conn, receptionist, amine, school.maths)
    view = group_view(qtbot, conn, receptionist, school.maths)
    assert not view.students.isHidden()  # beside the slots and teachers, no tabs
    assert view.students.summary.text() == "2 / 10 élèves · 8 place(s) libre(s) · 1 en essai"
    assert student_rows(view) == [
        ["Benali Amine", "2026-0002", "Actif", "18/10/2026", "", ""],
        ["Haddad Yanis", "2026-0003", "Essai", "18/10/2026", "", ""],
    ]


def test_past_students_are_shown_on_demand(qtbot, conn, receptionist, school, amine):
    first = enrollments.enroll(conn, receptionist, amine, school.maths)
    enrollments.switch(conn, receptionist, first, school.physics)
    maths = group_view(qtbot, conn, receptionist, school.maths)
    assert student_rows(maths) == []
    assert shown(maths.students.list.empty)
    assert maths.students.show_past.text() == t["group_students.show_past"].format(count=1)
    maths.students.show_past.setChecked(True)
    assert student_rows(maths) == [
        ["Benali Amine", "2026-0002", "Changé de groupe", "18/10/2026", "18/10/2026", ""]]
    physics = group_view(qtbot, conn, receptionist, school.physics)
    assert student_rows(physics)[0][5] == t["group_students.note.switched_in"]
    assert not physics.students.show_past.isEnabled()  # nobody left P1


def test_group_seats_follow_a_small_room(qtbot, conn, director, school, amine):
    from tadris.domain.models import SlotInput
    from tadris.services import rooms, timetable

    small = rooms.create(conn, director, "Salle C", 3)
    timetable.add_slot(conn, director, SlotInput(school.maths, small, 1, "17:00", "18:30"))
    enrollments.enroll(conn, director, amine, school.maths)
    view = group_view(qtbot, conn, director, school.maths)
    assert view.students.summary.text() == "1 / 3 élèves · 2 place(s) libre(s) · 0 en essai"


def test_closing_from_the_group_page_empties_the_list(qtbot, conn, director, school, amine,
                                                      monkeypatch):
    from tadris.ui.pages import groups as groups_page

    enrollments.enroll(conn, director, amine, school.maths)
    view = group_view(qtbot, conn, director, school.maths)
    seen = {}

    def accept(_parent, _title, text, _action):
        seen["text"] = text
        return True
    monkeypatch.setattr(groups_page, "confirm", accept)
    view.close_group.trigger()
    assert "Ses 1 élève(s) en sortiront aujourd'hui" in seen["text"]
    assert student_rows(view) == []
    view.students.show_past.setChecked(True)
    assert student_rows(view)[0][2] == "Sorti"


def test_dialog_and_a_subject_already_taken(qtbot, conn, director, receptionist, school, amine):
    teacher = teachers.create(conn, director, TeacherInput("Prof M2"), 6000, date(2026, 9, 1))
    m2 = groups.create(conn, director, GroupInput(
        school.year, school.l4am, groups.get(conn, director, school.maths).subject_id, "M2",
        3000, 10, date(2026, 9, 1)), teacher)
    enrollments.enroll(conn, receptionist, amine, school.maths)
    desk = EnrollDialog(conn, receptionist, students.get(conn, receptionist, amine))
    qtbot.addWidget(desk)
    assert m2 not in desk.picker.options  # the desk switches instead
    boss = EnrollDialog(conn, director, students.get(conn, director, amine))
    qtbot.addWidget(boss)
    boss.picker.select(m2)
    row = next(r for r in range(boss.picker.table.rowCount())
               if boss.picker.table.item(r, 0).text().startswith("M2"))
    assert boss.picker.table.item(row, 3).text() == t["enroll_dialog.same_subject"]
    assert shown(boss.reason_box)


def test_switch_dialog_offers_the_other_group_of_the_subject(qtbot, conn, director,
                                                            receptionist, school, amine):
    teacher = teachers.create(conn, director, TeacherInput("Prof M2"), 6000, date(2026, 9, 1))
    m2 = groups.create(conn, director, GroupInput(
        school.year, school.l4am, groups.get(conn, director, school.maths).subject_id, "M2",
        3000, 10, date(2026, 9, 1)), teacher)
    old = enrollments.enroll(conn, receptionist, amine, school.maths)
    dialog = SwitchDialog(conn, receptionist, enrollments.get(conn, receptionist, old))
    qtbot.addWidget(dialog)
    assert m2 in dialog.picker.options  # moving within the subject is the normal way
    dialog.picker.select(m2)
    assert not shown(dialog.reason_box)
