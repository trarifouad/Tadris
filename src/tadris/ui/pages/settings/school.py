"""Paramètres → École: the school as documents and the desk show it, one card per part
(identity, opening hours, default prices, receipt lines), each with « Modifier » opening its
own small dialog."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QLabel, QVBoxLayout, QWidget

from tadris.core.context import UserContext
from tadris.core.money import format_dzd
from tadris.i18n.fr import t
from tadris.services import debt, groups, registrations, settings
from tadris.ui.settings_dialogs import (
    DefaultsDialog,
    HoursDialog,
    IdentityDialog,
    ReceiptLinesDialog,
)
from tadris.ui.widgets.common import ask, toast
from tadris.ui.widgets.compact import summary_card
from tadris.ui.widgets.forms import caption


def value(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("summaryValue")
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


def pairs(names: list[str]) -> tuple[QGridLayout, list[QLabel]]:
    """Names on the left (muted), their values on the right: the grid and the values."""
    grid = QGridLayout()
    grid.setHorizontalSpacing(24)
    grid.setVerticalSpacing(6)
    values = []
    for r, name in enumerate(names):
        label = caption(name)
        grid.addWidget(label, r, 0, Qt.AlignmentFlag.AlignTop)
        shown = value()
        grid.addWidget(shown, r, 1)
        values.append(shown)
    grid.setColumnStretch(1, 1)
    return grid, values


class SchoolSection(QWidget):
    def __init__(self, conn, ctx: UserContext):
        super().__init__()
        self._conn, self._ctx = conn, ctx

        identity, body, self.edit_identity = summary_card(t["school_card.identity"],
                                                          t["action.edit"])
        self.name = value()
        self.name.setObjectName("summaryTitle")
        self.contact = caption()
        self.contact.setWordWrap(True)
        body.addWidget(self.name)
        body.addWidget(self.contact)

        hours, body, self.edit_hours = summary_card(t["school.hours"], t["action.edit"])
        self.hours = value()
        hours_note = caption(t["school.hours_caption"])
        hours_note.setWordWrap(True)
        body.addWidget(self.hours)
        body.addWidget(hours_note)

        defaults, body, self.edit_defaults = summary_card(t["school.fees"], t["action.edit"])
        grid, (self.fee, self.group_price, self.debt_warning) = pairs(
            [t["school_card.fee"], t["school_card.group_price"], t["school_card.debt_warning"]])
        body.addLayout(grid)

        receipts, body, self.edit_receipts = summary_card(t["school.receipts"],
                                                          t["action.edit"])
        grid, (self.header, self.footer) = pairs(
            [t["school_card.header"], t["school_card.footer"]])
        self.no_lines = caption(t["school_card.no_lines"])
        self.no_lines.setWordWrap(True)
        body.addLayout(grid)
        body.addWidget(self.no_lines)
        self._receipt_grid = grid

        for button, dialog in ((self.edit_identity, IdentityDialog),
                               (self.edit_hours, HoursDialog),
                               (self.edit_defaults, DefaultsDialog),
                               (self.edit_receipts, ReceiptLinesDialog)):
            button.clicked.connect(lambda _on=False, d=dialog: self._edit(d))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        for card in (identity, hours, defaults, receipts):
            layout.addWidget(card)
        self.refresh()

    def refresh(self) -> None:
        self.name.setText(settings.get(self._conn, "school.name", "") or "—")
        contact = [part for part in (settings.get(self._conn, "school.phone", ""),
                                     settings.get(self._conn, "school.address", "")) if part]
        self.contact.setText(" · ".join(contact) if contact else t["school_card.no_contact"])
        opens_at, closes_at = settings.school_hours(self._conn)
        self.hours.setText(t["school_card.hours"].format(opens=opens_at, closes=closes_at))
        self.fee.setText(format_dzd(registrations.default_fee(self._conn)))
        price = groups.default_price(self._conn)
        self.group_price.setText(format_dzd(price) if price else t["school_card.none"])
        threshold = debt.warning_threshold(self._conn)
        self.debt_warning.setText(t["school_card.from"].format(amount=format_dzd(threshold))
                                  if threshold else t["school_card.off"])
        header = settings.get(self._conn, "receipt.header", "")
        footer = settings.get(self._conn, "receipt.footer", "")
        self.header.setText(header or "—")
        self.footer.setText(footer or "—")
        lines = bool(header or footer)
        for i in range(self._receipt_grid.count()):
            self._receipt_grid.itemAt(i).widget().setVisible(lines)
        self.no_lines.setVisible(not lines)

    def _edit(self, dialog_class) -> None:
        if ask(dialog_class(self._conn, self._ctx, parent=self)):
            self.refresh()
            toast(self, t["school.saved"])
