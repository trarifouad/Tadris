import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QLabel

from tadris.core.errors import PermissionDenied
from tadris.core.permissions import NAV_ITEMS
from tadris.i18n.fr import t
from tadris.services import auth
from tadris.ui.first_run import FirstRunDialog
from tadris.ui.login_dialog import LoginDialog
from tadris.ui.main_window import MainWindow
from tadris.ui.pages.settings import SettingsPage
from tadris.ui.theme import ICONS_DIR, apply_theme, load_fonts, tokens
from tadris.ui.user_dialog import PasswordDialog, UserDialog
from tadris.ui.widgets.tables import CENTER, RIGHT, fill, item, ruled_table


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
    assert (ICONS_DIR / f"check-{mode}.svg").is_file()


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


# ----- table rows (hover and selection span the row) -----

def make_table(qtbot):
    table = ruled_table(["A", "B", "C"])
    fill(table, [[item(f"{r}{c}") for c in "abc"] for r in range(4)])
    table.resize(600, 260)
    qtbot.addWidget(table)
    table.show()
    return table


def pixel(table, row, column, dx=None):
    image = table.viewport().grab().toImage()
    x = table.columnViewportPosition(column) + (table.columnWidth(column) - 4 if dx is None else dx)
    y = table.rowViewportPosition(row) + 4
    return image.pixelColor(x, y).name().upper()


def test_hover_highlights_the_whole_row(qtbot):
    from tadris.ui.theme.delegates import blend
    table = make_table(qtbot)
    delegate = table.itemDelegate()
    pos = QPointF(table.columnViewportPosition(1) + 10, table.rowViewportPosition(2) + 10)
    event = QMouseEvent(QEvent.Type.MouseMove, pos, pos, Qt.MouseButton.NoButton,
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(table.viewport(), event)
    assert delegate.hover_row == 2
    hover = blend(tokens()["surface"], tokens()["surface_alt"], 0.55).name().upper()
    assert {pixel(table, 2, c) for c in range(3)} == {hover}
    assert pixel(table, 1, 1) == tokens()["surface"]
    QApplication.sendEvent(table.viewport(), QEvent(QEvent.Type.Leave))
    assert delegate.hover_row == -1


def test_selection_fills_the_row_with_a_leading_edge(qtbot):
    table = make_table(qtbot)
    table.setFocus()
    table.setCurrentCell(1, 1)  # current cell: must not get a focus box
    assert {pixel(table, 1, c) for c in range(3)} == {tokens()["primary_soft"]}
    assert pixel(table, 1, 1, dx=1) == tokens()["primary_soft"]  # no frame on the left edge
    assert pixel(table, 1, 0, dx=1) == tokens()["primary"]  # 3 px ink edge
    assert pixel(table, 1, 1, dx=1) != tokens()["primary"]


# ----- closed dialogs and popups are freed -----

def test_closed_dialogs_and_calendars_do_not_pile_up(qtbot, conn, director, monkeypatch):
    import gc

    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QApplication, QDialog

    from tadris.ui.pages.students import StudentsPage
    from tadris.ui.student_dialog import StudentDialog
    from tadris.ui.widgets.date_edit import DateLineEdit

    page = StudentsPage(conn, director)
    field = DateLineEdit()
    qtbot.addWidget(page)
    qtbot.addWidget(field)
    monkeypatch.setattr(StudentDialog, "exec", lambda self: QDialog.DialogCode.Rejected)

    def live() -> int:
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        gc.collect()
        return len(QApplication.allWidgets())

    before = live()
    for _ in range(10):
        page.list._create()  # opened, then Annuler
        field.open_calendar().close()
    assert live() == before


def test_headers_line_up_with_their_cells(qtbot):
    """A centered date or a right-aligned amount has its header above it, whether the
    table is filled at once or cell by cell."""
    left = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    center = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
    right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

    def headers(table):
        return [Qt.AlignmentFlag(table.horizontalHeaderItem(c).textAlignment())
                for c in range(table.columnCount())]

    filled = ruled_table(["Nom", "Naissance", "Montant"])
    qtbot.addWidget(filled)
    fill(filled, [[item("Benali"), item("12/08/2016", align=CENTER),
                   item("2 500 DA", align=RIGHT)]])
    assert headers(filled) == [left, center, right]

    by_cell = ruled_table(["Nom", "Naissance"])
    qtbot.addWidget(by_cell)
    by_cell.setRowCount(1)
    by_cell.setItem(0, 0, item("Benali"))
    by_cell.setItem(0, 1, item("12/08/2016", align=CENTER))
    qtbot.waitUntil(lambda: headers(by_cell) == [left, center])


# ----- accounts: passwords and disabling -----

def users_section(qtbot, conn, ctx):
    window = MainWindow(conn, ctx)
    qtbot.addWidget(window)
    click(qtbot, window.nav_buttons["settings"])
    page = window.pages.currentWidget()
    page.show_section("users")
    return page.sections["users"]


def test_director_disables_then_enables_a_receptionist(qtbot, monkeypatch, conn, director,
                                                       receptionist):
    from tadris.ui.pages.settings import users as users_page

    monkeypatch.setattr(users_page, "confirm", lambda *args: True)
    section = users_section(qtbot, conn, director)
    assert not section.status.isEnabled()  # nothing selected
    section.select("accueil")
    assert section.status.text() == t["users.disable"]
    click(qtbot, section.status)
    with pytest.raises(PermissionDenied):
        auth.login(conn, "accueil", "password2")
    assert section.table.item(0, 2).text() == t["user_status.disabled"]
    assert section.status.text() == t["users.enable"]  # still selected after the refresh
    click(qtbot, section.status)
    assert auth.login(conn, "accueil", "password2").role == "receptionist"


def test_the_director_cannot_disable_their_own_row(qtbot, conn, director, receptionist):
    section = users_section(qtbot, conn, director)
    section.select("directeur")
    assert section.password.isEnabled()
    assert not section.status.isEnabled()
    assert section.status.toolTip() == t["users.self_tip"]


def test_director_resets_a_forgotten_password(qtbot, conn, director, receptionist):
    dialog = PasswordDialog(conn, director, receptionist.user_id, "accueil")
    qtbot.addWidget(dialog)
    assert dialog.current is None  # nobody asks the director for the forgotten one
    dialog.password.setText("nouveau-pass")
    dialog.password_confirm.setText("nouveau-pass")
    click(qtbot, dialog.submit)
    assert dialog.result() == dialog.DialogCode.Accepted
    assert auth.login(conn, "accueil", "nouveau-pass").user_id == receptionist.user_id


def test_own_password_needs_the_current_one(qtbot, conn, receptionist):
    dialog = PasswordDialog(conn, receptionist, receptionist.user_id, "accueil")
    qtbot.addWidget(dialog)
    dialog.current.setText("wrong-pass")
    dialog.password.setText("nouveau-pass")
    dialog.password_confirm.setText("nouveau-pass")
    click(qtbot, dialog.submit)
    assert dialog.banner.text() == t["auth.wrong_current_password"]
    dialog.current.setText("password2")
    click(qtbot, dialog.submit)
    assert auth.login(conn, "accueil", "nouveau-pass").user_id == receptionist.user_id


def test_the_name_in_the_sidebar_opens_ones_own_password(qtbot, monkeypatch, conn,
                                                         receptionist):
    from tadris.ui import main_window

    opened = []
    monkeypatch.setattr(main_window, "ask", lambda dialog: opened.append(dialog) or False)
    window = MainWindow(conn, receptionist)
    qtbot.addWidget(window)
    click(qtbot, window.account_button)
    assert isinstance(opened[0], PasswordDialog)
    assert opened[0].current is not None
    assert opened[0].windowTitle() == t["password_dialog.own"]


# ----- the recovery code -----

def test_forgot_password_on_the_login_screen_logs_the_director_in(qtbot, monkeypatch, conn,
                                                                  director):
    from tadris.ui import login_dialog

    code = auth.new_recovery_code(conn, director)
    told = []
    monkeypatch.setattr(login_dialog.QMessageBox, "information",
                        lambda parent, title, text: told.append(title))

    def fill_and_send(dialog):
        assert dialog.username.text() == "directeur"  # taken from the login form
        dialog.code.setText(code.lower())
        dialog.password.setText("nouveau-pass")
        dialog.password_confirm.setText("nouveau-pass")
        click(qtbot, dialog.submit)
        return dialog.result() == dialog.DialogCode.Accepted

    monkeypatch.setattr(login_dialog, "ask", fill_and_send)
    login = LoginDialog(conn)
    qtbot.addWidget(login)
    login.username.setText("directeur")
    assert login.forgot.text() == t["login.forgot"]
    click(qtbot, login.forgot)
    assert login.ctx.user_id == director.user_id
    assert told == [t["recovery.done_title"]]
    assert auth.login(conn, "directeur", "nouveau-pass").role == "director"


def test_a_wrong_recovery_code_says_so(qtbot, conn, director):
    from tadris.ui.user_dialog import RecoveryDialog

    auth.new_recovery_code(conn, director)
    dialog = RecoveryDialog(conn, "directeur")
    qtbot.addWidget(dialog)
    dialog.code.setText("AAAA-AAAA-AAAA-AAAA")
    dialog.password.setText("nouveau-pass")
    dialog.password_confirm.setText("nouveau-pass")
    click(qtbot, dialog.submit)
    assert dialog.banner.text() == t["auth.recovery_invalid"]
    assert dialog.ctx is None


def test_the_users_section_makes_and_replaces_the_code(qtbot, monkeypatch, conn, director):
    from tadris.ui import user_dialog
    from tadris.ui.pages.settings import users as users_page

    shown = []
    monkeypatch.setattr(user_dialog, "ask", lambda dialog: shown.append(dialog.code.text()))
    asked = []
    monkeypatch.setattr(users_page, "confirm", lambda *args: asked.append(args[1]) or True)
    section = users_section(qtbot, conn, director)
    assert section.recovery_text.text() == t["users.recovery_none"]
    assert not section.recovery_todo.isHidden()
    click(qtbot, section.recovery)
    assert len(shown) == 1 and asked == []  # nothing to replace yet
    assert section.recovery_text.text().startswith("Code créé le ")
    assert section.recovery_todo.isHidden()
    assert section.recovery.text() == t["users.recovery_again"]
    click(qtbot, section.recovery)
    assert asked == [t["users.recovery_replace_title"]] and shown[0] != shown[1]
    auth.recover(conn, "directeur", shown[1], "nouveau-pass")  # the last one works


def test_the_recovery_code_window_shows_the_code(qtbot):
    from tadris.ui.user_dialog import RecoveryCodeDialog

    dialog = RecoveryCodeDialog("K7QM-4XRP-9TBW-2HDN")
    qtbot.addWidget(dialog)
    assert dialog.code.text() == "K7QM-4XRP-9TBW-2HDN"
    assert dialog.done.text() == t["recovery_code.done"]
