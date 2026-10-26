"""« Encaisser » from the dashboard and the Paiements page, without opening the student's
page first: the payment dialog, a toast, and the receipt opened to be printed (it is handed
over at the desk)."""

from PySide6.QtWidgets import QMessageBox, QWidget

from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError
from tadris.core.money import format_dzd
from tadris.core.permissions import allowed
from tadris.domain.models import Payment
from tadris.i18n.fr import t
from tadris.services import payments, printing, students
from tadris.ui.payment_dialogs import PaymentDialog
from tadris.ui.student_picker import StudentPicker
from tadris.ui.widgets import common
from tadris.ui.widgets.common import ask, toast


def collect(parent: QWidget, conn, ctx: UserContext, student_id: int,
            preselect: list[int] | None = None) -> Payment | None:
    """preselect: the charge ids ticked from the start (e.g. one group's months); by default
    the amount due now, oldest lines first. None when the dialog is closed without paying."""
    student = students.get(conn, ctx, student_id)
    dialog = PaymentDialog(conn, ctx, student, preselect=preselect, parent=parent)
    if not ask(dialog):
        return None
    p = payments.get(conn, ctx, dialog.payment_id)
    toast(parent, t["payments_tab.received"].format(amount=format_dzd(p.amount),
                                                    number=p.receipt_number))
    if p.receipt_id is not None and allowed(ctx, "print.document"):
        try:
            common.open_document(printing.receipt(conn, ctx, p.receipt_id))
        except (BusinessRuleError, OSError):
            QMessageBox.warning(parent, t["app.name"], t["print.failed"])
    return p


def pick_and_collect(parent: QWidget, conn, ctx: UserContext) -> Payment | None:
    """« Encaisser un paiement »: choose the student, then pay."""
    picker = StudentPicker(conn, ctx, parent=parent)
    if not ask(picker):
        return None
    return collect(parent, conn, ctx, picker.student_id)


def collect_many(parent: QWidget, conn, ctx: UserContext,
                 students: list[tuple[int, list[int] | None]]) -> int:
    """« Encaisser » on several lines: one payment per student (each with its own receipt),
    one after the other; closing a payment dialog stops there. Returns how many were
    taken. `students`: (student id, the charge ids to tick, or None)."""
    taken = 0
    for student_id, preselect in students:
        if collect(parent, conn, ctx, student_id, preselect) is None:
            break
        taken += 1
    return taken
