"""Refunds, step 5: the refund receipt, an 80 mm ticket laid out as the payment receipt. Only a
refund whose money went back has one; printed again, it says DUPLICATA; the payment receipts
it refers to never change.

Amine pays the fee and September (7 000, receipt R2026-00001) on 02/09; on 16/09 the desk
asks 2 000 back; the director approves and hands it back in cash on 20/09."""

import re
from dataclasses import replace
from datetime import date

import pytest
from reportlab.platypus import Paragraph

from tadris.core.errors import BusinessRuleError
from tadris.core.money import dzd_in_words, number_in_words, of_dzd_in_words
from tadris.documents.pdf import register_fonts
from tadris.documents.receipt import TICKET_MARGIN, TICKET_WIDTH, ticket_story
from tadris.i18n.fr import t
from tadris.services import printing, refunds
from test_refunds import (
    ask,
    build_school,
    done,
    fixed_clock,
    gone,
    paid_october,
    paid_september,
    pay,
)

PAID_DAY = date(2026, 9, 20)
REASON = "Départ de l'élève"


@pytest.fixture
def today(monkeypatch):
    return fixed_clock(monkeypatch)


@pytest.fixture
def school(conn, today):
    return build_school(conn, today)


def asked(s, amount=2000) -> int:
    gone(s)  # Amine's last day the 15th
    return refunds.request(s.conn, s.desk, s.september, amount, REASON)


def paid_out(s, amount=2000, method="cash") -> int:
    refund_id = asked(s, amount)
    refunds.approve(s.conn, s.boss, refund_id)
    s.today.day = PAID_DAY
    refunds.pay_out(s.conn, s.boss, refund_id, method)
    return refund_id


def printed(conn, kind: str) -> int:
    return conn.execute("SELECT COUNT(*) FROM print_log WHERE document_type = ?",
                        (kind,)).fetchone()[0]


def texts(doc) -> list[str]:
    register_fonts()
    usable = TICKET_WIDTH - 2 * TICKET_MARGIN
    return [f.getPlainText() for f in ticket_story(doc, usable) if isinstance(f, Paragraph)]


# ----- what the receipt says -----

def test_the_receipt_of_a_paid_refund(conn, school):
    paid_september(school)
    refund_id = paid_out(school)
    doc = printing.refund_receipt_content(conn, school.boss, refund_id)
    assert (doc.title, doc.number, doc.copy_mark) == ("Reçu de remboursement", "RB2026-00001",
                                                      "")
    assert doc.paid_at.startswith("Le 20/09/2026 à ")
    assert doc.details == [
        ("Élève", "Benali Amine (N° 2026-0001)"),
        ("Rendu en", "Espèces"),
        ("Motif", REASON),
        ("Paiement d'origine", "R2026-00001 du 02/09/2026"),
        ("Approuvé par", "directeur"),
        ("Versé par", "directeur"),
    ]
    when = "Du 01/09/2026 au 01/10/2026 · 2 séance(s) sur 4 à partir du 16/09/2026"
    assert doc.lines == [("A · Maths 4AM", when, "2 000 DA")]
    assert doc.total == ("Total remboursé", "2 000 DA")
    assert doc.amount_words == "Arrêté à la somme de deux mille dinars."
    assert (doc.stamp, doc.stamp_date, doc.balance, doc.voided_note) == (
        "REMBOURSÉ", "20/09/2026", [], "")
    assert doc.signature == t["refund_receipt.signature"]


def test_a_month_with_no_session_says_so(conn, school):
    """October, all of it a holiday, refunded in full: no « 0 séance(s) sur 0 »."""
    from tadris.services import holidays

    october = paid_october(school)
    holidays.create(conn, school.boss, "Fermeture", date(2026, 10, 1), date(2026, 10, 31))
    refund_id = ask(school, october, 6000)
    done(school, refund_id)
    [(_title, when, amount)] = printing.refund_receipt_content(conn, school.boss,
                                                               refund_id).lines
    assert when == "Du 01/10/2026 au 01/11/2026 · " + t["refund_receipt.sessions_none"]
    assert amount == "6 000 DA"


def test_the_ticket_shows_the_words_and_no_balance(conn, school):
    paid_september(school)
    doc = printing.refund_receipt_content(conn, school.boss, paid_out(school))
    shown = texts(doc)
    assert "Arrêté à la somme de deux mille dinars." in shown
    assert "RB2026-00001" in shown and "REÇU DE REMBOURSEMENT" in shown
    assert not any(t["receipt.left_now"] in line for line in shown)


def test_the_money_came_from_two_payments(conn, school):
    """September paid 2 000 then 4 000 (after the fee): 5 000 back, the latest first."""
    pay(school, 3000)
    pay(school, 4000, date(2026, 9, 3))
    gone(school, date(2026, 9, 5))  # nothing used yet
    refund_id = refunds.request(conn, school.desk, school.september, 5000, REASON)
    refunds.approve(conn, school.boss, refund_id)
    refunds.pay_out(conn, school.boss, refund_id, "transfer")
    doc = printing.refund_receipt_content(conn, school.boss, refund_id)
    assert dict(doc.details)["Paiement d'origine"] == (
        "R2026-00002 du 03/09/2026, R2026-00001 du 02/09/2026")
    assert dict(doc.details)["Rendu en"] == "Virement"
    assert doc.amount_words == "Arrêté à la somme de cinq mille dinars."


# ----- printing and reprinting -----

def test_printed_then_printed_again_as_a_duplicate(conn, school, tmp_path):
    paid_september(school)
    refund_id = paid_out(school)
    first_doc = printing.refund_receipt_content(conn, school.boss, refund_id)
    path = printing.refund_receipt(conn, school.boss, refund_id, tmp_path)
    assert path == tmp_path / "remboursement_RB2026-00001.pdf"
    assert path.read_bytes().startswith(b"%PDF")
    assert printed(conn, printing.REFUND_RECEIPT) == 1
    school.today.day = date(2026, 10, 5)  # reprinted later, by the desk
    again = printing.refund_receipt_content(conn, school.desk, refund_id)
    assert again.copy_mark == "DUPLICATA"
    same = ("number", "paid_at", "details", "lines", "total", "amount_words", "stamp",
            "stamp_date")
    assert [getattr(again, f) for f in same] == [getattr(first_doc, f) for f in same]
    reprint = printing.refund_receipt(conn, school.desk, refund_id, tmp_path)
    assert reprint == path and reprint.read_bytes().startswith(b"%PDF")
    assert printed(conn, printing.REFUND_RECEIPT) == 2


@pytest.mark.parametrize("state", ["pending", "approved", "rejected", "cancelled"])
def test_only_a_paid_refund_has_a_receipt(conn, school, tmp_path, state):
    paid_september(school)
    refund_id = asked(school)
    if state == "approved":
        refunds.approve(conn, school.boss, refund_id)
    elif state == "rejected":
        refunds.reject(conn, school.boss, refund_id, "Non")
    elif state == "cancelled":
        refunds.withdraw(conn, school.desk, refund_id, "Erreur")
    with pytest.raises(BusinessRuleError, match=re.escape(t["refund_receipt.not_paid"])):
        printing.refund_receipt(conn, school.boss, refund_id, tmp_path)
    assert list(tmp_path.iterdir()) == []
    assert printed(conn, printing.REFUND_RECEIPT) == 0


# ----- the payment receipt never changes -----

def test_the_payment_receipt_is_left_as_it_was(conn, school, tmp_path):
    payment = paid_september(school)
    receipt_id, = conn.execute("SELECT id FROM receipts WHERE payment_id = ?",
                               (payment,)).fetchone()
    before_rows = [tuple(r) for r in conn.execute("SELECT * FROM receipts")]
    school.today.day = PAID_DAY  # both read on the same day (« Reste à payer au … »)
    before = printing.receipt_content(conn, school.boss, receipt_id)
    printing.refund_receipt(conn, school.boss, paid_out(school), tmp_path)
    after = printing.receipt_content(conn, school.boss, receipt_id)
    assert replace(after, footer=before.footer) == before  # what is owed did not move
    assert after.copy_mark == ""  # the refund's print is not the payment receipt's
    assert [tuple(r) for r in conn.execute("SELECT * FROM receipts")] == before_rows
    assert printed(conn, printing.RECEIPT) == 0


# ----- an amount in words -----

@pytest.mark.parametrize("n, words", [
    (0, "zéro"), (1, "un"), (16, "seize"), (17, "dix-sept"), (21, "vingt et un"),
    (61, "soixante et un"), (70, "soixante-dix"), (71, "soixante et onze"),
    (77, "soixante-dix-sept"), (80, "quatre-vingts"), (81, "quatre-vingt-un"),
    (91, "quatre-vingt-onze"), (99, "quatre-vingt-dix-neuf"), (100, "cent"),
    (101, "cent un"), (180, "cent quatre-vingts"), (200, "deux cents"), (201, "deux cent un"),
    (1000, "mille"), (1001, "mille un"), (2500, "deux mille cinq cents"),
    (3333, "trois mille trois cent trente-trois"), (80_000, "quatre-vingt mille"),
    (200_000, "deux cent mille"), (1_000_000, "un million"), (2_000_000, "deux millions"),
    (200_000_000, "deux cents millions"),
    (1_234_567, "un million deux cent trente-quatre mille cinq cent soixante-sept"),
])
def test_numbers_in_words(n, words):
    assert number_in_words(n) == words


def test_dinars_in_words():
    assert dzd_in_words(1) == "un dinar"
    assert dzd_in_words(6000) == "six mille dinars"
    # A whole number of millions or milliards takes « de » (REVIEW_FIXES, finding 8).
    assert dzd_in_words(1_000_000) == "un million de dinars"
    assert dzd_in_words(2_000_000) == "deux millions de dinars"
    assert dzd_in_words(200_000_000) == "deux cents millions de dinars"
    assert dzd_in_words(1_000_000_000) == "un milliard de dinars"
    assert dzd_in_words(1_002_000_000) == "un milliard deux millions de dinars"
    assert dzd_in_words(1_200_000) == "un million deux cent mille dinars"
    assert dzd_in_words(1_000_001) == "un million un dinars"


def test_the_sum_in_words_elides_de_before_un():
    """« Arrêté à la somme d'un million de dinars », never « de un » (found by step 7)."""
    assert of_dzd_in_words(2000) == "de deux mille dinars"
    assert of_dzd_in_words(1) == "d'un dinar"
    assert of_dzd_in_words(1_000_000) == "d'un million de dinars"
    assert of_dzd_in_words(1_500_000) == "d'un million cinq cent mille dinars"
    assert of_dzd_in_words(11) == "de onze dinars"
    assert of_dzd_in_words(8000) == "de huit mille dinars"
    with pytest.raises(ValueError):
        number_in_words(-1)
