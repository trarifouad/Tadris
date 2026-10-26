import json
import sqlite3
from datetime import date

import pytest
from PySide6.QtCore import Qt

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import PermissionDenied, ValidationError
from tadris.i18n.fr import t
from tadris.services import auth, holidays


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(dates, "today", lambda: date(2026, 10, 18))


@pytest.fixture
def director(conn):
    return auth.bootstrap_director(conn, "directeur", "password1", "École Ennour")


@pytest.fixture
def receptionist(conn, director):
    user_id = auth.create_user(conn, director, "accueil", "password2", "receptionist")
    return UserContext(user_id=user_id, username="accueil", role="receptionist")


def last_audit(conn, action):
    return conn.execute("SELECT * FROM audit_log WHERE action = ? ORDER BY id DESC",
                        (action,)).fetchone()


# ----- service -----

def test_a_period_and_a_single_day(conn, director):
    winter = holidays.create(conn, director, " Vacances d'hiver ", date(2026, 12, 20),
                             date(2027, 1, 3))
    november = holidays.create(conn, director, "1er Novembre", date(2026, 11, 1))
    listed = holidays.list_holidays(conn, director)
    assert [(h.id, h.label, h.start_date, h.end_date, h.days) for h in listed] == [
        (winter, "Vacances d'hiver", "2026-12-20", "2027-01-03", 15),
        (november, "1er Novembre", "2026-11-01", "2026-11-01", 1),
    ]
    entry = json.loads(last_audit(conn, "holiday.create")["new_value"])
    assert entry["label"] == "1er Novembre"


def test_validation(conn, director):
    with pytest.raises(ValidationError) as exc:
        holidays.create(conn, director, "  ", date(2026, 11, 1))
    assert exc.value.message == t["holiday.label_required"]
    with pytest.raises(ValidationError) as exc:
        holidays.create(conn, director, "x", date(2026, 11, 5), date(2026, 11, 4))
    assert exc.value.message == t["holiday.dates_order"]


def test_periods_never_overlap(conn, director):
    holidays.create(conn, director, "Vacances d'hiver", date(2026, 12, 20), date(2027, 1, 3))
    with pytest.raises(ValidationError) as exc:
        holidays.create(conn, director, "Nouvel an", date(2027, 1, 1))
    assert exc.value.message == t["holiday.overlap"].format(
        label="Vacances d'hiver", start="20/12/2026", end="03/01/2027")
    holidays.create(conn, director, "Rentrée", date(2027, 1, 4))  # the next day is free


def test_database_refuses_an_overlap(conn, director):
    holidays.create(conn, director, "Vacances", date(2026, 12, 20), date(2027, 1, 3))
    with pytest.raises(sqlite3.IntegrityError, match="holiday overlap"):
        conn.execute("INSERT INTO holidays(label, start_date, end_date) "
                     "VALUES ('x', '2027-01-03', '2027-01-05')")


def test_update_and_remove_are_audited(conn, director):
    holiday_id = holidays.create(conn, director, "Vacances", date(2026, 12, 20),
                                 date(2027, 1, 3))
    holidays.update(conn, director, holiday_id, "Vacances d'hiver", date(2026, 12, 21),
                    date(2027, 1, 3))
    entry = last_audit(conn, "holiday.update")
    assert json.loads(entry["old_value"])["start_date"] == "2026-12-20"
    holidays.update(conn, director, holiday_id, "Vacances d'hiver", date(2026, 12, 21),
                    date(2027, 1, 3))  # no change: no second entry
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'holiday.update'"
                        ).fetchone()[0] == 1
    holidays.remove(conn, director, holiday_id)
    assert holidays.list_holidays(conn, director) == []
    assert json.loads(last_audit(conn, "holiday.remove")["old_value"])["label"] == \
        "Vacances d'hiver"


def test_an_update_may_not_overlap_another(conn, director):
    holidays.create(conn, director, "Hiver", date(2026, 12, 20), date(2027, 1, 3))
    spring = holidays.create(conn, director, "Printemps", date(2027, 3, 20), date(2027, 4, 4))
    with pytest.raises(ValidationError, match="Hiver"):
        holidays.update(conn, director, spring, "Printemps", date(2027, 1, 2), date(2027, 4, 4))
    holidays.update(conn, director, spring, "Printemps", date(2027, 3, 21), date(2027, 4, 4))


def test_director_only_to_manage_both_can_read(conn, director, receptionist):
    with pytest.raises(PermissionDenied):
        holidays.create(conn, receptionist, "x", date(2026, 11, 1))
    holidays.create(conn, director, "1er Novembre", date(2026, 11, 1))
    assert len(holidays.list_holidays(conn, receptionist)) == 1


def test_days_off_between_two_dates(conn, director):
    holidays.create(conn, director, "1er Novembre", date(2026, 11, 1))
    holidays.create(conn, director, "Hiver", date(2026, 12, 20), date(2027, 1, 3))
    off = holidays.days_off(conn, date(2026, 10, 25), date(2026, 12, 22))
    assert off == {"2026-11-01": "1er Novembre", "2026-12-20": "Hiver",
                   "2026-12-21": "Hiver", "2026-12-22": "Hiver"}


# ----- Paramètres, Vacances tab -----

@pytest.fixture
def themed(qapp):
    from tadris.ui.theme import apply_theme, load_fonts

    load_fonts()
    apply_theme(qapp)


def test_vacances_from_the_structure(qtbot, themed, conn, director, monkeypatch):
    """Paramètres → Structure, « Gérer les vacances »: the whole list in a window, where
    periods are added and removed; closed, the year's card says what is coming."""
    from tadris.ui.pages import setup_tabs
    from tadris.ui.pages.settings import SettingsPage
    from tadris.ui.setup_dialogs import HolidayDialog
    from tadris.ui.widgets.forms import SectionWindow

    def fill(dialog):
        dialog.label.setText("Vacances d'hiver")
        dialog.start.setText("20/12/2026")
        dialog.end.setText("03/01/2027")
        dialog._submit()
    monkeypatch.setattr(HolidayDialog, "exec", lambda self: (fill(self), self.result())[1])
    monkeypatch.setattr(setup_tabs, "confirm", lambda *_args: True)
    seen = []

    def use(window):
        tab = window.section
        assert window.windowTitle() == t["structure.window.holidays"]
        assert not tab.list.empty.isHidden()
        qtbot.mouseClick(tab.new, Qt.MouseButton.LeftButton)
        table = tab.list.table
        seen.append([table.item(0, c).text() for c in range(4)])
        return 0
    monkeypatch.setattr(SectionWindow, "exec", use)
    page = SettingsPage(conn, director)
    qtbot.addWidget(page)
    page.show_tab("holidays")
    structure = page.sections["structure"]
    assert structure.holidays_text.text() == t["structure.no_holidays"]
    qtbot.mouseClick(structure.manage_holidays, Qt.MouseButton.LeftButton)
    assert seen == [["Vacances d'hiver", "20/12/2026", "03/01/2027", "15"]]
    assert structure.holidays_text.text() == t["structure.holidays"].format(
        count=1, label="Vacances d'hiver", period="du 20/12/2026 au 03/01/2027")

    def remove(window):
        tab = window.section
        tab.list.table.selectRow(0)
        qtbot.mouseClick(tab.remove, Qt.MouseButton.LeftButton)
        seen.append(tab.list.table.rowCount())
        return 0
    monkeypatch.setattr(SectionWindow, "exec", remove)
    qtbot.mouseClick(structure.manage_holidays, Qt.MouseButton.LeftButton)
    assert seen[-1] == 0
    assert structure.holidays_text.text() == t["structure.no_holidays"]


def test_single_day_dialog(qtbot, themed, conn, director):
    from tadris.ui.setup_dialogs import HolidayDialog

    dialog = HolidayDialog(conn, director)
    qtbot.addWidget(dialog)
    dialog.label.setText("1er Novembre")
    dialog.start.setText("01/11/2026")
    dialog._submit()
    assert dialog.result()
    [holiday] = holidays.list_holidays(conn, director)
    assert holiday.start_date == holiday.end_date == "2026-11-01"
