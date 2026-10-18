import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from tadris.core.permissions import NAV_ITEMS
from tadris.i18n.fr import t
from tadris.services import auth
from tadris.ui.first_run import FirstRunDialog
from tadris.ui.login_dialog import LoginDialog
from tadris.ui.main_window import MainWindow
from tadris.ui.pages.settings import SettingsPage
from tadris.ui.theme import ICONS_DIR, apply_theme, load_fonts
from tadris.ui.user_dialog import UserDialog


@pytest.fixture(autouse=True)
def theme(qapp):
    load_fonts()
    apply_theme(qapp)


@pytest.fixture
def director(conn):
    return auth.bootstrap_director(conn, "directeur", "password1", "École Ennour")


@pytest.fixture
def receptionist(conn, director):
    auth.create_user(conn, director, "accueil", "password2", "receptionist")
    return auth.login(conn, "accueil", "password2")


def click(qtbot, button):
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)


def test_bundled_fonts_load():
    assert {"Readex Pro", "Reem Kufi", "IBM Plex Mono"} <= load_fonts()


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_theme_icons_ship_for_each_mode(mode):
    assert (ICONS_DIR / f"chevron-down-{mode}.svg").is_file()


# ----- first run -----

def fill_first_run(dialog, password="password1", confirm="password1"):
    dialog.school_name.setText("École Ennour")
    dialog.username.setText("directeur")
    dialog.password.setText(password)
    dialog.password_confirm.setText(confirm)


def test_first_run_creates_director(qtbot, conn):
    dialog = FirstRunDialog(conn)
    qtbot.addWidget(dialog)
    fill_first_run(dialog)
    click(qtbot, dialog.submit)
    assert dialog.ctx is not None
    assert dialog.ctx.role == "director"
    assert auth.user_count(conn) == 1


def test_first_run_password_mismatch(qtbot, conn):
    dialog = FirstRunDialog(conn)
    qtbot.addWidget(dialog)
    fill_first_run(dialog, confirm="password9")
    click(qtbot, dialog.submit)
    assert not dialog.banner.isHidden()
    assert dialog.banner.text() == t["auth.password_mismatch"]
    assert dialog.ctx is None
    assert auth.user_count(conn) == 0


def test_first_run_shows_service_error(qtbot, conn):
    dialog = FirstRunDialog(conn)
    qtbot.addWidget(dialog)
    fill_first_run(dialog, password="court", confirm="court")
    click(qtbot, dialog.submit)
    assert dialog.banner.text() == t["auth.password_short"]
    assert dialog.ctx is None


def test_first_run_fields_are_not_clipped_by_a_long_error(qtbot, conn):
    dialog = FirstRunDialog(conn)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.banner.show_error(t["db.group_full"] + " " + t["first_run.caption"] * 2)
    for field in (dialog.school_name, dialog.username, dialog.password, dialog.password_confirm):
        box = field.parentWidget()
        assert box.height() >= box.sizeHint().height()


# ----- login -----

def test_login_wrong_password_shows_banner(qtbot, conn, director):
    dialog = LoginDialog(conn)
    qtbot.addWidget(dialog)
    dialog.username.setText("directeur")
    dialog.password.setText("wrong-pass")
    click(qtbot, dialog.submit)
    assert dialog.banner.text() == t["auth.invalid"]
    assert dialog.password.text() == ""
    assert dialog.ctx is None
    assert dialog.submit.isEnabled()


def test_login_success_clears_banner(qtbot, conn, director):
    dialog = LoginDialog(conn)
    qtbot.addWidget(dialog)
    dialog.username.setText("directeur")
    dialog.password.setText("wrong-pass")
    click(qtbot, dialog.submit)
    dialog.password.setText("password1")
    click(qtbot, dialog.submit)
    assert dialog.banner.isHidden()
    assert dialog.ctx.user_id == director.user_id


# ----- main window: phase 1 acceptance -----

def status_text(window) -> str:
    return " ".join(label.text() for label in window.statusBar().findChildren(QLabel))


def test_director_sees_every_sidebar_entry(qtbot, conn, director):
    window = MainWindow(conn, director)
    qtbot.addWidget(window)
    assert list(window.nav_buttons) == [key for key, _, _ in NAV_ITEMS]
    assert window.windowTitle() == "Tadris · École Ennour"
    assert "directeur" in status_text(window)
    assert t["role.director"] in status_text(window)


def test_receptionist_sidebar_hides_director_entries(qtbot, conn, receptionist):
    window = MainWindow(conn, receptionist)
    qtbot.addWidget(window)
    assert "payouts" not in window.nav_buttons
    assert "settings" not in window.nav_buttons
    assert "students" in window.nav_buttons
    assert t["role.receptionist"] in status_text(window)


def test_settings_page_lists_users(qtbot, conn, director, receptionist):
    window = MainWindow(conn, director)
    qtbot.addWidget(window)
    click(qtbot, window.nav_buttons["settings"])
    page = window.pages.currentWidget()
    assert isinstance(page, SettingsPage)
    rows = [
        [page.table.item(r, c).text() for c in range(page.table.columnCount())]
        for r in range(page.table.rowCount())
    ]
    assert [row[:3] for row in rows] == [
        ["accueil", t["role.receptionist"], t["user_status.active"]],
        ["directeur", t["role.director"], t["user_status.active"]],
    ]


def test_user_dialog_rejects_duplicate_username(qtbot, conn, director):
    dialog = UserDialog(conn, director)
    qtbot.addWidget(dialog)
    dialog.username.setText("directeur")
    dialog.password.setText("password2")
    dialog.password_confirm.setText("password2")
    click(qtbot, dialog.submit)
    assert dialog.banner.text() == t["auth.username_taken"]
    assert dialog.user_id is None


def test_user_dialog_password_mismatch(qtbot, conn, director):
    dialog = UserDialog(conn, director)
    qtbot.addWidget(dialog)
    dialog.username.setText("accueil")
    dialog.password.setText("password2")
    dialog.password_confirm.setText("password3")
    click(qtbot, dialog.submit)
    assert dialog.banner.text() == t["auth.password_mismatch"]
    assert auth.user_count(conn) == 1


def test_phase_1_acceptance_director_creates_receptionist_who_logs_in(qtbot, conn, director):
    create = UserDialog(conn, director)
    qtbot.addWidget(create)
    create.username.setText("accueil")
    assert create.role.currentData() == "receptionist"
    create.password.setText("password2")
    create.password_confirm.setText("password2")
    click(qtbot, create.submit)
    assert create.user_id is not None

    login = LoginDialog(conn)
    qtbot.addWidget(login)
    login.username.setText("accueil")
    login.password.setText("password2")
    click(qtbot, login.submit)
    assert login.ctx.role == "receptionist"

    receptionist_window = MainWindow(conn, login.ctx)
    director_window = MainWindow(conn, director)
    qtbot.addWidget(receptionist_window)
    qtbot.addWidget(director_window)
    assert set(director_window.nav_buttons) - set(receptionist_window.nav_buttons) == {
        "payouts",
        "settings",
    }


def test_sidebar_switches_pages(qtbot, conn, director):
    window = MainWindow(conn, director)
    qtbot.addWidget(window)
    assert window.nav_buttons["dashboard"].isChecked()
    click(qtbot, window.nav_buttons["students"])
    assert window.nav_buttons["students"].isChecked()
    assert not window.nav_buttons["dashboard"].isChecked()
    title = window.pages.currentWidget().findChild(QLabel, "pageTitle")
    assert title.text() == t["nav.students"]
