"""The director's Journal: the audit log in plain French, a page at a time."""

import json
from datetime import date, timedelta

import pytest
from PySide6.QtCore import Qt

from tadris.core import dates
from tadris.core.errors import PermissionDenied, ValidationError
from tadris.i18n.fr import t
from tadris.services import auth, journal

DAY = date(2026, 10, 20)


@pytest.fixture
def director(conn):
    return auth.bootstrap_director(conn, "directeur", "password1", "École Ennour")


@pytest.fixture
def desk(conn, director):
    auth.create_user(conn, director, "accueil", "password2", "receptionist")
    return auth.login(conn, "accueil", "password2")


def write(conn, user_id, action, when, entity="payments", entity_id=None, new=None):
    conn.execute(
        "INSERT INTO audit_log(user_id, action, entity_name, entity_id, new_value, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, action, entity, entity_id, None if new is None else json.dumps(new), when))


# ----- in plain French -----

def test_journal_values():
    names = journal.Names({"students": {7: "Benali Amine"}, "class_groups": {3: "Maths 4AM"}})
    assert journal.action_label("payment.record") == "Paiement enregistré"
    assert journal.action_label("user.disable") == "Utilisateur désactivé"
    assert journal.action_label("whatsapp_group.link") == "Groupe WhatsApp lié"
    assert journal.action_label("phase11.sms") == "phase11.sms"  # unknown: as recorded
    assert journal.entity_label("students", 7, names) == "Élève : Benali Amine"
    assert journal.entity_label("payments", 12, names) == "Paiement n° 12"
    assert journal.entity_label("app", None, names) == "Application"
    new = json.dumps({"student_id": 7, "group_id": 3, "price": 3000, "percentage_bp": 6250,
                      "weekday": 2, "method": "cheque", "is_main": True, "charge_id": 99,
                      "start_date": "2026-09-15", "notes": None, "mystery": "x"})
    assert journal.lines(None, new, names) == [
        "Élève : Benali Amine", "Groupe : Maths 4AM", "Prix : 3 000 DA", "Taux : 62,5 %",
        "Jour : Mardi", "Mode : Chèque", "Contact principal : Oui",
        "Début : 15/09/2026", "mystery : x"]
    marks = json.dumps({"date": "2026-10-18", "changes": [
        {"enrollment_id": 1, "old": None, "new": "present"},
        {"enrollment_id": 2, "old": None, "new": "present"},
        {"enrollment_id": 3, "old": "present", "new": "absent"}]})
    assert journal.lines(None, marks, names) == ["Date : 18/10/2026",
                                                 "Marques : 2 Présent, 1 Absent"]
    assert journal.lines('{"key": "school.name", "value": "A"}',
                         '{"key": "school.name", "value": "B"}', names) == [
        "Paramètre : Nom de l'école", "Valeur : A → B"]
    assert journal.lines('{"status": "active"}', '{"status": "disabled"}', names) == [
        "Statut : Actif → Désactivé"]
    assert journal.lines(None, '{"whatsapp_code": "AbC123"}', names) == []
    assert journal.lines(None, '{"now": "2001-01-01T08:00:00", "last": '
                         '"2026-10-30T18:00:00"}', names) == [
        "Date de l'ordinateur : 01/01/2001", "Dernière opération : 30/10/2026"]
    assert len(journal.summary(None, json.dumps({"reason": "x" * 300}), names, 50)) == 50


# ----- the entries -----

def test_entries_latest_first_in_french(conn, director, desk):
    write(conn, desk.user_id, "payment.record", "2026-10-20T09:00:00", entity_id=12,
          new={"amount": 3000, "method": "cash"})
    write(conn, director.user_id, "user.disable", "2026-10-20T10:00:00", entity="users",
          entity_id=desk.user_id, new={"status": "disabled"})
    entries = journal.entries(conn, director, DAY, DAY)
    assert [(e.created_at, e.user, e.action, e.item, e.detail) for e in entries] == [
        ("2026-10-20T10:00:00", "directeur", "Utilisateur désactivé",
         "Utilisateur : accueil", "Statut : Désactivé"),
        ("2026-10-20T09:00:00", "accueil", "Paiement enregistré", "Paiement n° 12",
         "Montant : 3 000 DA · Mode : Espèces"),
    ]
    assert journal.count(conn, director, DAY, DAY) == 2


def test_the_dates_and_the_user_filter(conn, director, desk):
    write(conn, desk.user_id, "payment.record", "2026-10-19T23:59:59")
    write(conn, desk.user_id, "payment.record", "2026-10-20T08:00:00")
    write(conn, director.user_id, "payment.void", "2026-10-20T08:30:00")
    write(conn, desk.user_id, "payment.record", "2026-10-21T00:00:00")
    assert journal.count(conn, director, DAY, DAY) == 2  # the whole day, nothing else
    assert journal.count(conn, director, DAY - timedelta(days=1), DAY + timedelta(days=1)) == 4
    only_desk = journal.entries(conn, director, DAY, DAY, user_id=desk.user_id)
    assert [e.created_at for e in only_desk] == ["2026-10-20T08:00:00"]


def test_what_the_app_did_by_itself_is_left_out_but_what_the_director_must_know(
        conn, director):
    for action in ("backup.create", "session.generate", "subscription.mark_ended",
                   "backup.failed", "backup.mirror_failed", "clock.behind"):
        write(conn, None, action, "2026-10-20T07:00:00", entity="app")
    shown = journal.entries(conn, director, DAY, DAY)
    assert {e.action for e in shown} == {
        "Sauvegarde échouée", "Copie au second emplacement échouée",
        "Date de l'ordinateur antérieure acceptée"}
    assert {e.user for e in shown} == {t["audit.system"]}


def test_a_page_at_a_time_older_than_the_last_shown(conn, director):
    for minute in range(5):
        write(conn, director.user_id, "payment.record", f"2026-10-20T08:0{minute}:00")
    first = journal.entries(conn, director, DAY, DAY, limit=2)
    second = journal.entries(conn, director, DAY, DAY, before_id=first[-1].id, limit=2)
    third = journal.entries(conn, director, DAY, DAY, before_id=second[-1].id, limit=2)
    assert [e.created_at[11:16] for e in first + second + third] == [
        "08:04", "08:03", "08:02", "08:01", "08:00"]


def test_the_journal_is_the_directors(conn, desk):
    for read in (lambda: journal.entries(conn, desk, DAY, DAY),
                 lambda: journal.count(conn, desk, DAY, DAY),
                 lambda: journal.users(conn, desk)):
        with pytest.raises(PermissionDenied):
            read()


def test_an_end_before_the_start_is_refused(conn, director):
    with pytest.raises(ValidationError) as exc:
        journal.entries(conn, director, DAY, DAY - timedelta(days=1))
    assert exc.value.message == t["journal.range_invalid"]


def test_users_for_the_filter_include_disabled_accounts(conn, director, desk):
    auth.disable_user(conn, director, desk.user_id)
    assert journal.users(conn, director) == [(desk.user_id, "accueil"),
                                             (director.user_id, "directeur")]


# ----- the window -----

@pytest.fixture
def view(qtbot, conn, director, desk, monkeypatch):
    from tadris.ui.pages.settings.journal import JournalView

    monkeypatch.setattr(dates, "today", lambda: DAY)

    def make():
        widget = JournalView(conn, director)
        qtbot.addWidget(widget)
        widget.resize(1000, 500)
        widget.show()
        return widget
    return make


def rows(table) -> list[list[str]]:
    return [[table.item(r, c).text() for c in range(table.columnCount())]
            for r in range(table.rowCount())]


def test_the_window_opens_on_the_last_week(conn, director, desk, view):
    write(conn, desk.user_id, "payment.record", "2026-10-12T09:00:00")  # 8 days before
    write(conn, desk.user_id, "payment.record", "2026-10-13T09:00:00", entity_id=4,
          new={"amount": 1500})
    widget = view()
    assert widget.first.value() == date(2026, 10, 13) and widget.last.value() == DAY
    assert rows(widget.table) == [["13/10/2026 09:00", "accueil", "Paiement enregistré",
                                   "Paiement n° 4", "Montant : 1 500 DA"]]
    assert widget.count.text() == "1 opération(s)"
    assert widget.empty.isHidden()


def test_the_user_filter_and_the_empty_state(conn, director, desk, view):
    write(conn, director.user_id, "payment.void", "2026-10-20T09:00:00")
    widget = view()
    widget.user.setCurrentIndex(widget.user.findData(desk.user_id))
    assert widget.table.isHidden() and widget.empty.isVisible()
    widget.user.setCurrentIndex(widget.user.findData(None))
    assert widget.table.rowCount() == 1


def test_a_wrong_range_says_so(conn, director, view):
    widget = view()
    widget.first.set_value(DAY + timedelta(days=1))
    assert widget.banner.text() == t["journal.range_invalid"]


def test_the_next_page_comes_as_the_list_is_scrolled(qtbot, conn, director, view,
                                                     monkeypatch):
    monkeypatch.setattr(journal, "PAGE", 20)
    for i in range(45):
        write(conn, director.user_id, "payment.record",
              f"2026-10-20T{8 + i // 60:02d}:{i % 60:02d}:00")
    widget = view()
    assert widget.count.text() == "20 sur 45 opérations (la suite en descendant)"
    widget.table.scrollToBottom()
    qtbot.waitUntil(lambda: widget.table.rowCount() >= 40)
    widget.table.scrollToBottom()
    qtbot.waitUntil(lambda: widget.table.rowCount() == 45)
    assert widget.count.text() == "45 opération(s)"
    assert widget.table.item(44, 0).text() == "20/10/2026 08:00"


def test_donnees_opens_the_journal(qtbot, conn, director, monkeypatch):
    from tadris.ui.pages.settings.data import DataSection
    from tadris.ui.pages.settings.journal import JournalView
    from tadris.ui.widgets.forms import SectionWindow

    opened = []
    monkeypatch.setattr(SectionWindow, "exec", lambda self: opened.append(self) or 0)
    section = DataSection(conn, director)
    qtbot.addWidget(section)
    assert section.journal.text() == t["data.journal_open"]
    qtbot.mouseClick(section.journal, Qt.MouseButton.LeftButton)
    assert opened[0].windowTitle() == t["journal.title"]
    assert isinstance(opened[0].section, JournalView)
