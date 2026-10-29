from dataclasses import replace
from datetime import date

import pytest
from PySide6.QtCore import Qt

from tadris.core import dates, whatsapp
from tadris.core.errors import BusinessRuleError, PermissionDenied, ValidationError
from tadris.core.money import format_dzd
from tadris.core.phones import is_mobile
from tadris.domain.models import (
    ContactInput,
    ContactLink,
    GroupInput,
    SlotInput,
    StudentInput,
    TeacherInput,
)
from tadris.i18n.fr import t
from tadris.services import (
    announcements,
    attendance,
    auth,
    catalog,
    contacts,
    debt,
    enrollments,
    groups,
    holidays,
    messages,
    payments,
    registrations,
    rooms,
    school_years,
    sessions,
    students,
    teachers,
    timetable,
)
from tadris.ui.pages import contacts_page
from tadris.ui.pages.contacts_page import ContactsPage
from tadris.ui.theme import apply_theme, load_fonts
from tadris.ui.widgets.qr_code import modules


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


class School:
    """Maths M1: Amine and Sara (siblings, one mother), Yanis (a landline father and a
    mother who wants no messages), and Lina, who left."""

    def __init__(self, conn, ctx):
        year = school_years.create(conn, ctx, "2026-2027", date(2026, 9, 1), date(2027, 6, 30))
        level = catalog.create(conn, ctx, "level", "4AM")
        teacher = teachers.create(conn, ctx, TeacherInput("Karim Haddad"), 6000,
                                  date(2026, 9, 1))
        maths = catalog.create(conn, ctx, "subject", "Maths")
        self.group = groups.create(conn, ctx, GroupInput(year, level, maths, "M1", 3000, 20,
                                                         date(2026, 9, 1)), teacher)

        def student(first, last, contact=None, link=None):
            sid = students.create(conn, ctx, StudentInput(first, last), contact, link)
            registrations.register(conn, ctx, sid, level, 0)
            enrollments.enroll(conn, ctx, sid, self.group)
            return sid

        self.amine = student("Amine", "Benali", ContactInput("Fatima Benali", "0661 90 25 47"),
                             ContactLink(relation="Mère"))
        self.sara = student("Sara", "Benali")
        mother = contacts.list_for_student(conn, ctx, self.amine)[0].contact_id
        contacts.link_existing(conn, ctx, self.sara, mother, ContactLink(relation="Mère"))
        self.yanis = student("Yanis", "Kaci", ContactInput("Omar Kaci", "048 55 12 30"),
                             ContactLink(relation="Père"))
        contacts.add(conn, ctx, self.yanis, ContactInput("Nadia Kaci", "0770 11 22 33"),
                     ContactLink(relation="Mère", can_receive_sms=False))
        self.lina = student("Lina", "Saidi", ContactInput("Rachid Saidi", "0550 12 34 56"))
        live = enrollments.for_student(conn, ctx, self.lina)[0]
        enrollments.leave(conn, ctx, live.id)


@pytest.fixture
def school(conn, director):
    return School(conn, director)


# ----- links -----

def test_only_mobiles_have_whatsapp():
    assert is_mobile("0661902547") and is_mobile("0550123456") and is_mobile("0770112233")
    assert not is_mobile("048551230") and not is_mobile(None) and not is_mobile("")
    assert whatsapp.international("0661902547") == "213661902547"
    assert whatsapp.international("048551230") is None


def test_the_link_carries_the_message_encoded():
    text = "Bonjour, Amine était absent & en retard ?"
    assert whatsapp.web_link("0661902547", text) == (
        "https://wa.me/213661902547?text="
        "Bonjour%2C%20Amine%20%C3%A9tait%20absent%20%26%20en%20retard%20%3F")
    assert whatsapp.app_link("0661902547", "Salut").startswith(
        "whatsapp://send?phone=213661902547&text=Salut")


def test_a_computer_without_the_app_opens_whatsapp_web(monkeypatch):
    from PySide6.QtGui import QDesktopServices

    urls = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: urls.append(url.toString()))
    monkeypatch.setattr(whatsapp, "desktop_app_installed", lambda: False)
    contacts_page.open_chat("0661902547", "Salut")
    monkeypatch.setattr(whatsapp, "desktop_app_installed", lambda: True)
    contacts_page.open_chat("0661902547", "Salut")
    assert urls == ["https://web.whatsapp.com/send?phone=213661902547&text=Salut",
                    "whatsapp://send?phone=213661902547&text=Salut"]


def test_the_student_placeholder_names_each_child():
    text = "Bonjour, {élève} a cours demain."
    assert whatsapp.personal(text, ["Amine"]) == "Bonjour, Amine a cours demain."
    assert whatsapp.personal(text, ["Amine", "Sara"]) == "Bonjour, Amine et Sara a cours demain."
    assert whatsapp.personal(text, ["A", "B", "C"]).startswith("Bonjour, A, B et C")
    assert whatsapp.personal("Sans nom", ["Amine"]) == "Sans nom"


def test_a_usual_message_fits_a_qr_code_a_long_one_does_not():
    usual = whatsapp.web_link("0661902547", "Bonjour, Amine était absent aujourd'hui au "
                              "cours de maths de 14 h. Merci de nous prévenir la prochaine "
                              "fois. La direction.")
    assert whatsapp.fits_qr(usual)
    grid = modules(usual)
    assert len(grid) == len(grid[0]) > 21
    assert not whatsapp.fits_qr(whatsapp.web_link("0661902547", "é" * 120))


# ----- who gets the message -----

def test_a_group_reaches_each_parent_once_and_only_those_who_accept(conn, director, school):
    found = messages.for_group(conn, director, school.group)
    assert [(r.full_name, r.relation, r.students) for r in found] == [
        ("Fatima Benali", "Mère", ("Amine", "Sara")),  # two children, one message
        ("Omar Kaci", "Père", ("Yanis",)),
    ]  # Nadia Kaci refuses messages; Lina left the group
    assert found[0].phone == "0661902547"
    assert found[1].phone is None  # a landline: listed, but no WhatsApp


def test_a_second_phone_that_is_a_mobile_is_used(conn, director, school):
    omar = messages.for_group(conn, director, school.group)[1]
    contacts.update(conn, director, school.yanis, omar.contact_id,
                    ContactInput("Omar Kaci", "048 55 12 30", "0699 88 77 66"),
                    ContactLink(relation="Père", is_main=True))
    assert messages.for_group(conn, director, school.group)[1].phone == "0699887766"


def test_a_student_reaches_their_own_contacts(conn, receptionist, school):
    assert [r.full_name for r in messages.for_student(conn, receptionist, school.sara)] == [
        "Fatima Benali"]
    assert [r.full_name for r in messages.for_student(conn, receptionist, school.yanis)] == [
        "Omar Kaci"]


def test_sending_needs_the_permission(conn, director, school):
    from dataclasses import replace

    nobody = replace(director, role="nobody")
    with pytest.raises(PermissionDenied):
        messages.for_group(conn, nobody, school.group)


# ----- the page -----

@pytest.fixture
def opened(monkeypatch):
    chats = []
    monkeypatch.setattr(contacts_page, "open_chat", lambda phone, text: chats.append((phone, text)))
    return chats


def make_page(qtbot, conn, ctx) -> ContactsPage:
    page = ContactsPage(conn, ctx)
    qtbot.addWidget(page)
    return page


def states(page) -> list[str]:
    return [page.table.item(r, 4).text() for r in range(page.table.rowCount())]


def test_the_menu_says_contacts(qtbot, conn, receptionist):
    from tadris.ui.main_window import MainWindow

    window = MainWindow(conn, receptionist)
    qtbot.addWidget(window)
    assert "sms" not in window.nav_buttons
    window.nav_buttons["contacts"].click()
    assert isinstance(window.pages.currentWidget(), ContactsPage)
    assert window.nav_buttons["contacts"].text() == "Contacts"


def test_a_group_message_opens_whatsapp_parent_after_parent(qtbot, conn, receptionist, school,
                                                            opened):
    page = make_page(qtbot, conn, receptionist)
    page.show_group(school.group)
    assert states(page) == [t["contacts.state.to_send"], t["contacts.state.no_mobile"]]
    assert not page.open_button.isEnabled()  # no message yet
    assert page.qr.is_empty()

    page.message.setPlainText("Bonjour, {élève} n'a pas cours samedi.")
    assert page.open_button.isEnabled()
    assert not page.qr.is_empty()
    qtbot.mouseClick(page.next_button, Qt.MouseButton.LeftButton)
    assert opened == [("0661902547", "Bonjour, Amine et Sara n'a pas cours samedi.")]
    assert states(page)[0] == t["contacts.state.opened"]
    assert page.count.text() == "1 ouvert(s) sur 1"
    assert not page.next_button.isEnabled()  # nobody left with WhatsApp

    page.table.selectRow(1)  # the landline
    assert not page.open_button.isEnabled()
    assert page.qr.is_empty()
    assert "fixe" in page.qr_caption.text()


def test_one_student_from_the_picker(qtbot, conn, receptionist, school, opened):
    page = make_page(qtbot, conn, receptionist)
    assert page.empty.text() == t["contacts.pick_first"]
    page.show_student(school.amine)
    assert page.student_label.text() == "Benali Amine"
    page.message.setPlainText("Rappel pour {élève}")
    page.open_selected()
    assert opened == [("0661902547", "Rappel pour Amine")]


def test_a_message_too_long_is_not_opened(qtbot, conn, receptionist, school, opened):
    page = make_page(qtbot, conn, receptionist)
    page.show_group(school.group)
    page.message.setPlainText("x" * (whatsapp.MAX_LENGTH + 1))
    assert not page.open_button.isEnabled()
    assert "raccourcissez" in page.length.text()
    page.open_selected()
    assert opened == []


def test_a_message_too_long_for_the_qr_code_still_opens(qtbot, conn, receptionist, school,
                                                        opened):
    page = make_page(qtbot, conn, receptionist)
    page.show_group(school.group)
    page.message.setPlainText("é" * 300)
    assert page.qr.is_empty()
    assert page.qr_caption.text() == t["contacts.qr_too_long"]
    page.open_selected()
    assert len(opened) == 1


# ----- the WhatsApp group of a group -----

CODE = "AbCdEfGhIjKlMnOpQrStUv"


def test_an_invite_link_is_read_as_whatsapp_copies_it():
    for text in (f"https://chat.whatsapp.com/{CODE}", f" chat.whatsapp.com/{CODE} ",
                 f"https://chat.whatsapp.com/{CODE}?mode=ac_t",
                 f"https://chat.whatsapp.com/invite/{CODE}"):
        assert whatsapp.invite_code(text) == CODE
    for text in ("", "https://wa.me/213661902547", f"https://evil.com/{CODE}",
                 "https://chat.whatsapp.com/short"):
        assert whatsapp.invite_code(text) is None
    assert whatsapp.invite_link(CODE) == f"https://chat.whatsapp.com/{CODE}"
    assert whatsapp.group_app_link(CODE) == f"whatsapp://chat?code={CODE}"
    assert whatsapp.group_browser_link(CODE) == f"https://web.whatsapp.com/accept?code={CODE}"


def test_linking_a_group_keeps_its_code_and_who_was_invited(conn, receptionist, school):
    assert messages.group_code(conn, receptionist, school.group) is None
    with pytest.raises(BusinessRuleError):
        messages.mark_invited(conn, receptionist, school.group, 1)
    with pytest.raises(ValidationError) as exc:
        messages.link_group(conn, receptionist, school.group, "https://wa.me/213661902547")
    assert exc.value.message == t["whatsapp_group.link_invalid"]

    messages.link_group(conn, receptionist, school.group, f"https://chat.whatsapp.com/{CODE}")
    assert messages.group_code(conn, receptionist, school.group) == CODE
    fatima = messages.for_group(conn, receptionist, school.group)[0].contact_id
    messages.mark_invited(conn, receptionist, school.group, fatima)
    messages.mark_invited(conn, receptionist, school.group, fatima)  # once is enough
    assert list(messages.invited(conn, receptionist, school.group)) == [fatima]

    messages.link_group(conn, receptionist, school.group, f"chat.whatsapp.com/{CODE}")
    assert list(messages.invited(conn, receptionist, school.group)) == [fatima]  # same link
    messages.link_group(conn, receptionist, school.group,
                        "https://chat.whatsapp.com/ZyXwVuTsRqPoNmLkJiHgFe")
    assert messages.invited(conn, receptionist, school.group) == {}  # the old link is dead
    messages.unlink_group(conn, receptionist, school.group)
    assert messages.group_code(conn, receptionist, school.group) is None
    actions = [row["action"] for row in conn.execute(
        "SELECT action FROM audit_log WHERE action LIKE 'whatsapp_group.%' ORDER BY id")]
    assert actions == ["whatsapp_group.link", "whatsapp_group.link", "whatsapp_group.unlink"]


# ----- models -----

@pytest.fixture
def week(conn, director, school):
    """Thursday 17:00-18:30 and Sunday (today) 09:00-10:30 in Salle A; on 29/10 no class."""
    room = rooms.create(conn, director, "Salle A", 20)
    for weekday, start, end in ((4, "17:00", "18:30"), (7, "09:00", "10:30")):
        timetable.add_slot(conn, director, SlotInput(school.group, room, weekday, start, end))
    sessions.generate(conn, director)
    found = {s.date: s for s in sessions.listing(conn, director, date(2026, 10, 18),
                                                 date(2026, 11, 1), group_id=school.group)}
    sessions.cancel(conn, director, found["2026-10-29"].id, "Enseignant malade")
    sessions.reschedule(conn, director, found["2026-10-22"].id, date(2026, 10, 21), "16:00",
                        "17:30", room, "Sortie scolaire")
    other = teachers.create(conn, director, TeacherInput("Samia Ait"), 5000, date(2026, 9, 1))
    sessions.set_teacher(conn, director, found["2026-10-25"].id, other)
    return found


def compose(conn, ctx, kind, school, **kw):
    found = announcements.choices(conn, ctx, kind, school.group, kw.get("student"))
    return found, announcements.compose(conn, ctx, kind, found[0].id if found else None,
                                        school.group, kw.get("student"))


def test_the_cancelled_session_of_the_29th(conn, receptionist, school, week):
    found, text = compose(conn, receptionist, "cancelled", school)
    assert [c.label for c in found] == [  # cancelled in Présences first, then announced
        "jeudi 29/10/2026 · 17:00–18:30 · Enseignant malade"]  # (the moved one is « moved »)
    assert text == (
        "Bonjour, la séance de Maths 4AM (M1) du jeudi 29/10/2026 de 17:00 à 18:30 est "
        "annulée : pas de cours ce jour-là.\nMotif : Enseignant malade.\n\nÉcole Ennour")


def test_a_moved_session_says_where_it_goes(conn, receptionist, school, week):
    found, text = compose(conn, receptionist, "moved", school)
    assert [c.label for c in found] == ["jeudi 22/10/2026 → mercredi 21/10/2026"]
    assert text.startswith(
        "Bonjour, la séance de Maths 4AM (M1) du jeudi 22/10/2026 de 17:00 à 18:30 est "
        "déplacée au mercredi 21/10/2026 de 16:00 à 17:30, salle Salle A.")


def test_reminder_and_substitute(conn, receptionist, school, week):
    found, text = compose(conn, receptionist, "reminder", school)
    assert found[0].label == "dimanche 18/10/2026 · 09:00–10:30"  # today, still to come
    assert "cancelled" not in {s.status for s in sessions.listing(
        conn, receptionist, date(2026, 10, 18), date(2026, 10, 18))}
    assert "prochaine séance de Maths 4AM (M1) a lieu le dimanche 18/10/2026" in text
    found, text = compose(conn, receptionist, "substitute", school)
    assert [c.label for c in found] == ["dimanche 25/10/2026 · 09:00–10:30 · Samia Ait"]
    assert "sera assurée par Samia Ait, en remplacement de Karim Haddad" in text


def test_holidays_one_day_and_a_period(conn, director, receptionist, school):
    assert announcements.choices(conn, receptionist, "holiday", school.group) == []
    with pytest.raises(ValidationError) as exc:
        announcements.compose(conn, receptionist, "holiday", None, school.group)
    assert exc.value.message == t["announce.none.holiday"]
    holidays.create(conn, director, "Fête de la Révolution", date(2026, 11, 1))
    holidays.create(conn, director, "Vacances d'hiver", date(2026, 12, 17), date(2027, 1, 3))
    holidays.create(conn, director, "Passé", date(2026, 10, 1))
    found = announcements.choices(conn, receptionist, "holiday", school.group)
    assert [c.label for c in found] == [
        "Fête de la Révolution · le dimanche 01/11/2026",
        "Vacances d'hiver · du jeudi 17/12/2026 au dimanche 03/01/2027"]
    one = announcements.compose(conn, receptionist, "holiday", found[0].id, school.group)
    assert one.startswith("Bonjour, l'école sera fermée le dimanche 01/11/2026 (Fête de la "
                          "Révolution) : pas de cours ce jour-là.")
    period = announcements.compose(conn, receptionist, "holiday", found[1].id, school.group)
    assert "Reprise des cours le lundi 04/01/2027." in period


def test_a_group_named_after_its_course_is_named_once(conn, director, school):
    g = groups.get(conn, director, school.group)
    assert announcements.group_label(g) == "Maths 4AM (M1)"
    assert announcements.group_label(replace(g, name="maths 4am")) == "Maths 4AM"


def test_a_session_still_planned_cannot_be_announced_as_cancelled(conn, director,
                                                                   receptionist, school, week):
    """The message follows Présences, never the reverse: cancel first, then announce."""
    found = announcements.choices(conn, receptionist, "cancelled", school.group)
    assert "2026-10-25" not in {sessions.get(conn, receptionist, c.id).date for c in found}
    sessions.cancel(conn, director, week["2026-10-25"].id, "Grève")
    found = announcements.choices(conn, receptionist, "cancelled", school.group)
    assert [c.label for c in found] == ["dimanche 25/10/2026 · 09:00–10:30 · Grève",
                                        "jeudi 29/10/2026 · 17:00–18:30 · Enseignant malade"]


def test_timetable_payment_and_invitation(conn, receptionist, school, week):
    _, text = compose(conn, receptionist, "timetable", school)
    assert text.startswith("Bonjour, voici les horaires de Maths 4AM (M1) :\n"
                           "• dimanche de 09:00 à 10:30, salle Salle A\n"  # Saturday first
                           "• jeudi de 17:00 à 18:30, salle Salle A")
    found, text = compose(conn, receptionist, "payment", school)
    assert [c.id for c in found] == ["2026-10", "2026-11"]
    assert "la mensualité de octobre 2026 pour Maths 4AM (M1) (3 000 DA)" in text
    with pytest.raises(ValidationError):
        announcements.compose(conn, receptionist, "invite", None, school.group)
    messages.link_group(conn, receptionist, school.group, CODE.join(["chat.whatsapp.com/", ""]))
    text = announcements.compose(conn, receptionist, "invite", None, school.group)
    assert "{élève}" in text and f"https://chat.whatsapp.com/{CODE}" in text
    assert whatsapp.personal(text, ["Amine", "Sara"]).count("Amine et Sara") == 1


def test_student_models_absence_and_debt(conn, director, receptionist, school, week):
    assert announcements.kinds("student") == ("free", "absence", "debt", "holiday")
    assert announcements.choices(conn, receptionist, "absence", student_id=school.amine) == []
    enrollment = enrollments.for_student(conn, director, school.amine)[0].id
    attendance.save(conn, director, week["2026-10-18"].id, {enrollment: "absent"})
    found = announcements.choices(conn, receptionist, "absence", student_id=school.amine)
    text = announcements.compose(conn, receptionist, "absence", found[0].id,
                                 student_id=school.amine)
    assert text.startswith("Bonjour, {élève} était absent(e) au cours de M1 · Maths 4AM le "
                           "dimanche 18/10/2026 de 09:00 à 10:30.")
    owed = debt.for_student(conn, receptionist, school.amine).owed_now
    assert owed > 0  # the month of the enrollment
    assert announcements.compose(conn, receptionist, "debt", student_id=school.amine).startswith(
        f"Bonjour, il reste {format_dzd(owed)} à régler pour {{élève}}.")
    payments.record(conn, receptionist, school.amine, owed, "cash")
    with pytest.raises(ValidationError) as exc:
        announcements.compose(conn, receptionist, "debt", student_id=school.amine)
    assert exc.value.message == t["announce.none.debt"]


# ----- the page and the WhatsApp group -----

def test_link_invite_then_post_to_the_group(qtbot, conn, receptionist, school, week, opened,
                                            monkeypatch):
    posted = []
    monkeypatch.setattr(contacts_page, "open_group", lambda code, text: posted.append(
        (code, text)))
    page = make_page(qtbot, conn, receptionist)
    page.show_group(school.group)
    assert page.wa_card.isVisibleTo(page) and not page.post_button.isVisibleTo(page)
    assert "« Maths 4AM (M1) »" in page.wa_text.text()  # the name to give it in WhatsApp

    messages.link_group(conn, receptionist, school.group, f"chat.whatsapp.com/{CODE}")
    page.refresh()
    assert page.post_button.isVisibleTo(page)
    page.template.setCurrentIndex(page.template.findData("invite"))
    assert page.qr_title.text() == t["contacts.qr_invite_title"]
    assert not page.qr.is_empty()  # the group's link, for parents at the desk
    assert not page.post_button.isEnabled()  # the invitation goes to each parent
    assert page.count.text() == "0 invité(s) sur 1"
    page.open_next()
    assert "Amine et Sara" in opened[0][1] and CODE in opened[0][1]
    assert states(page)[0] == "Invité le 18/10/2026"
    assert page.count.text() == "1 invité(s) sur 1"
    page.refresh()  # remembered
    page.template.setCurrentIndex(page.template.findData("invite"))
    assert states(page)[0] == "Invité le 18/10/2026" and not page.next_button.isEnabled()

    page.template.setCurrentIndex(page.template.findData("cancelled"))
    assert "29/10/2026" in page.message.toPlainText()
    qtbot.mouseClick(page.post_button, Qt.MouseButton.LeftButton)
    assert posted == [(CODE, page.message.toPlainText().strip())]
    assert page.paste_hint.isVisibleTo(page)  # WhatsApp cannot type in a group: paste
    assert "Ctrl+V" in page.paste_hint.text()
    page.message.setPlainText("Bonjour {élève}")  # names nobody in a group
    assert not page.post_button.isEnabled()


def test_nothing_cancelled_says_to_cancel_in_presences_first(qtbot, conn, receptionist,
                                                             school):
    page = make_page(qtbot, conn, receptionist)
    page.show_group(school.group)
    page.template.setCurrentIndex(page.template.findData("cancelled"))
    assert page.template_note.text() == t["announce.none.cancelled"]
    assert "Présences" in page.template_note.text()
    assert not page.about.isVisibleTo(page)  # no empty list
    assert page.message.toPlainText() == ""
    page.template.setCurrentIndex(page.template.findData("timetable"))
    assert page.template_note.text() == t["announce.none.timetable"]
    page.show_student(school.amine)
    assert page.template.findData("invite") == -1
    assert not page.wa_card.isVisibleTo(page)
