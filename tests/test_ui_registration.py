from datetime import date

import pytest
from PySide6.QtCore import Qt

from tadris import config
from tadris.core import dates
from tadris.domain.models import GroupInput, StudentInput, TeacherInput
from tadris.i18n.fr import t
from tadris.services import (
    auth,
    catalog,
    enrollments,
    groups,
    registrations,
    school_years,
    settings,
    students,
    teachers,
)
from tadris.ui.pages.registration_tab import RegistrationTab
from tadris.ui.pages.setup_tabs import SchoolTab
from tadris.ui.pages.student_detail import StudentDetailView
from tadris.ui.registration_dialogs import (
    CancelRegistrationDialog,
    ChangeLevelDialog,
    RegistrationDialog,
)
from tadris.ui.theme import apply_theme, load_fonts
from tadris.ui.widgets.inputs import select_data


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
def year(conn, director):
    return school_years.create(conn, director, "2026-2027", date(2026, 9, 1), date(2027, 6, 30))


@pytest.fixture
def levels(conn, director):
    return catalog.create(conn, director, "level", "4AM"), catalog.create(conn, director,
                                                                          "level", "3AS")


@pytest.fixture
def amine(conn, director):
    return students.create(conn, director, StudentInput("Amine", "Benali"))


def click(qtbot, button):
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)


def auto_exec(monkeypatch, dialog_class, fill_and_submit):
    def exec_(self):
        fill_and_submit(self)
        return self.result()
    monkeypatch.setattr(dialog_class, "exec", exec_)


def make_tab(qtbot, conn, ctx, student_id) -> RegistrationTab:
    tab = RegistrationTab(conn, ctx, student_id)
    qtbot.addWidget(tab)
    return tab


def shown(widget) -> bool:
    return not widget.isHidden()


# ----- empty states -----

def test_not_registered_offers_the_registration(qtbot, conn, receptionist, year, levels, amine):
    tab = make_tab(qtbot, conn, receptionist, amine)
    assert tab.empty.text() == t["registration_tab.not_registered"].format(label="2026-2027")
    assert shown(tab.register) and not shown(tab.card)
    assert tab.register.text() == "Inscrire pour l'année 2026-2027"
    assert not shown(tab.history)


def test_no_open_year(qtbot, conn, director, amine):
    tab = make_tab(qtbot, conn, director, amine)
    assert tab.empty.text() == t["registration.no_open_year"]
    assert not shown(tab.register)


def test_inactive_student_cannot_be_registered(qtbot, conn, director, year, amine):
    students.deactivate(conn, director, amine)
    tab = make_tab(qtbot, conn, director, amine)
    assert tab.empty.text() == t["registration_tab.student_inactive"]
    assert not shown(tab.register)


def test_student_card_shows_the_registration(qtbot, conn, director, year, amine):
    view = StudentDetailView(conn, director, amine)
    qtbot.addWidget(view)
    assert view.registration.isVisibleTo(view)
    assert view.registration.grid.isHidden() and not view.registration.summary.isHidden()


def test_reactivating_offers_the_registration_again(qtbot, conn, director, year, amine,
                                                    monkeypatch):
    students.deactivate(conn, director, amine)
    view = StudentDetailView(conn, director, amine)
    qtbot.addWidget(view)
    assert not shown(view.registration.register)
    view.reactivate.trigger()
    assert shown(view.registration.register)


# ----- register -----

def test_register_with_the_default_fee(qtbot, conn, director, receptionist, year, levels,
                                       amine, monkeypatch):
    settings.set_value(conn, director, "defaults.registration_fee", 2000)
    seen = {}

    def fill(dialog):
        seen["fee"] = dialog.fee.text()
        select_data(dialog.level, levels[0])
        dialog._submit()
    auto_exec(monkeypatch, RegistrationDialog, fill)
    tab = make_tab(qtbot, conn, receptionist, amine)
    click(qtbot, tab.register)
    assert seen["fee"] == "2 000 DA"
    assert shown(tab.card) and not shown(tab.register) and not shown(tab.empty)
    assert tab.title.text() == "Année 2026-2027"
    assert (tab.level.text(), tab.fee.text(), tab.due.text()) == ("4AM", "2 000 DA",
                                                                  "2 000 DA")
    assert tab.registered_on.text() == "18/10/2026"
    assert tab.groups.text() == "0"
    assert shown(tab.change_level) and not shown(tab.cancel)  # cancel is for the director


@pytest.mark.parametrize("typed, fee", [("1 500", 1500), ("", 0)])
def test_typed_or_blank_fee(qtbot, conn, director, year, levels, amine, monkeypatch, typed,
                            fee):
    settings.set_value(conn, director, "defaults.registration_fee", 2000)

    def fill(dialog):
        select_data(dialog.level, levels[1])
        dialog.fee.setText(typed)
        dialog._submit()
    auto_exec(monkeypatch, RegistrationDialog, fill)
    tab = make_tab(qtbot, conn, director, amine)
    click(qtbot, tab.register)
    assert registrations.current(conn, director, amine).fee_amount == fee


def test_level_is_required(qtbot, conn, director, year, levels, amine):
    student = students.get(conn, director, amine)
    dialog = RegistrationDialog(conn, director, student,
                                school_years.current(conn, director))
    qtbot.addWidget(dialog)
    dialog._submit()
    assert dialog.banner.text() == t["registration.level_required"]
    assert registrations.current(conn, director, amine) is None


def test_invalid_fee_shows_in_the_dialog(qtbot, conn, director, year, levels, amine):
    dialog = RegistrationDialog(conn, director, students.get(conn, director, amine),
                                school_years.current(conn, director))
    qtbot.addWidget(dialog)
    select_data(dialog.level, levels[0])
    dialog.fee.setText("deux mille")
    dialog._submit()
    assert dialog.banner.text() == t["money.invalid"]


# ----- change level, cancel -----

def test_change_level(qtbot, conn, receptionist, year, levels, amine, monkeypatch):
    registrations.register(conn, receptionist, amine, levels[0], 0)

    def fill(dialog):
        select_data(dialog.level, levels[1])
        dialog._submit()
    auto_exec(monkeypatch, ChangeLevelDialog, fill)
    tab = make_tab(qtbot, conn, receptionist, amine)
    click(qtbot, tab.change_level)
    assert tab.level.text() == "3AS"


def test_change_and_cancel_hidden_while_in_a_group(qtbot, conn, director, year, levels, amine):
    registrations.register(conn, director, amine, levels[0], 0)
    teacher = teachers.create(conn, director, TeacherInput("Prof"), 6000, date(2026, 9, 1))
    subject = catalog.create(conn, director, "subject", "Maths")
    group = groups.create(conn, director, GroupInput(year, levels[0], subject, "M1", 3000, 10,
                                                     date(2026, 9, 1)), teacher)
    enrollments.enroll(conn, director, amine, group)
    tab = make_tab(qtbot, conn, director, amine)
    assert tab.groups.text() == "1"
    assert not shown(tab.change_level) and not shown(tab.cancel)


def test_director_cancels_with_a_reason(qtbot, conn, director, year, levels, amine,
                                        monkeypatch):
    registrations.register(conn, director, amine, levels[0], 2000)
    reasons = iter(["", "Erreur de saisie"])

    def fill(dialog):
        dialog.reason.setText(next(reasons))
        dialog._submit()  # blank: refused, the banner shows
        if not dialog.result():
            assert dialog.banner.text() == t["registration.reason_required"]
            dialog.reason.setText(next(reasons))
            dialog._submit()
    auto_exec(monkeypatch, CancelRegistrationDialog, fill)
    tab = make_tab(qtbot, conn, director, amine)
    assert shown(tab.cancel)
    click(qtbot, tab.cancel)
    assert not shown(tab.card) and shown(tab.register)
    assert shown(tab.history)
    rows = [[tab.history.item(0, c).text() for c in range(5)]]
    assert rows == [["2026-2027", "4AM", "2 000 DA", "Annulée", "18/10/2026"]]


# ----- Paramètres: default fee -----

def test_school_tab_saves_the_default_fee(qtbot, conn, director):
    tab = SchoolTab(conn, director)
    qtbot.addWidget(tab)
    assert tab.registration_fee.text() == "0 DA"
    tab.registration_fee.setText("2 500")
    click(qtbot, tab.save)
    assert registrations.default_fee(conn) == 2500
    assert tab.registration_fee.text() == "2 500 DA"


def test_school_tab_refuses_a_bad_fee_and_saves_nothing(qtbot, conn, director):
    tab = SchoolTab(conn, director)
    qtbot.addWidget(tab)
    tab.phone.setText("0550 12 34 56")
    tab.registration_fee.setText("abc")
    click(qtbot, tab.save)
    assert tab.error.text() == t["money.invalid"]
    assert settings.get(conn, "school.phone") is None


# ----- TADRIS_DB -----

def test_tadris_db_opens_another_database(monkeypatch, tmp_path):
    monkeypatch.delenv(config.DB_ENV, raising=False)
    assert config.db_override() is None
    assert config.db_path().name == "tadris.db"
    monkeypatch.setenv(config.DB_ENV, str(tmp_path / "copie.db"))
    assert config.db_path() == tmp_path / "copie.db"
