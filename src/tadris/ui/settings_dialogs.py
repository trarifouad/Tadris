"""Paramètres → École: one dialog per card, each saving its own part (the school's identity,
its opening hours, the default prices, the receipts' extra lines)."""

from PySide6.QtWidgets import QLineEdit, QWidget

from tadris.core.context import UserContext
from tadris.i18n.fr import t
from tadris.services import debt, groups, registrations, settings
from tadris.ui.widgets.common import labeled
from tadris.ui.widgets.forms import FormDialog, caption, row
from tadris.ui.widgets.inputs import money_edit, read_money, time_combo

FORM_WIDTH = 640


def _note(text: str):
    note = caption(text)
    note.setWordWrap(True)
    return note


class IdentityDialog(FormDialog):
    """Name (required), phone and address: printed at the top of every document."""

    def __init__(self, conn, ctx: UserContext, parent=None):
        super().__init__(t["school_dialog.identity"], t["action.save"], width=FORM_WIDTH,
                         parent=parent)
        self._conn, self._ctx = conn, ctx
        self.name = QLineEdit(settings.get(conn, "school.name", ""))
        self.phone = QLineEdit(settings.get(conn, "school.phone", ""))
        self.address = QLineEdit(settings.get(conn, "school.address", ""))
        self.add(_note(t["school.caption"]))
        self.add(labeled(t["school.name"], self.name, required=True))
        self.add(row(labeled(t["school.phone"], self.phone),
                     labeled(t["school.address"], self.address)))
        self.finish(self.name)

    def save(self) -> None:
        settings.save_identity(self._conn, self._ctx, self.name.text(), self.phone.text(),
                               self.address.text())


class HoursDialog(FormDialog):
    """When the school opens and closes, every day: the timetable's slots fit inside."""

    def __init__(self, conn, ctx: UserContext, parent=None):
        super().__init__(t["school.hours"], t["action.save"], parent=parent)
        self._conn, self._ctx = conn, ctx
        opens_at, closes_at = settings.school_hours(conn)
        self.opens_at = time_combo(opens_at)
        self.closes_at = time_combo(closes_at)
        self.add(_note(t["school.hours_caption"]))
        self.add(row(labeled(t["school.opens_at"], self.opens_at, required=True),
                     labeled(t["school.closes_at"], self.closes_at, required=True)))
        self.finish(self.opens_at)

    def save(self) -> None:
        settings.set_school_hours(self._conn, self._ctx, self.opens_at.currentText(),
                                  self.closes_at.currentText())


class DefaultsDialog(FormDialog):
    """The registration fee and the price of a new group proposed by default, and the debt
    warning threshold (empty: none)."""

    def __init__(self, conn, ctx: UserContext, parent=None):
        super().__init__(t["school.fees"], t["action.save"], width=FORM_WIDTH, parent=parent)
        self._conn, self._ctx = conn, ctx
        self.registration_fee = money_edit(registrations.default_fee(conn))
        price = groups.default_price(conn)
        self.group_price = money_edit(price or None)
        self.group_price.setPlaceholderText(t["school.group_price_off"])
        threshold = debt.warning_threshold(conn)
        self.debt_warning = money_edit(threshold or None)
        self.debt_warning.setPlaceholderText(t["school.debt_warning_off"])
        self.add(_note(t["school.fees_caption"]))
        self.add(row(labeled(t["school.registration_fee"], self.registration_fee),
                     labeled(t["school.group_price"], self.group_price)))
        self.add(row(labeled(t["school.debt_warning"], self.debt_warning), QWidget()))
        self.finish(self.registration_fee)

    def save(self) -> None:
        settings.save_defaults(self._conn, self._ctx,
                               read_money(self.registration_fee, empty=0),
                               read_money(self.group_price, empty=0),
                               read_money(self.debt_warning, empty=0))


class ReceiptLinesDialog(FormDialog):
    """Two optional lines: one under the school's address, one at the foot of receipts."""

    def __init__(self, conn, ctx: UserContext, parent=None):
        super().__init__(t["school.receipts"], t["action.save"], width=FORM_WIDTH,
                         parent=parent)
        self._conn, self._ctx = conn, ctx
        self.receipt_header = QLineEdit(settings.get(conn, "receipt.header", ""))
        self.receipt_header.setPlaceholderText(t["school.receipt_header_hint"])
        self.receipt_header.setMaxLength(settings.RECEIPT_LINE_MAX)
        self.receipt_footer = QLineEdit(settings.get(conn, "receipt.footer", ""))
        self.receipt_footer.setPlaceholderText(t["school.receipt_footer_hint"])
        self.receipt_footer.setMaxLength(settings.RECEIPT_LINE_MAX)
        self.add(_note(t["school.receipts_caption"]))
        self.add(labeled(t["school.receipt_header"], self.receipt_header))
        self.add(labeled(t["school.receipt_footer"], self.receipt_footer))
        self.finish(self.receipt_header)

    def save(self) -> None:
        settings.save_receipt_lines(self._conn, self._ctx, self.receipt_header.text(),
                                    self.receipt_footer.text())
