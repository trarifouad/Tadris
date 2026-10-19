"""The student's Remboursements tab: money handed back, with its actions."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from tadris.core.context import UserContext
from tadris.core.permissions import allowed
from tadris.i18n.fr import t
from tadris.services import refunds
from tadris.ui.pages.refunds_section import RefundsSection
from tadris.ui.refund_dialogs import RefundRequestDialog
from tadris.ui.widgets.common import ask, primary_button, toast


class RefundsTab(QWidget):
    changed = Signal()

    def __init__(self, conn, ctx: UserContext, student_id: int):
        super().__init__()
        self._conn = conn
        self._ctx = ctx
        self._student_id = student_id
        self.refunds = RefundsSection(conn, ctx,
                                      lambda: refunds.for_student(conn, ctx, student_id),
                                      show_student=False, empty_text=t["refunds.empty"])
        self.request = self.refunds.add_button(primary_button(t["refunds.request"]), end=True)
        self.request.setDefault(False)
        self.request.clicked.connect(self._request)
        self.request.setVisible(allowed(ctx, "refund.request"))
        self.refunds.changed.connect(self.changed.emit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 16, 0, 0)
        layout.addWidget(self.refunds)
        self.refresh()

    def refresh(self) -> None:
        self.refunds.refresh()

    def _request(self) -> None:
        dialog = RefundRequestDialog(self._conn, self._ctx, self._student_id, parent=self)
        if ask(dialog):
            self.refresh()
            self.refunds.select_id(dialog.refund_id)
            self.changed.emit()
            toast(self, t["refunds.requested"])
