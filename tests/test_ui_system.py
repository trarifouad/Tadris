"""Paramètres → Données, about the app itself: « Sauvegardes » and « À propos »."""

from pathlib import Path

import pytest

from tadris import __version__
from tadris.db.connection import connect
from tadris.db.migrate import latest_version, migrate
from tadris.i18n.fr import t
from tadris.services import auth, backup
from tadris.ui.main_window import MainWindow
from tadris.ui.pages import system_tabs
from tadris.ui.pages.settings import SettingsPage
from tadris.ui.pages.system_tabs import AboutTab, BackupsTab
from tadris.ui.theme import apply_theme, load_fonts
from tadris.ui.widgets.forms import SectionWindow


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


def test_about_is_in_the_data_section(qtbot, school):
    conn, director = school
    page = SettingsPage(conn, director)
    qtbot.addWidget(page)
    page.show_tab("about")
    assert page.current_section() == "data"
    assert isinstance(page.sections["data"].about, AboutTab)
    assert page.sections["data"].about.app_version.text() == __version__


def test_the_data_card_sums_up_the_backups_and_takes_one(qtbot, school, tmp_path):
    conn, director = school
    page = SettingsPage(conn, director)
    qtbot.addWidget(page)
    data = page.sections["data"]
    assert data.last.text() == t["data.none"] and data.last_state.isHidden()
    assert data.second.text() == t["data.no_second"]
    data.take.click()  # « Sauvegarder maintenant », from the card
    [taken] = backup.list_backups(conn)
    assert data.last.text() == t["data.last"].format(
        when=system_tabs.display_stamp(taken.created_at))
    assert data.last_state.text() == t["backups.status.verified"] and data.error.isHidden()
    assert Path(taken.file_path).parent == tmp_path / "backups"


# ----- sauvegardes -----

@pytest.fixture
def answers(monkeypatch):
    """What the dialogs answer: confirm (True), the folder and the file chosen."""
    given = {"confirm": True, "folder": None, "file": None, "asked": []}

    def confirm(parent, title, text, action):
        given["asked"].append(text)
        return given["confirm"]

    monkeypatch.setattr(system_tabs, "confirm", confirm)
    monkeypatch.setattr(system_tabs.common, "ask_folder",
                        lambda parent, title, start: given["folder"])
    monkeypatch.setattr(system_tabs.common, "ask_open_path",
                        lambda parent, title, start, file_filter: given["file"])
    return given


def make_backups(qtbot, conn, ctx) -> BackupsTab:
    tab = BackupsTab(conn, ctx)
    qtbot.addWidget(tab)
    return tab


def students(conn) -> list[str]:
    return [row[0] for row in conn.execute("SELECT last_name FROM students ORDER BY id")]


def add_student(conn, name: str) -> None:
    n = conn.execute("SELECT COUNT(*) + 1 FROM students").fetchone()[0]
    conn.execute("INSERT INTO students(student_number, first_name, last_name) "
                 "VALUES (?, 'Prénom', ?)", (f"2026-{n:04d}", name))


def select(tab, backup_id) -> None:
    tab.list.select_id(backup_id)
    assert tab.selected().id == backup_id


def test_the_copies_are_listed_latest_first(qtbot, school, tmp_path):
    conn, director = school
    first = backup.take(conn, tmp_path / "backups")
    second = backup.take(conn, tmp_path / "backups", "manual")
    tab = make_backups(qtbot, conn, director)
    assert tab.where.text() == f"Dossier des sauvegardes : {tmp_path / 'backups'}"
    assert tab.list.ids() == [second.id, first.id]
    table = tab.list.table
    assert [table.item(r, 1).text() for r in range(2)] == ["Manuelle", "Automatique"]
    assert table.item(0, 3).text() == "Vérifiée"
    assert table.item(0, 2).text().endswith(" Mo")
    assert not tab.restore_selected.isEnabled()  # nothing selected
    select(tab, first.id)
    assert tab.restore_selected.isEnabled()


def test_a_failed_copy_cannot_be_restored(qtbot, school, tmp_path):
    conn, director = school
    taken = backup.take(conn, tmp_path / "backups")
    Path(taken.file_path).unlink()
    backup.verify(conn, taken.id)
    tab = make_backups(qtbot, conn, director)
    select(tab, taken.id)
    assert tab.list.table.item(0, 3).text() == "Échouée"
    assert not tab.restore_selected.isEnabled()


def test_save_now_makes_a_manual_copy(qtbot, school, tmp_path):
    conn, director = school
    tab = make_backups(qtbot, conn, director)
    assert tab.list.ids() == []
    tab.take_now.click()
    [made] = backup.list_backups(conn)
    assert made.type == "manual" and made.status == "verified"
    assert tab.selected().id == made.id
    assert conn.execute("SELECT user_id FROM audit_log WHERE action = 'backup.manual'"
                        ).fetchone()[0] == director.user_id


def test_choose_and_remove_the_second_location(qtbot, school, tmp_path, answers):
    conn, director = school
    usb = tmp_path / "usb"
    usb.mkdir()
    tab = make_backups(qtbot, conn, director)
    assert tab.second.text().startswith("Aucun")
    assert tab.remove_second.isHidden()

    answers["folder"] = usb
    tab.choose_second.click()
    assert backup.second_root(conn) == usb
    assert str(usb / f"Tadris-{backup.school_id(conn)}") in tab.second.text()
    assert not tab.remove_second.isHidden()
    tab.take_now.click()
    assert len(list(backup.second_folder(conn).glob("*.db"))) == 1

    answers["confirm"] = False
    tab.remove_second.click()
    assert backup.second_root(conn) == usb  # cancelled
    answers["confirm"] = True
    tab.remove_second.click()
    assert backup.second_root(conn) is None
    assert tab.second.text().startswith("Aucun")


def test_a_second_location_unplugged_warns_on_save_now(qtbot, school, tmp_path, answers):
    conn, director = school
    usb = tmp_path / "usb"
    usb.mkdir()
    answers["folder"] = usb
    tab = make_backups(qtbot, conn, director)
    tab.choose_second.click()
    usb.rmdir()
    tab.take_now.click()
    assert not tab.error.isHidden()
    assert "introuvable" in tab.error.text()
    [made] = backup.list_backups(conn)
    assert made.status == "verified" and tab.selected().id == made.id


def test_restore_a_copy_after_confirming(qtbot, school, tmp_path, answers):
    conn, director = school
    taken = backup.take(conn, tmp_path / "backups")
    add_student(conn, "Ajouté")
    tab = make_backups(qtbot, conn, director)
    select(tab, taken.id)

    answers["confirm"] = False
    tab.restore_selected.click()
    assert students(conn) == ["Ajouté"]  # cancelled: nothing replaced
    assert "École Ennour" in answers["asked"][0] and "Élèves : 0" in answers["asked"][0]

    answers["confirm"] = True
    with qtbot.waitSignal(tab.restored) as signal:
        tab.restore_selected.click()
    assert students(conn) == []
    assert signal.args[0].endswith("-avant-restauration.db")
    assert Path(signal.args[0]).is_file()


def test_restore_from_a_file_that_is_not_a_copy(qtbot, school, tmp_path, answers):
    conn, director = school
    junk = tmp_path / "photo.db"
    junk.write_bytes(b"\x89PNG" * 400)
    answers["file"] = junk
    tab = make_backups(qtbot, conn, director)
    tab.restore_file.click()
    assert "n'est pas une sauvegarde" in tab.error.text()
    assert answers["asked"] == []  # refused before asking


def test_restore_from_a_file(qtbot, school, tmp_path, answers):
    conn, director = school
    add_student(conn, "Gardé")
    taken = backup.take(conn, tmp_path / "backups")
    copied = tmp_path / "usb-copie.db"
    copied.write_bytes(Path(taken.file_path).read_bytes())
    conn.execute("DELETE FROM students")
    answers["file"] = copied
    tab = make_backups(qtbot, conn, director)
    with qtbot.waitSignal(tab.restored):
        tab.restore_file.click()
    assert students(conn) == ["Gardé"]
    assert "usb-copie.db" in answers["asked"][0]


def test_an_in_memory_database_has_no_backups(qtbot, conn):
    director = auth.bootstrap_director(conn, "directeur", "password1", "École Ennour")
    tab = make_backups(qtbot, conn, director)
    assert tab.where.text() == t["backups.in_memory"]
    assert not tab.take_now.isEnabled() and not tab.restore_file.isEnabled()


def test_after_a_restore_the_window_goes_back_to_the_login(qtbot, school, tmp_path, answers,
                                                           monkeypatch):
    conn, director = school
    shown = []
    monkeypatch.setattr("tadris.ui.main_window.QMessageBox.information",
                        lambda parent, title, text: shown.append(text))
    taken = backup.take(conn, tmp_path / "backups")
    window = MainWindow(conn, director)
    qtbot.addWidget(window)
    window.show()
    window.nav_buttons["settings"].click()
    page = window.findChild(SettingsPage)
    page.show_tab("backups")

    def restore_in_the_window(backups_window):
        """« Gérer les sauvegardes »: the copy restored from the window, which closes."""
        tab = backups_window.section
        select(tab, taken.id)
        tab.restore_selected.click()
        return backups_window.result()
    monkeypatch.setattr(SectionWindow, "exec", restore_in_the_window)
    with qtbot.waitSignal(window.logged_out):
        page.sections["data"].manage.click()
    assert window.restored and window.logging_out
    assert "avant-restauration" in shown[0] and "Reconnectez-vous" in shown[0]
