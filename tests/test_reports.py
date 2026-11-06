"""Rapports: every figure against a hand count on a small school."""

import json
from datetime import date

import pytest

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import PermissionDenied, ValidationError
from tadris.domain.models import GroupInput, SlotInput, StudentInput, TeacherInput
from tadris.i18n.fr import t
from tadris.services import (
    attendance,
    auth,
    catalog,
    enrollments,
    groups,
    payments,
    payouts,
    registrations,
    reports,
    rooms,
    school_years,
    students,
    subscriptions,
    teachers,
    timetable,
)

TODAY = date(2026, 10, 18)  # a Sunday
MONDAY = date(2026, 10, 19)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(dates, "today", lambda: TODAY)


@pytest.fixture
def director(conn):
    return auth.bootstrap_director(conn, "directeur", "password1", "École Ennour")


@pytest.fixture
def desk(conn, director):
    user_id = auth.create_user(conn, director, "accueil", "password2", "receptionist")
    return UserContext(user_id=user_id, username="accueil", role="receptionist")


class School:
    """Karim (60 %) teaches A (6 000 DA) and B (12 000 DA); Samia (50 %) teaches C (4 000 DA).

    A: Amine and Badis from 01/09; Amine's month renewed for October.
    B: Chems from 01/09.  C: Dalia from 01/10.  Farid: registered, fee 1 000, no group.
    Amine pays 12 000 (September and October of A); Chems 5 000 of his 12 000; a payment
    of Badis is voided. A and C meet on Mondays."""

    def __init__(self, conn, ctx):
        self.conn, self.ctx = conn, ctx
        self.year = school_years.create(conn, ctx, "2026-2027", date(2026, 9, 1),
                                        date(2027, 6, 30))
        self.level = catalog.create(conn, ctx, "level", "4AM")
        self.karim = teachers.create(conn, ctx, TeacherInput("Karim Haddad"), 6000,
                                     date(2026, 9, 1))
        self.samia = teachers.create(conn, ctx, TeacherInput("Samia Rahmani"), 5000,
                                     date(2026, 9, 1))
        self.a = self.group("A", "Maths", 6000, self.karim)
        self.b = self.group("B", "Physique", 12000, self.karim)
        self.c = self.group("C", "Arabe", 4000, self.samia)
        room = rooms.create(conn, ctx, "Salle 1", 20)
        other = rooms.create(conn, ctx, "Salle 2", 20)
        timetable.add_slot(conn, ctx, SlotInput(self.a, room, 1, "17:00", "18:30"))
        timetable.add_slot(conn, ctx, SlotInput(self.c, other, 1, "10:00", "11:30"))
        self.amine, self.amine_a = self.pupil("Amine", self.a)
        self.badis, self.badis_a = self.pupil("Badis", self.a)
        self.chems, _ = self.pupil("Chems", self.b)
        self.dalia, self.dalia_c = self.pupil("Dalia", self.c, date(2026, 10, 1))
        self.farid = students.create(conn, ctx, StudentInput("Farid", "Zerrouki"))
        registrations.register(conn, ctx, self.farid, self.level, 1000)
        [first] = subscriptions.for_enrollment(conn, ctx, self.amine_a)
        subscriptions.renew(conn, ctx, first.id)
        payments.record(conn, ctx, self.amine, 12000, "cash")
        payments.record(conn, ctx, self.chems, 5000, "cash")
        wrong = payments.record(conn, ctx, self.badis, 6000, "cash")
        payments.void(conn, ctx, wrong, "erreur de saisie")

    def group(self, name, subject, price, teacher):
        subject_id = catalog.create(self.conn, self.ctx, "subject", subject)
        return groups.create(self.conn, self.ctx, GroupInput(
            self.year, self.level, subject_id, name, price, 30, date(2026, 9, 1)), teacher)

    def pupil(self, first, group_id, on=date(2026, 9, 1)) -> tuple[int, int]:
        student = students.create(self.conn, self.ctx, StudentInput(first, "Test"))
        registrations.register(self.conn, self.ctx, student, self.level, 0)
        return student, enrollments.enroll(self.conn, self.ctx, student, group_id,
                                           enrolled_on=on)


@pytest.fixture
def school(conn, director):
    return School(conn, director)


def tiles(report) -> list:
    return [(tile.label, tile.value) for tile in report.tiles]


# ----- who sees what -----

def test_the_desk_sees_attendance_and_students(desk, director):
    assert reports.available(director) == ["revenue", "attendance", "teachers"]
    assert reports.available(desk) == ["attendance"]  # the students' list: the Élèves page


def test_money_reports_are_the_directors(conn, desk, school):
    with pytest.raises(PermissionDenied):
        reports.revenue(conn, desk, school.year)
    with pytest.raises(PermissionDenied):
        reports.teacher_summary(conn, desk, school.year)


# ----- Recettes -----

def test_revenue_by_month(conn, director, school):
    report = reports.revenue(conn, director, school.year, "month")
    assert tiles(report) == [("Facturé", 35000), ("Encaissé", 17000), ("Reste dû", 18000),
                             ("Part école", 15000)]
    by_month = {row[0]: row[1:] for row in report.rows}
    assert len(report.rows) == 10  # September to June, empty months too
    # September: A 2 x 6 000 + B 12 000; Karim's 60 % of each: 14 400.
    assert by_month["Septembre 2026"] == (24000, 11000, 13000, 0, 14400, 9600)
    # October: A 6 000 (60 %), C 4 000 (50 %), Farid's fee 1 000 (all the school's).
    assert by_month["Octobre 2026"] == (11000, 6000, 5000, 17000, 5600, 5400)
    assert by_month["Novembre 2026"] == (0, 0, 0, 0, 0, 0)
    assert report.total == ("Total", 35000, 17000, 18000, 17000, 20000, 15000)
    assert report.chart.labels[:2] == ("sept.", "oct.")
    assert report.chart.series == (
        ("Facturé", (24000, 11000) + (0,) * 8), ("Encaissé", (0, 17000) + (0,) * 8))


def test_revenue_by_group_the_fees_last(conn, director, school):
    report = reports.revenue(conn, director, school.year, "group")
    assert [row[:2] for row in report.rows] == [
        ("A · Maths 4AM", "Karim Haddad"), ("B · Physique 4AM", "Karim Haddad"),
        ("C · Arabe 4AM", "Samia Rahmani"), (t["reports.fees"], None)]
    assert [row[2:] for row in report.rows] == [
        (3, 18000, 12000, 6000, 6000, 10800, 7200),
        (1, 12000, 5000, 7000, 6000, 7200, 4800),
        (1, 4000, 0, 4000, 5000, 2000, 2000),
        (1, 1000, 0, 1000, None, 0, 1000)]
    assert report.total == ("Total", None, 6, 35000, 17000, 18000, None, 20000, 15000)
    assert report.row_ids == (school.a, school.b, school.c, None)
    assert report.opens == "groups"


def test_a_cancelled_month_does_not_count(conn, director, school):
    [october] = [s for s in subscriptions.for_enrollment(conn, director, school.dalia_c)]
    subscriptions.cancel(conn, director, october.id, "ne vient plus")
    report = reports.revenue(conn, director, school.year)
    assert report.tiles[0].value == 31000


def test_the_summer_before_the_year_is_its(conn, director, monkeypatch):
    """Registered and paid on 25/08, before the year's first day: the fee and the money
    count in the year, in an August row; the summer after the previous year too, never
    before it."""
    monkeypatch.setattr(dates, "today", lambda: date(2026, 8, 25))
    old = school_years.create(conn, director, "2025-2026", date(2025, 9, 1),
                              date(2026, 6, 30))
    school_years.close(conn, director, old)
    year = school_years.create(conn, director, "2026-2027", date(2026, 9, 1),
                               date(2027, 6, 30))
    level = catalog.create(conn, director, "level", "4AM")
    student = students.create(conn, director, StudentInput("Amine", "Test"))
    registrations.register(conn, director, student, level, 1500)
    payments.record(conn, director, student, 1500, "cash")
    monkeypatch.setattr(dates, "today", lambda: TODAY)
    report = reports.revenue(conn, director, year)
    assert tiles(report) == [("Facturé", 1500), ("Encaissé", 1500), ("Reste dû", 0),
                             ("Part école", 1500)]
    assert report.rows[0] == ("Août 2026", 1500, 1500, 0, 1500, 0, 1500)
    assert len(report.rows) == 11  # August, then September to June
    assert tiles(reports.revenue(conn, director, old))[:2] == [("Facturé", 0), ("Encaissé", 0)]


def test_june_paid_in_july_is_the_years(conn, director, school, monkeypatch):
    """A June payout handed over on 02/07: paid for the year, not waiting."""
    monkeypatch.setattr(dates, "today", lambda: date(2027, 7, 2))
    payout = payouts.build_draft(conn, director, school.karim, date(2027, 6, 30))
    payouts.approve(conn, director, payout)
    payouts.mark_paid(conn, director, payout, "cash")
    karim = next(row for row in reports.teacher_summary(conn, director, school.year).rows
                 if row[0] == "Karim Haddad")
    assert (karim[5], karim[6], karim[7]) == (18000, 18000, 0)  # share due, paid, waiting


def test_the_teachers_share_follows_the_rate_of_the_months_first_day(conn, director, school):
    teachers.set_rate(conn, director, school.karim, 5000, date(2026, 10, 1))
    by_month = {row[0]: row for row in reports.revenue(conn, director, school.year).rows}
    assert by_month["Septembre 2026"][5] == 14400  # still 60 %
    assert by_month["Octobre 2026"][5] == 3000 + 2000  # A's October at 50 %, C at 50 %


# ----- Présences -----

@pytest.fixture
def marked(conn, director, school, monkeypatch):
    """Monday 19/10: Amine present, Badis absent in A; Dalia late in C."""
    monkeypatch.setattr(dates, "today", lambda: MONDAY)

    def session(group_id):
        return conn.execute("SELECT id FROM sessions WHERE date = ? AND group_id = ?",
                            (dates.iso(MONDAY), group_id)).fetchone()[0]

    attendance.save(conn, director, session(school.a),
                    {school.amine_a: "present", school.badis_a: "absent"})
    attendance.save(conn, director, session(school.c), {school.dalia_c: "late"})
    return school


def test_attendance_by_group(conn, desk, marked):
    report = reports.attendance(conn, desk, date(2026, 10, 1), date(2026, 10, 31))
    assert tiles(report) == [("Taux de présence", 6667), ("Séances tenues", 2),  # 2 of 3, rounded
                             ("Présences", 2), ("Absences", 1)]
    # Two marks only: Dalia, late, came (Présent); no « Retard » nor « Excusé » column.
    assert [c.title for c in report.columns][-3:] == ["Présent", "Absent", "Taux de présence"]
    assert report.rows == (
        ("A · Maths 4AM", "Karim Haddad", 1, 2, 1, 1, 5000),
        ("C · Arabe 4AM", "Samia Rahmani", 1, 1, 1, 0, 10000))
    assert report.tones == ("danger", None)  # under 75 %
    assert report.total == ("Total", None, 2, None, 2, 1, 6667)
    assert report.chart.labels == ("C · Arabe 4AM", "A · Maths 4AM")  # best first
    assert report.period == "Du 01/10/2026 au 31/10/2026"


def test_attendance_by_student_the_lowest_first(conn, desk, marked):
    report = reports.attendance(conn, desk, date(2026, 10, 1), date(2026, 10, 31),
                                view="student")
    assert [(row[0], row[-1]) for row in report.rows] == [
        ("Test Badis", 0), ("Test Amine", 10000), ("Test Dalia", 10000)]
    assert report.row_ids == (marked.badis, marked.amine, marked.dalia)
    assert report.total[0] == "3 élève(s)"


def test_attendance_of_one_group_and_the_dates(conn, desk, marked):
    report = reports.attendance(conn, desk, date(2026, 10, 1), date(2026, 10, 31), marked.c)
    assert [row[0] for row in report.rows] == ["C · Arabe 4AM"]
    assert ("Groupe", "C · Arabe 4AM") in report.filters
    empty = reports.attendance(conn, desk, date(2026, 10, 20), date(2026, 10, 31))
    assert (empty.rows, empty.total, empty.tiles[0].value) == ((), None, None)
    with pytest.raises(ValidationError):
        reports.attendance(conn, desk, date(2026, 10, 31), date(2026, 10, 1))


def test_period_presets():
    assert reports.period_range(None, "week", TODAY) == (date(2026, 10, 17), date(2026, 10, 23))
    assert reports.period_range(None, "month", TODAY) == (date(2026, 10, 1), date(2026, 10, 31))
    assert reports.period_range(None, "last_month", TODAY) == (date(2026, 9, 1),
                                                               date(2026, 9, 30))


# ----- Enseignants -----

def test_teacher_summary(conn, director, school, monkeypatch):
    payout = payouts.build_draft(conn, director, school.karim, date(2026, 10, 1))
    payouts.approve(conn, director, payout)
    payouts.mark_paid(conn, director, payout, "cash")
    on_18 = reports.teacher_summary(conn, director, school.year)
    assert [row[8] for row in on_18.rows] == [0, 0]  # October's months still run: not yet
    monkeypatch.setattr(dates, "today", lambda: date(2026, 11, 1))  # they are over
    report = reports.teacher_summary(conn, director, school.year)
    # Karim: A (2) and B (1); his months 30 000, 60 %: 18 000; September paid (14 400),
    # A's October not prepared yet (3 600). Samia: C, 4 000 at 50 %.
    assert report.rows == (
        ("Karim Haddad", 2, 3, 6000, 30000, 18000, 14400, 0, 3600),
        ("Samia Rahmani", 1, 1, 5000, 4000, 2000, 0, 0, 2000))
    assert tiles(report) == [("Enseignants actifs", 2), ("Groupes en cours", 3),
                             ("Payé cette année", 14400), ("Reste à payer", 5600)]
    assert report.total == ("Total", 3, 4, None, 34000, 20000, 14400, 0, 5600)
    assert report.row_ids == (school.karim, school.samia) and report.opens == "teachers"


# ----- Élèves -----

def test_student_list(conn, desk, school):
    report = reports.student_list(conn, desk)
    assert [(row[1], row[2], row[3], row[6], row[7]) for row in report.rows] == [
        ("Test Amine", "4AM", "A · Maths", "2026-10-18", 0),
        ("Test Badis", "4AM", "A · Maths", "2026-10-18", 6000),
        ("Test Chems", "4AM", "B · Physique", "2026-10-18", 7000),
        ("Test Dalia", "4AM", "C · Arabe", "2026-10-18", 4000),
        ("Zerrouki Farid", "4AM", None, "2026-10-18", 1000)]
    assert report.tiles == ()  # a plain list: no figures above it
    assert report.total == ("5 élève(s)",) + (None,) * 6 + (18000,)


def test_student_list_filters(conn, desk, school):
    in_a = reports.student_list(conn, desk, group_id=school.a)
    assert [row[1] for row in in_a.rows] == ["Test Amine", "Test Badis"]
    found = reports.student_list(conn, desk, query="zerr")
    assert [row[1] for row in found.rows] == ["Zerrouki Farid"]
    assert ("Recherche", "zerr") in found.filters
    with pytest.raises(ValidationError):
        reports.student_list(conn, desk, status="gone")


# ----- exports -----

def test_export_pdf_and_excel_and_the_audit(conn, director, school, tmp_path):
    from openpyxl import load_workbook

    report = reports.revenue(conn, director, school.year, "group")
    pdf = reports.export(conn, director, report, "pdf", tmp_path / "recettes.pdf")
    assert pdf.read_bytes().startswith(b"%PDF")
    xlsx = reports.export(conn, director, report, "xlsx", tmp_path / "recettes.xlsx")
    book = load_workbook(xlsx)
    assert book.sheetnames == ["Recettes par groupe", "Infos"]
    sheet = book.worksheets[0]
    assert sheet["A1"].value == "Recettes par groupe"
    assert [c.value for c in sheet[6]] == [
        "Groupe", "Enseignant", "Mois facturés", "Facturé (DA)", "Réglé (DA)",
        "Reste dû (DA)", "Taux", "Part enseignants (DA)", "Part école (DA)"]
    assert [c.value for c in sheet[7]] == ["A · Maths 4AM", "Karim Haddad", 3, 18000, 12000,
                                           6000, 0.6, 10800, 7200]
    assert sheet["D7"].number_format == '#,##0 "DA"' and sheet["G7"].number_format == "0.0%"
    total = [c.value for c in sheet[11]]
    assert total[:4] == ["Total", None, "=SUBTOTAL(9,C7:C10)", "=SUBTOTAL(9,D7:D10)"]
    assert total[6] is None  # no total of rates
    assert (sheet.freeze_panes, sheet.auto_filter.ref) == ("A7", "A6:I10")
    assert [row[0].value for row in book["Infos"].iter_rows()][:2] == ["Rapport", "Période"]
    logged = [json.loads(row[0]) for row in conn.execute(
        "SELECT new_value FROM audit_log WHERE action = 'report.export' ORDER BY id")]
    assert logged == [{"report": "Recettes par groupe", "format": "PDF", "rows": 4},
                      {"report": "Recettes par groupe", "format": "Excel", "rows": 4}]


def test_an_export_goes_to_the_documents_folder(conn, desk, school, tmp_path, monkeypatch):
    from tadris import config

    monkeypatch.setattr(config, "documents_dir", lambda: tmp_path)
    path = reports.export(conn, desk, reports.student_list(conn, desk), "xlsx")
    assert path.parent == tmp_path
    assert path.name.startswith("rapport_liste-eleves_") and path.suffix == ".xlsx"


def test_typed_text_never_becomes_a_formula(conn, desk, school, tmp_path):
    from openpyxl import load_workbook

    students.create(conn, desk, StudentInput("=HYPERLINK(\"x\")", "Zz"))
    path = reports.export(conn, desk, reports.student_list(conn, desk), "xlsx",
                          tmp_path / "eleves.xlsx")
    cell = next(row[1] for row in load_workbook(path).worksheets[0].iter_rows(min_row=7)
                if str(row[1].value).startswith("Zz"))
    assert cell.data_type == "s" and cell.value == 'Zz =HYPERLINK("x")'


def test_an_unknown_format_is_refused(conn, desk, school, tmp_path):
    with pytest.raises(ValidationError):
        reports.export(conn, desk, reports.student_list(conn, desk), "docx", tmp_path / "x")
