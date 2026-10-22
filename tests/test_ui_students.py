from datetime import date

import pytest
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QLabel
from shiboken6 import isValid

from tadris.core import dates
from tadris.domain.models import ContactInput, ContactLink, StudentInput
from tadris.i18n.fr import t
from tadris.services import auth, contacts, students
from tadris.ui.contact_dialog import ContactDialog
from tadris.ui.main_window import MainWindow
from tadris.ui.pages import student_detail
from tadris.ui.pages.student_detail import StudentDetailView
from tadris.ui.pages.students import StudentsPage
from tadris.ui.student_dialog import StudentDialog
from tadris.ui.theme import apply_theme, load_fonts
from tadris.ui.widgets.date_edit import DateLineEdit, format_date_typing
from tadris.ui.widgets.tables import ID_ROLE


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


@pytest.fixture
def amine(conn, director):
    return students.create(
        conn, director, StudentInput("Amine", "Benali", date(2012, 3, 14)),
        ContactInput("Karim Benali", "0661902547"), ContactLink("Père"),
    )


def click(qtbot, button):
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)


def auto_exec(monkeypatch, dialog_class, fill_and_submit):
    """Replace a dialog's blocking exec() with: fill the form, click, return the result."""
    def exec_(self):
        fill_and_submit(self)
        return self.result()
    monkeypatch.setattr(dialog_class, "exec", exec_)


def table_rows(table) -> list[list[str]]:
    return [
        [table.item(r, c).text() for c in range(table.columnCount())]
        for r in range(table.rowCount())
    ]


def list_view(qtbot, conn, ctx):
    page = StudentsPage(conn, ctx)
    qtbot.addWidget(page)
    page.list.owner = page  # the Python reference keeps the parent page alive
    return page.list


def visible(widget) -> bool:
    return not widget.isHidden()


# ----- list -----

def test_list_shows_columns_and_count(qtbot, conn, director, amine):
    page = StudentsPage(conn, director)
    qtbot.addWidget(page)
    assert table_rows(page.list.table) == [[
        "2026-0001", "Benali", "Amine", "14/03/2012", "Karim Benali", "0661 90 25 47",
        t["student_status.active"],
    ]]
    assert page.list.count.text() == t["students.count"].format(count=1)
    assert visible(page.list.table) and not visible(page.list.empty)


def test_empty_list_explains_how_to_start(qtbot, conn, director):
    page = StudentsPage(conn, director)
    qtbot.addWidget(page)
    assert visible(page.list.empty) and not visible(page.list.table)
    assert page.list.empty.text() == t["students.empty"]


def test_search_and_status_filter(qtbot, conn, director, amine):
    yanis = students.create(conn, director, StudentInput("Yanis", "Haddad"))
    students.deactivate(conn, director, yanis)
    page = list_view(qtbot, conn, director)
    assert page.student_ids() == [amine]
    page.status.setCurrentIndex(2)  # Tous
    assert sorted(page.student_ids()) == [amine, yanis]
    page.search.setText("0661 90")
    qtbot.waitUntil(lambda: page.student_ids() == [amine])
    page.search.setText("zzz")
    page.refresh()
    assert page.student_ids() == []
    assert page.empty.text() == t["students.no_match"]


def test_columns_sort_by_date_not_text(qtbot, conn, director):
    for first, born in (("A", date(2012, 1, 20)), ("B", date(2011, 12, 5)), ("C", None)):
        students.create(conn, director, StudentInput(first, "Saidi", born))
    page = list_view(qtbot, conn, director)
    page.table.sortByColumn(3, Qt.SortOrder.AscendingOrder)
    assert [row[2] for row in table_rows(page.table)] == ["C", "B", "A"]


def test_status_column_is_a_badge(qtbot, conn, director, amine):
    from tadris.ui.theme.delegates import KIND_ROLE
    page = list_view(qtbot, conn, director)
    assert page.table.item(0, 6).data(KIND_ROLE) == "success"


def test_receptionist_sees_new_student_button(qtbot, conn, receptionist):
    page = list_view(qtbot, conn, receptionist)
    assert visible(page.new_student)


# ----- student dialog -----

def fill_student(dialog, last="Benali", first="Amine", born="14/03/2012"):
    dialog.last_name.setText(last)
    dialog.first_name.setText(first)
    dialog.birth_date.setText(born)


def test_student_dialog_creates_with_main_contact(qtbot, conn, receptionist):
    dialog = StudentDialog(conn, receptionist)
    qtbot.addWidget(dialog)
    fill_student(dialog)
    dialog.contact_name.setText("Karim Benali")
    dialog.contact_relation.setCurrentText(t["relation.father"])
    dialog.contact_phone.setText("0661 90 25 47")
    click(qtbot, dialog.submit)
    assert dialog.student_id is not None
    [contact] = contacts.list_for_student(conn, receptionist, dialog.student_id)
    assert (contact.full_name, contact.relation, contact.is_main) == (
        "Karim Benali", t["relation.father"], True
    )


def test_student_dialog_without_contact(qtbot, conn, director):
    dialog = StudentDialog(conn, director)
    qtbot.addWidget(dialog)
    fill_student(dialog, born="")
    click(qtbot, dialog.submit)
    assert students.get(conn, director, dialog.student_id).birth_date is None
    assert contacts.list_for_student(conn, director, dialog.student_id) == []


@pytest.mark.parametrize("born, phone, key", [
    ("31/02/2012", "", "date.invalid"),
    ("14/03/2012", "0661", "phone.invalid"),
])
def test_student_dialog_shows_errors(qtbot, conn, director, born, phone, key):
    dialog = StudentDialog(conn, director)
    qtbot.addWidget(dialog)
    fill_student(dialog, born=born)
    dialog.contact_name.setText("Karim")
    dialog.contact_phone.setText(phone)
    click(qtbot, dialog.submit)
    assert dialog.banner.text() == t[key]
    assert dialog.student_id is None


def test_duplicate_warns_then_creates_on_second_click(qtbot, conn, director, amine):
    dialog = StudentDialog(conn, director)
    qtbot.addWidget(dialog)
    fill_student(dialog)
    click(qtbot, dialog.submit)
    assert dialog.student_id is None
    assert visible(dialog.warning)
    assert "Benali Amine (2026-0001)" in dialog.warning.text()
    assert dialog.submit.text() == t["student_dialog.submit_anyway"]
    click(qtbot, dialog.submit)
    assert dialog.student_id is not None
    assert len(students.search(conn, director, "benali")) == 2


def test_duplicate_check_runs_again_after_a_change(qtbot, conn, director, amine):
    dialog = StudentDialog(conn, director)
    qtbot.addWidget(dialog)
    fill_student(dialog)
    click(qtbot, dialog.submit)
    dialog.first_name.setText("Lina")
    dialog.contact_name.setText("Karim Benali")
    dialog.contact_phone.setText("0661902547")
    click(qtbot, dialog.submit)
    assert dialog.student_id is None
    assert t["student_dialog.duplicate_phone"].format(
        name="Benali Amine", number="2026-0001") in dialog.warning.text()


def test_edit_dialog_prefills_and_saves(qtbot, conn, director, amine):
    dialog = StudentDialog(conn, director, students.get(conn, director, amine))
    qtbot.addWidget(dialog)
    assert (dialog.last_name.text(), dialog.birth_date.text()) == ("Benali", "14/03/2012")
    dialog.notes.setPlainText("Lunettes")
    click(qtbot, dialog.submit)  # its own name is not a duplicate
    assert dialog.result() == StudentDialog.DialogCode.Accepted
    assert students.get(conn, director, amine).notes == "Lunettes"


# ----- detail -----

def test_detail_cards(qtbot, conn, director, amine):
    """The student (identity, registration, contacts) and the study side by side, the money
    under them: no tabs left; the whole lists open in windows."""
    from PySide6.QtWidgets import QTabWidget

    view = StudentDetailView(conn, director, amine)
    qtbot.addWidget(view)
    assert view.findChildren(QTabWidget) == []
    assert view.name.text() == "Benali Amine"
    assert view.number.text() == t["student_detail.number"].format(number="2026-0001")
    assert view.status.kind() == "success"
    for section in (view.registration, view.contacts):
        assert section.isVisibleTo(view)
    for key, section in (("groups", view.groups), ("sessions", view.attendance),
                         ("subscriptions", view.subscriptions),
                         ("payments", view.all_payments)):
        assert view.windows[key].section is section and not section.isVisibleTo(view)
    assert [b.text() for b in view.money_tabs.buttons] == ["À payer", "Reçus"]
    assert view.money_views.count() == 2
    assert [view.money_views.widget(i) for i in range(2)] == [
        view.payments.dues, view.payments.history]
    assert view.contacts.table.isColumnHidden(3) and view.contacts.table.isColumnHidden(4)
    assert table_rows(view.contacts.table)[0][:3] == [
        "Karim Benali", t["relation.father"], "0661 90 25 47"
    ]


def test_the_study_card_keeps_one_line_per_group(qtbot, conn, director, amine, monkeypatch):
    """No list of every session or month on the page: a line per group, and links to the
    whole lists, which open in a window and refresh the page when it closes."""
    from tadris.domain.models import GroupInput, TeacherInput
    from tadris.services import catalog, groups, registrations, school_years, teachers
    from tadris.services import enrollments as enrollments_service
    from tadris.ui.pages.student_overview import SectionWindow

    monkeypatch.setattr(dates, "today", lambda: date(2026, 10, 18))
    year = school_years.create(conn, director, "2026-2027", date(2026, 9, 1), date(2027, 6, 30))
    level = catalog.create(conn, director, "level", "4AM")
    teacher = teachers.create(conn, director, TeacherInput("Karim Haddad"), 6000,
                              date(2026, 9, 1))
    group_id = groups.create(conn, director, GroupInput(
        year, level, catalog.create(conn, director, "subject", "Maths"), "M1", 3000, 10,
        date(2026, 9, 1)), teacher)
    registrations.register(conn, director, amine, level, 0)
    view = StudentDetailView(conn, director, amine)
    qtbot.addWidget(view)
    assert view.group_lines.lines == [] and not view.group_lines.empty.isHidden()
    assert view.open_groups.text() == t["overview.groups"].format(count=0)
    assert not view.enroll.isHidden()
    opened = []

    def exec_(window):
        opened.append(window.windowTitle())
        enrollments_service.enroll(conn, director, amine, group_id)  # done in the window
        return 1
    monkeypatch.setattr(SectionWindow, "exec", exec_)
    click(qtbot, view.open_groups)
    assert opened == [t["overview.window.groups"]]
    [line] = view.group_lines.lines  # the page followed
    assert line.month.text() == t["overview.month"].format(period="18 oct. au 18 nov.",
                                                           left="reste 3 000 DA")
    assert line.attendance.text() == t["overview.no_attendance"]
    assert view.open_subscriptions.text() == t["overview.subscriptions"].format(count=1)


def test_receptionist_cannot_deactivate_from_detail(qtbot, conn, receptionist, amine):
    view = StudentDetailView(conn, receptionist, amine)
    qtbot.addWidget(view)
    assert view.deactivate.isHidden() and view.reactivate.isHidden()
    assert visible(view.edit)


def test_director_deactivates_after_confirm(qtbot, conn, director, amine, monkeypatch):
    view = StudentDetailView(conn, director, amine)
    qtbot.addWidget(view)
    monkeypatch.setattr(student_detail, "confirm", lambda *a: False)
    click(qtbot, view.deactivate)
    assert students.get(conn, director, amine).status == "active"
    monkeypatch.setattr(student_detail, "confirm", lambda *a: True)
    click(qtbot, view.deactivate)
    assert students.get(conn, director, amine).status == "inactive"
    assert view.status.kind() == "neutral"
    assert view.deactivate.isHidden() and visible(view.reactivate)
    click(qtbot, view.reactivate)
    assert students.get(conn, director, amine).status == "active"


def test_deactivate_error_shows_on_the_page(qtbot, conn, director, amine, monkeypatch):
    view = StudentDetailView(conn, director, amine)
    qtbot.addWidget(view)
    monkeypatch.setattr(student_detail, "confirm", lambda *a: True)
    students.deactivate(conn, director, amine)  # changed elsewhere meanwhile
    click(qtbot, view.deactivate)
    assert view.error.text() == t["student.already_inactive"]
    assert visible(view.error)


# ----- contacts tab -----

def fill_contact(name, phone, relation="", main=None):
    def fill(dialog):
        dialog.full_name.setText(name)
        dialog.phone.setText(phone)
        dialog.relation.setCurrentText(relation)
        if main is not None:
            dialog.is_main.setChecked(main)
        dialog.submit.click()
    return fill


def test_add_second_contact_and_make_it_main(qtbot, conn, director, amine, monkeypatch):
    view = StudentDetailView(conn, director, amine)
    qtbot.addWidget(view)
    tab = view.contacts
    auto_exec(monkeypatch, ContactDialog,
              fill_contact("Nadia Benali", "0770 11 22 33", t["relation.mother"]))
    click(qtbot, tab.add)
    rows = table_rows(tab.table)
    assert [r[0] for r in rows] == ["Karim Benali", "Nadia Benali"]
    assert [r[5] for r in rows] == [t["contacts.main_badge"], ""]
    assert tab.selected().full_name == "Nadia Benali"
    click(qtbot, tab.make_main)
    assert [r[0] for r in table_rows(tab.table)] == ["Nadia Benali", "Karim Benali"]
    assert tab.selected().is_main and not tab.make_main.isEnabled()


def test_unlink_main_contact_shows_reason(qtbot, conn, director, amine, monkeypatch):
    contacts.add(conn, director, amine, ContactInput("Nadia Benali", "0770112233"))
    view = StudentDetailView(conn, director, amine)
    qtbot.addWidget(view)
    tab = view.contacts
    monkeypatch.setattr(student_detail, "confirm", lambda *a: True)
    tab.table.selectRow(0)
    click(qtbot, tab.unlink)
    assert tab.error.text() == t["contact.main_required_first"]
    tab.table.selectRow(1)
    click(qtbot, tab.unlink)
    assert [r[0] for r in table_rows(tab.table)] == ["Karim Benali"]


def test_first_contact_dialog_locks_main(qtbot, conn, director):
    student_id = students.create(conn, director, StudentInput("Lina", "Haddad"))
    dialog = ContactDialog(conn, director, student_id, is_first=True)
    qtbot.addWidget(dialog)
    assert dialog.is_main.isChecked() and not dialog.is_main.isEnabled()


def test_sibling_links_existing_contact(qtbot, conn, director, amine):
    sister = students.create(conn, director, StudentInput("Lina", "Benali"))
    dialog = ContactDialog(conn, director, sister, is_first=True)
    qtbot.addWidget(dialog)
    dialog.full_name.setText("K. Benali")
    dialog.phone.setText("0661 90 25 47")
    click(qtbot, dialog.submit)
    assert visible(dialog.warning) and "Benali Amine" in dialog.warning.text()
    assert dialog.submit.text() == t["contact_dialog.link_existing"]
    click(qtbot, dialog.submit)
    [linked] = contacts.list_for_student(conn, director, sister)
    assert linked.full_name == "Karim Benali"  # existing contact, unchanged
    assert linked.shared_with == ("Benali Amine",)


def test_existing_contact_can_be_declined(qtbot, conn, director, amine):
    sister = students.create(conn, director, StudentInput("Lina", "Benali"))
    dialog = ContactDialog(conn, director, sister, is_first=True)
    qtbot.addWidget(dialog)
    dialog.full_name.setText("Grand-mère Benali")
    dialog.phone.setText("0661902547")
    click(qtbot, dialog.submit)
    click(qtbot, dialog.create_new)
    [linked] = contacts.list_for_student(conn, director, sister)
    assert linked.full_name == "Grand-mère Benali"
    assert linked.shared_with == ()


def test_editing_shared_contact_warns(qtbot, conn, director, amine):
    sister = students.create(conn, director, StudentInput("Lina", "Benali"))
    [father] = contacts.list_for_student(conn, director, amine)
    contacts.link_existing(conn, director, sister, father.contact_id)
    [shared] = contacts.list_for_student(conn, director, amine)
    dialog = ContactDialog(conn, director, amine, shared)
    qtbot.addWidget(dialog)
    assert "Benali Lina" in dialog.note.text()
    assert not dialog.is_main.isEnabled()


# ----- phase 2 acceptance -----

def test_phase_2_acceptance(qtbot, conn, director, receptionist, monkeypatch):
    """A student with two contacts is created, edited and deactivated, never deleted."""
    front_desk = MainWindow(conn, receptionist)
    qtbot.addWidget(front_desk)
    click(qtbot, front_desk.nav_buttons["students"])
    page = front_desk.pages.currentWidget()
    assert isinstance(page, StudentsPage)

    auto_exec(monkeypatch, StudentDialog, lambda d: (
        fill_student(d),
        d.contact_name.setText("Karim Benali"),
        d.contact_phone.setText("0661902547"),
        d.submit.click(),
    ))
    click(qtbot, page.list.new_student)
    assert page.stack.currentWidget() is page.detail  # opens on the new student
    student_id = page.detail.student_id
    assert "2026-0001" in front_desk.statusBar().currentMessage()

    auto_exec(monkeypatch, ContactDialog, fill_contact("Nadia Benali", "0770112233"))
    click(qtbot, page.detail.contacts.add)
    assert len(contacts.list_for_student(conn, receptionist, student_id)) == 2

    auto_exec(monkeypatch, StudentDialog, lambda d: (
        d.first_name.setText("Amine Rayan"), d.submit.click()
    ))
    click(qtbot, page.detail.edit)
    assert page.detail.name.text() == "Benali Amine Rayan"
    assert page.detail.deactivate.isHidden()  # front desk cannot deactivate

    click(qtbot, page.detail.back_button)
    assert page.stack.currentWidget() is page.list
    assert page.list.table.item(0, 2).text() == "Amine Rayan"

    director_window = MainWindow(conn, director)
    qtbot.addWidget(director_window)
    click(qtbot, director_window.nav_buttons["students"])
    director_page = director_window.pages.currentWidget()
    index = director_page.list.table.model().index(0, 0)
    director_page.list.table.activated.emit(index)
    monkeypatch.setattr(student_detail, "confirm", lambda *a: True)
    click(qtbot, director_page.detail.deactivate)
    click(qtbot, director_page.detail.back_button)
    assert director_page.list.student_ids() == []
    director_page.list.status.setCurrentIndex(1)  # Inactifs
    assert director_page.list.student_ids() == [student_id]
    assert conn.execute("SELECT COUNT(*) FROM students").fetchone()[0] == 1
    assert director_page.list.table.item(0, 0).data(ID_ROLE) == student_id
    title = director_page.list.findChild(QLabel, "pageTitle")
    assert title.text() == t["nav.students"]


# ----- birth date field -----

@pytest.mark.parametrize("typed, shown", [
    ("2", "2"),
    ("29", "29"),
    ("291", "29/1"),
    ("29102003", "29/10/2003"),
    ("2910200399", "29/10/2003"),       # extra digits dropped
    ("29/10/2003", "29/10/2003"),       # already formatted: unchanged
    ("29-10-2003", "29/10/2003"),       # pasted with another separator
    ("29.10.2003", "29/10/2003"),
    ("2/10/2003", "21/02/003"),         # a digit erased mid-field: digits regroup
    ("29/", "29"),
    ("/", ""),
    ("٢٩١٠٢٠٠٣", "29/10/2003"),
    ("29a10", "29/10"),
    ("", ""),
])
def test_format_date_typing(typed, shown):
    assert format_date_typing(typed) == shown


@pytest.fixture
def date_field(qtbot):
    field = DateLineEdit()
    qtbot.addWidget(field)
    field.show()
    field.setFocus()
    return field


def test_typing_digits_inserts_slashes(qtbot, date_field):
    qtbot.keyClicks(date_field, "29102003")
    assert date_field.text() == "29/10/2003"
    assert date_field.cursorPosition() == 10


def test_typing_day_with_slash(qtbot, date_field):
    qtbot.keyClicks(date_field, "1/2/2012")
    assert date_field.text() == "01/02/2012"


def test_separator_after_full_group_is_ignored(qtbot, date_field):
    qtbot.keyClicks(date_field, "29/10/2003")
    assert date_field.text() == "29/10/2003"
    qtbot.keyClicks(date_field, "/")
    assert date_field.text() == "29/10/2003"


def test_paste_regroups(qtbot, date_field):
    from PySide6.QtGui import QGuiApplication
    QGuiApplication.clipboard().setText("29-10-2003")
    date_field.paste()
    assert date_field.text() == "29/10/2003"


def test_backspace_erases_through_slashes(qtbot, date_field):
    qtbot.keyClicks(date_field, "29102003")
    for expected in ("29/10/200", "29/10/20", "29/10/2", "29/10", "29/1", "29", "2", ""):
        qtbot.keyClick(date_field, Qt.Key.Key_Backspace)
        assert date_field.text() == expected


def test_backspace_after_a_middle_slash_erases_the_digit(qtbot, date_field):
    qtbot.keyClicks(date_field, "29102003")
    date_field.setCursorPosition(3)  # 29/|10/2003
    qtbot.keyClick(date_field, Qt.Key.Key_Backspace)
    assert date_field.text() == "21/02/003"
    assert date_field.cursorPosition() == 1


def test_editing_the_middle_keeps_the_cursor(qtbot, date_field):
    qtbot.keyClicks(date_field, "2910203")
    date_field.setCursorPosition(8)  # 29/10/20|3
    qtbot.keyClicks(date_field, "0")
    assert date_field.text() == "29/10/2003"
    assert date_field.cursorPosition() == 9


def test_student_dialog_birth_date_typed_without_slashes(qtbot, conn, director):
    dialog = StudentDialog(conn, director)
    qtbot.addWidget(dialog)
    dialog.last_name.setText("Benali")
    dialog.first_name.setText("Amine")
    qtbot.keyClicks(dialog.birth_date, "14032012")
    click(qtbot, dialog.submit)
    assert students.get(conn, director, dialog.student_id).birth_date == "2012-03-14"


# ----- calendar -----

def test_calendar_button_is_in_the_field(date_field):
    assert date_field.calendar_action in date_field.actions()
    assert date_field.calendar_action.toolTip() == t["date.pick"]


def test_calendar_pick_fills_the_field(qtbot, date_field):
    popup = date_field.open_calendar()
    popup.calendar.clicked.emit(QDate(2012, 3, 14))
    assert date_field.text() == "14/03/2012"
    assert not popup.isVisible()


def test_calendar_opens_on_the_typed_date(qtbot, date_field):
    qtbot.keyClicks(date_field, "14032012")
    popup = date_field.open_calendar()
    assert popup.calendar.selectedDate() == QDate(2012, 3, 14)
    popup.close()


def test_calendar_opens_on_suggested_month_when_empty(qtbot):
    field = DateLineEdit(suggested=date(2016, 10, 1), maximum=date(2026, 10, 18))
    qtbot.addWidget(field)
    popup = field.open_calendar()
    assert (popup.calendar.yearShown(), popup.calendar.monthShown()) == (2016, 10)
    assert popup.calendar.maximumDate() == QDate(2026, 10, 18)
    popup.close()


def test_alt_down_opens_calendar(qtbot, date_field):
    qtbot.keyClick(date_field, Qt.Key.Key_Down, Qt.KeyboardModifier.AltModifier)
    assert date_field.popup is not None and date_field.popup.isVisible()
    date_field.popup.close()


def test_birth_date_calendar_refuses_the_future(qtbot, conn, director):
    dialog = StudentDialog(conn, director)
    qtbot.addWidget(dialog)
    popup = dialog.birth_date.open_calendar()
    assert popup.calendar.maximumDate() == QDate(2026, 10, 18)  # dates.today() in tests
    assert (popup.calendar.yearShown(), popup.calendar.monthShown()) == (2016, 10)
    popup.calendar.clicked.emit(QDate(2012, 3, 14))
    dialog.last_name.setText("Benali")
    dialog.first_name.setText("Amine")
    click(qtbot, dialog.submit)
    assert students.get(conn, director, dialog.student_id).birth_date == "2012-03-14"


def test_calendar_weekend_is_not_red(qtbot, date_field):
    from tadris.ui.theme import tokens
    popup = date_field.open_calendar()

    def color(day):
        return popup.calendar.weekdayTextFormat(day).foreground().color().name().upper()

    for day in (Qt.DayOfWeek.Friday, Qt.DayOfWeek.Saturday, Qt.DayOfWeek.Sunday):
        assert color(day) == tokens()["text"]
    popup.close()


# ----- calendar: month and year pickers -----

@pytest.fixture
def popup(qtbot):
    field = DateLineEdit(minimum=date(1940, 1, 1), maximum=date(2026, 10, 18))
    qtbot.addWidget(field)
    field.set_value(date(2012, 3, 14))
    popup = field.open_calendar()
    popup.field = field
    yield popup
    if isValid(popup):  # picking a day closes and deletes it
        popup.close()


def enabled_texts(buttons) -> list[str]:
    return [b.text() for b in buttons if b.isEnabled()]


def test_header_shows_month_and_year(popup):
    assert (popup.month_button.text(), popup.year_button.text()) == ("Mars", "2012")
    assert popup.view == popup.DAYS


def test_pick_year_then_month_then_day(qtbot, popup):
    click(qtbot, popup.year_button)
    assert popup.view == popup.YEARS
    assert popup.range_label.text() == "2004 – 2015"
    assert [b.text() for b in popup.year_buttons if b.isChecked()] == ["2012"]
    year_2009 = next(b for b in popup.year_buttons if b.text() == "2009")
    click(qtbot, year_2009)
    assert popup.view == popup.MONTHS
    assert popup.year_button.text() == "2009" and popup.month_button.isHidden()
    click(qtbot, popup.month_buttons[5])  # juin
    assert popup.view == popup.DAYS
    assert (popup.year(), popup.month()) == (2009, 6)
    assert popup.month_button.text() == "Juin"
    popup.calendar.clicked.emit(QDate(2009, 6, 21))
    assert popup.field.text() == "21/06/2009"


def test_month_name_opens_months(qtbot, popup):
    click(qtbot, popup.month_button)
    assert popup.view == popup.MONTHS
    assert [b.text() for b in popup.month_buttons if b.isChecked()] == ["mars"]


def test_year_pages_and_bounds(qtbot, popup):
    click(qtbot, popup.year_button)
    click(qtbot, popup.next)
    assert popup.range_label.text() == "2016 – 2027"
    assert enabled_texts(popup.year_buttons)[-1] == "2026"  # 2027 is after the maximum
    assert not popup.next.isEnabled()
    for _ in range(7):
        click(qtbot, popup.prev)
    assert popup.range_label.text() == "1932 – 1943"
    assert enabled_texts(popup.year_buttons)[0] == "1940"  # the minimum
    assert not popup.prev.isEnabled()


def test_months_after_maximum_are_disabled(qtbot, popup):
    popup.pick_year(2026)
    assert enabled_texts(popup.month_buttons)[-1] == "oct"
    assert not popup.next.isEnabled()


def test_picking_max_year_clamps_the_month(qtbot, popup):
    popup.calendar.setCurrentPage(2012, 12)
    popup.pick_year(2026)
    assert (popup.year(), popup.month()) == (2026, 10)


def test_day_arrows_stop_at_bounds(qtbot, popup):
    popup.calendar.setCurrentPage(2026, 9)
    click(qtbot, popup.next)
    assert (popup.year(), popup.month()) == (2026, 10)
    assert not popup.next.isEnabled()
    click(qtbot, popup.prev)
    assert (popup.year(), popup.month()) == (2026, 9)


def test_escape_steps_back_to_days(qtbot, popup):
    click(qtbot, popup.year_button)
    qtbot.keyClick(popup, Qt.Key.Key_Escape)
    assert popup.view == popup.DAYS
