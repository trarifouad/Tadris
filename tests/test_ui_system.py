"""Paramètres tabs about the app itself: « À propos » and « Sauvegardes »."""

import pytest

from tadris import __version__
from tadris.db.connection import connect
from tadris.db.migrate import latest_version, migrate
from tadris.i18n.fr import t
from tadris.services import auth
from tadris.ui.pages import system_tabs
from tadris.ui.pages.settings import SettingsPage
from tadris.ui.pages.system_tabs import AboutTab
from tadris.ui.theme import apply_theme, load_fonts


@pytest.fixture(autouse=True)
def theme(qapp):
    load_fonts()
    apply_theme(qapp)


@pytest.fixture
def school(tmp_path):
    """A database on disk with a director."""
    auth._reset_failures()
    c = connect(tmp_path / "tadris.db")
    migrate(c)
    director = auth.bootstrap_director(c, "directeur", "password1", "École Ennour")
    yield c, director
    c.close()


@pytest.fixture
def opened(monkeypatch):
    folders = []
    monkeypatch.setattr(system_tabs.common, "open_folder", folders.append)
    return folders


# ----- à propos -----

def test_about_shows_the_versions_and_the_database_file(qtbot, school, tmp_path, opened):
    conn, director = school
    tab = AboutTab(conn, director)
    qtbot.addWidget(tab)
    assert tab.app_version.text() == __version__
    assert tab.schema_version.text() == str(latest_version())
    assert tab.database.text() == str(tmp_path / "tadris.db")
    tab.open_folder.click()
    assert opened == [tmp_path]


def test_about_an_in_memory_database(qtbot, conn, opened):
    director = auth.bootstrap_director(conn, "directeur", "password1", "École Ennour")
    tab = AboutTab(conn, director)
    qtbot.addWidget(tab)
    assert tab.database.text() == t["about.in_memory"]
    assert not tab.open_folder.isEnabled()


def test_about_is_the_last_settings_tab(qtbot, school):
    conn, director = school
    page = SettingsPage(conn, director)
    qtbot.addWidget(page)
    last = page.tabs.count() - 1
    assert page.tabs.tabText(last) == "À propos"
    assert page.tabs.widget(last) is page.about
