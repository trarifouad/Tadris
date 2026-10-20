from typing import ClassVar

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog

from tadris import app
from tadris.services import auth
from tadris.ui import main_window
from tadris.ui.main_window import MainWindow
from tadris.ui.theme import apply_theme, load_fonts


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


def logouts(conn) -> list:
    return conn.execute("SELECT user_id, entity_id FROM audit_log WHERE action = 'user.logout'"
                        ).fetchall()


def test_the_button_sits_under_the_user(qtbot, conn, receptionist):
    window = MainWindow(conn, receptionist)
    qtbot.addWidget(window)
    assert window.logout_button.text() == "Se déconnecter"
    assert window.logout_button.parent().objectName() == "sidebarFooter"


def test_logout_closes_the_window_and_is_audited(qtbot, conn, receptionist):
    window = MainWindow(conn, receptionist)
    qtbot.addWidget(window)
    window.show()
    with qtbot.waitSignal(window.logged_out):
        qtbot.mouseClick(window.logout_button, Qt.MouseButton.LeftButton)
    assert window.logging_out and not window.isVisible()
    assert [tuple(row) for row in logouts(conn)] == [(receptionist.user_id,
                                                      receptionist.user_id)]


def test_unsaved_attendance_asks_first(qtbot, conn, director, monkeypatch):
    window = MainWindow(conn, director)
    qtbot.addWidget(window)
    window.show()
    monkeypatch.setattr(window, "has_unsaved", lambda: True)
    asked = []
    monkeypatch.setattr(main_window, "confirm",
                        lambda parent, title, text, action: asked.append(action) or False)
    assert window.logout() is False
    assert window.isVisible() and not window.logging_out and logouts(conn) == []

    monkeypatch.setattr(main_window, "confirm", lambda *args: True)
    assert window.logout() is True
    assert asked == ["Se déconnecter"] and len(logouts(conn)) == 1


def test_nothing_unsaved_by_default(qtbot, conn, director):
    window = MainWindow(conn, director)
    qtbot.addWidget(window)
    for key in ("attendance", "students", "payments"):
        window.nav_buttons[key].click()
    assert window.has_unsaved() is False
    attendance = window.pages.widget(window._slots["attendance"])
    assert attendance.has_unsaved() is False


# ----- the app's loop: login, work, logout, login again -----

class FakeLogin:
    """Accepts as each user of `queue` in turn; rejects once it is empty."""

    queue: ClassVar[list] = []

    def __init__(self, conn, parent=None):
        self.ctx = None

    def exec(self):
        if not FakeLogin.queue:
            return QDialog.DialogCode.Rejected
        self.ctx = FakeLogin.queue.pop(0)
        return QDialog.DialogCode.Accepted


class FakeApp:
    """app.exec(): what the user does in the window just shown, then the loop returns."""

    def __init__(self, actions):
        self.actions = actions
        self.windows = []

    def exec(self):
        window = self.windows[-1]
        self.actions.pop(0)(window)
        return 0


@pytest.fixture
def loop(monkeypatch, qtbot):
    def run(conn, users, actions):
        FakeLogin.queue = list(users)
        fake = FakeApp(actions)

        class Window(MainWindow):
            def __init__(self, conn, ctx):
                super().__init__(conn, ctx)
                fake.windows.append(self)

        monkeypatch.setattr(app, "LoginDialog", FakeLogin)
        monkeypatch.setattr(app, "MainWindow", Window)
        code = app.run_sessions(fake, conn, None, None)
        return code, fake.windows
    return run


def test_logout_brings_the_login_back(conn, director, receptionist, loop):
    code, windows = loop(conn, [receptionist, director],
                         [lambda w: w.logout(), lambda w: w.close()])
    assert code == 0
    assert [w.ctx.username for w in windows] == ["accueil", "directeur"]
    assert len(logouts(conn)) == 1


def test_closing_the_login_after_a_logout_quits(conn, receptionist, loop):
    code, windows = loop(conn, [receptionist], [lambda w: w.logout()])
    assert code == 0 and len(windows) == 1  # someone worked: the close backup runs


def test_nobody_logged_in(conn, director, loop):
    code, windows = loop(conn, [], [])
    assert code is None and windows == []

