import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from tadris.i18n.fr import t
from tadris.services import auth
from tadris.ui.login_dialog import LoginDialog
from tadris.ui.main_window import MainWindow
from tadris.ui.theme import apply_theme, load_fonts


@pytest.fixture(autouse=True)
def theme(qapp):
    load_fonts()
    apply_theme(qapp)


@pytest.fixture
def director(conn):
    return auth.bootstrap_director(conn, "directeur", "password1", "École Ennour")


def enter(qtbot, widget):
    qtbot.keyClick(widget, Qt.Key.Key_Return)


# ----- login: Enter goes down the form -----

@pytest.fixture
def login(qtbot, conn, director):
    dialog = LoginDialog(conn)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    return dialog


def test_enter_after_the_username_goes_to_the_password(qtbot, login):
    qtbot.keyClicks(login.username, "directeur")
    enter(qtbot, login.username)
    assert login.password.hasFocus()
    assert login.banner.isHidden()  # no « incorrect » before the password is typed
    assert login.ctx is None and login.result() == 0


def test_enter_after_the_password_logs_in(qtbot, login, director):
    qtbot.keyClicks(login.username, "directeur")
    enter(qtbot, login.username)
    qtbot.keyClicks(login.password, "password1")
    enter(qtbot, login.password)
    assert login.ctx is not None and login.ctx.user_id == director.user_id
    assert login.result() == LoginDialog.DialogCode.Accepted


def test_a_wrong_password_after_enter_shows_the_banner(qtbot, login):
    qtbot.keyClicks(login.username, "directeur")
    enter(qtbot, login.username)
    qtbot.keyClicks(login.password, "wrong-pass")
    enter(qtbot, login.password)
    assert login.banner.text() == t["auth.invalid"]
    assert login.password.hasFocus() and login.password.text() == ""


def test_enter_with_an_empty_field_never_tries(qtbot, login):
    enter(qtbot, login.username)  # nothing typed yet
    assert login.password.hasFocus() and login.banner.isHidden()
    enter(qtbot, login.password)  # still nothing: back to the username
    assert login.username.hasFocus() and login.banner.isHidden()
    qtbot.keyClicks(login.username, "directeur")
    login.password.setFocus()
    enter(qtbot, login.password)  # no password: nothing happens
    assert login.banner.isHidden() and login.ctx is None


def test_enter_in_the_username_when_both_are_filled_logs_in(qtbot, login):
    login.password.setText("password1")
    qtbot.keyClicks(login.username, "directeur")
    enter(qtbot, login.username)
    assert login.ctx is not None


def test_the_button_still_logs_in(qtbot, login):
    login.username.setText("directeur")
    login.password.setText("password1")
    qtbot.mouseClick(login.submit, Qt.MouseButton.LeftButton)
    assert login.ctx is not None


# ----- back to the page a link came from -----

@pytest.fixture
def window(qtbot, conn, director):
    w = MainWindow(conn, director)
    qtbot.addWidget(w)
    w.show()
    return w


def current(window) -> str:
    return next(key for key, button in window.nav_buttons.items() if button.isChecked())


def test_no_back_button_from_the_sidebar(window):
    window.nav_buttons["groups"].click()
    window.nav_buttons["students"].click()
    assert window.back_bar.isHidden()


def test_see_all_can_go_back_to_the_dashboard(qtbot, window):
    assert current(window) == "dashboard"
    window.go_to("groups")
    assert current(window) == "groups"
    assert window.back_bar.isVisible()
    assert window.back_button.text() == "← Retour : Tableau de bord"
    qtbot.mouseClick(window.back_button, Qt.MouseButton.LeftButton)
    assert current(window) == "dashboard"
    assert window.back_bar.isHidden()


def test_links_stack_and_unwind(window):
    window.go_to("payments")
    window.go_to("reports")
    assert window.back_button.text() == "← Retour : Paiements"
    window.back()
    assert current(window) == "payments"
    assert window.back_button.text() == "← Retour : Tableau de bord"
    window.back()
    assert current(window) == "dashboard" and window.back_bar.isHidden()
    window.back()  # nothing left: stays
    assert current(window) == "dashboard"


def test_a_sidebar_click_forgets_the_way_back(window):
    window.go_to("groups")
    window.nav_buttons["teachers"].click()
    assert window.back_bar.isHidden()


def test_alt_left_goes_back(qtbot, window):
    window.go_to("groups")
    qtbot.keyClick(window, Qt.Key.Key_Left, Qt.KeyboardModifier.AltModifier)
    assert current(window) == "dashboard"


def test_the_mouse_back_button_goes_back(window):
    window.go_to("subscriptions")
    page = window.pages.currentWidget()
    press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(5, 5), QPointF(5, 5),
                        Qt.MouseButton.BackButton, Qt.MouseButton.BackButton,
                        Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(page, press)
    assert current(window) == "dashboard"


def test_a_student_opened_from_the_dashboard_can_go_back(conn, director, window):
    from tadris.domain.models import StudentInput
    from tadris.services import students

    student = students.create(conn, director, StudentInput("Amine", "Benali"))
    window.open_student(student)
    assert current(window) == "students"
    assert window.back_button.text() == "← Retour : Tableau de bord"
    window.back()
    assert current(window) == "dashboard"
