import logging
import sys

import pytest
from PySide6.QtCore import QTimer

from tadris import app
from tadris.i18n.fr import t


@pytest.fixture
def env(monkeypatch):
    # _choose_scale writes os.environ itself: set first, so monkeypatch restores the value
    # (or its absence) after the test and no later Qt test runs scaled.
    for key in ("QT_SCALE_FACTOR", app.SCALE_ENV):
        monkeypatch.setenv(key, "")
        monkeypatch.delenv(key)

    def run(platform: str, **values) -> str | None:
        monkeypatch.setattr(app.sys, "platform", platform)
        for key, value in values.items():
            monkeypatch.setenv(key, value)
        app._choose_scale()
        return app.os.environ.get("QT_SCALE_FACTOR")
    return run


def test_linux_opens_at_125_percent(env):
    assert env("linux") == "1.25"


def test_windows_follows_its_own_scale(env):
    assert env("win32") is None


def test_tadris_scale_wins_everywhere(env):
    assert env("win32", TADRIS_SCALE="1,5") == "1.5"


def test_tadris_scale_100_percent_on_linux(env):
    assert env("linux", TADRIS_SCALE="1") == "1.0"


def test_a_qt_scale_already_set_is_kept(env):
    assert env("linux", QT_SCALE_FACTOR="2") == "2"


@pytest.mark.parametrize("value", ["abc", "0.1", "9"])
def test_a_bad_tadris_scale_is_ignored(env, caplog, value):
    assert env("linux", TADRIS_SCALE=value) == "1.25"
    assert "TADRIS_SCALE" in caplog.text


# ----- the log: errors nobody caught -----

@pytest.fixture
def logged(tmp_path, monkeypatch):
    """The app's log in a temporary folder, the messages collected; the hook and the
    handlers are put back after."""
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(app, "_said", set())
    shown = []
    monkeypatch.setattr(app.QMessageBox, "critical",
                        lambda parent, title, text: shown.append((title, text)))
    path = app.start_log(tmp_path)
    yield path, shown
    for handler in list(app.log.handlers):
        app.log.removeHandler(handler)
        handler.close()


def raised(error: Exception):
    try:
        raise error
    except Exception as exc:  # noqa: BLE001 - any error, as the hook receives it
        return type(exc), exc, exc.__traceback__


def test_an_error_nobody_caught_is_logged_and_said_once(qapp, logged):
    path, shown = logged
    for _ in range(3):  # the same place again, e.g. at every repaint
        sys.excepthook(*raised(ValueError("boom")))
    text = path.read_text(encoding="utf-8")
    assert text.count("Erreur inattendue") == 3 and "ValueError: boom" in text
    assert shown == [(t["crash.title"], t["crash.text"].format(path=path))]


def test_an_error_in_a_qt_slot_reaches_the_log(qtbot, logged):
    path, shown = logged

    def boom():
        raise RuntimeError("dans un slot")

    QTimer.singleShot(0, boom)
    qtbot.waitUntil(lambda: bool(shown))
    assert "RuntimeError: dans un slot" in path.read_text(encoding="utf-8")


def test_starting_the_log_again_keeps_one_file(tmp_path, logged):
    app.start_log(tmp_path)
    files = [h for h in app.log.handlers if isinstance(h, logging.FileHandler)]
    assert len(files) == 1


# ----- one Tadris at a time on a database -----

def test_a_second_tadris_on_the_same_database_is_refused(tmp_path):
    first = app.lock_database(tmp_path / "tadris.db")
    assert first is not None and (tmp_path / "tadris.lock").exists()
    assert app.lock_database(tmp_path / "tadris.db") is None
    first.unlock()  # the first one closed
    again = app.lock_database(tmp_path / "tadris.db")
    assert again is not None
    again.unlock()


def test_another_database_has_its_own_lock(tmp_path):
    school = app.lock_database(tmp_path / "tadris.db")
    copy = app.lock_database(tmp_path / "demo.db")  # a TADRIS_DB test copy
    assert school is not None and copy is not None
    school.unlock()
    copy.unlock()
