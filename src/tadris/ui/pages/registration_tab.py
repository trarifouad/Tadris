"""The student's Inscription tab: the registration of the open year and the past ones."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from tadris.core.context import UserContext
from tadris.core.dates import display_date
from tadris.core.money import format_dzd
from tadris.core.permissions import allowed
from tadris.domain.models import Registration, SchoolYear
from tadris.i18n.fr import t
from tadris.services import registrations, school_years, students
from tadris.ui.registration_dialogs import (
    CancelRegistrationDialog,
    ChangeLevelDialog,
    RegistrationDialog,
)
from tadris.ui.theme.status import kind_for
from tadris.ui.widgets.common import Badge, PageBanner, ask, primary_button, toast, variant_button
from tadris.ui.widgets.tables import CENTER, fill, item, ruled_table


class RegistrationTab(QWidget):
    changed = Signal()

    def __init__(self, conn, ctx: UserContext, student_id: int):
        super().__init__()
        self._compact = False
        self._conn = conn
        self._ctx = ctx
        self._student_id = student_id
        self.year: SchoolYear | None = None
        self.current: Registration | None = None

        self.error = PageBanner()
        self.register = primary_button(t["registration_tab.register"])
        self.register.setDefault(False)
        self.register.clicked.connect(self._register)
        self.change_level = QPushButton(t["registration_tab.change_level"])
        self.change_level.setAutoDefault(False)
        self.change_level.clicked.connect(self._change_level)
        self.cancel = variant_button(t["registration_tab.cancel"], "danger")
        self.cancel.clicked.connect(self._cancel)

        # The open year's registration, as a card of label / value pairs.
        self.title = QLabel()
        self.title.setObjectName("sectionTitle")
        self.status = Badge()
        self.level = QLabel()
        self.fee = QLabel()
        self.due = QLabel()
        self.registered_on = QLabel()
        self.groups = QLabel()
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(8)
        for r, (key, value) in enumerate((("level", self.level), ("fee", self.fee),
                                          ("due", self.due), ("date", self.registered_on),
                                          ("groups", self.groups))):
            label = QLabel(t[f"registration_tab.{key}"])
            label.setObjectName("fieldLabel")
            grid.addWidget(label, r, 0)
            grid.addWidget(value, r, 1)
        grid.setColumnStretch(2, 1)
        self.grid = QWidget()
        self.grid.setLayout(grid)
        grid.setContentsMargins(0, 0, 0, 0)
        # One line instead of the grid when the tab sits in a card (make_compact()).
        self.summary = QLabel()
        self.summary.setObjectName("caption")
        self.summary.setWordWrap(True)
        self.summary.hide()
        heading = QHBoxLayout()
        heading.setSpacing(12)
        heading.addWidget(self.title)
        heading.addWidget(self.status)
        heading.addStretch()
        heading.addWidget(self.change_level)
        heading.addWidget(self.cancel)
        self.card = QFrame()
        self.card.setObjectName("card")
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(20, 16, 20, 16)
        card_layout.setSpacing(12)
        card_layout.addLayout(heading)
        card_layout.addWidget(self.grid)
        card_layout.addWidget(self.summary)

        # Not registered for the open year (or no open year): a message and the button.
        self.empty = QLabel()
        self.empty.setObjectName("emptyState")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        empty_row = QHBoxLayout()
        self._empty_row = empty_row
        empty_row.addStretch()
        empty_row.addWidget(self.register)
        empty_row.addStretch()

        self.history_title = QLabel(t["registration_tab.history"])
        self.history_title.setObjectName("sectionTitle")
        self.history = ruled_table([t["registration_tab.col.year"],
                                    t["registration_tab.col.level"],
                                    t["registration_tab.col.fee"],
                                    t["registration_tab.col.status"],
                                    t["registration_tab.col.date"]])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 16, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self.error)
        layout.addWidget(self.card)
        layout.addWidget(self.empty)
        layout.addLayout(empty_row)
        layout.addSpacing(8)
        layout.addWidget(self.history_title)
        layout.addWidget(self.history, 1)
        layout.addStretch(0)
        self.refresh()

    def refresh(self) -> None:
        student = students.get(self._conn, self._ctx, self._student_id)
        self.year = school_years.current(self._conn, self._ctx)
        self.current = registrations.current(self._conn, self._ctx, self._student_id)
        reg = self.current
        self.card.setVisible(reg is not None)
        if reg is not None:
            self.title.setText(t["registration_tab.title"].format(label=reg.year_label))
            self.status.setText(t["registration_status.active"])
            # On the student page, green is for the student's and the groups' status only.
            self.status.set_kind("neutral" if self._compact else kind_for("registration",
                                                                           "active"))
            self.level.setText(reg.level)
            self.fee.setText(format_dzd(reg.fee_amount))
            self.due.setText(format_dzd(reg.fee_due))
            self.registered_on.setText(display_date(reg.registered_at))
            self.groups.setText(str(reg.live_enrollments))
            self.summary.setText(t["registration_tab.summary"].format(
                level=reg.level, fee=format_dzd(reg.fee_amount), due=format_dzd(reg.fee_due),
                date=display_date(reg.registered_at)))
        can_register = allowed(self._ctx, "registration.create")
        in_year = reg is not None and reg.live_enrollments == 0
        self.change_level.setVisible(in_year and can_register)
        self.cancel.setVisible(in_year and allowed(self._ctx, "registration.cancel"))

        if self.year is None:
            message = t["registration.no_open_year"]
        elif student.status != "active":
            message = t["registration_tab.student_inactive"]
        else:
            message = t["registration_tab.not_registered"].format(label=self.year.label)
        self.empty.setText(message)
        self.empty.setVisible(reg is None)
        self.register.setVisible(reg is None and self.year is not None
                                 and student.status == "active" and can_register)
        if self.year is not None:
            self.register.setText(t["registration_tab.register"].format(label=self.year.label))

        past = [r for r in registrations.for_student(self._conn, self._ctx, self._student_id)
                if reg is None or r.id != reg.id]
        fill(self.history, [self._cells(r) for r in past])
        self.history.setVisible(bool(past))
        self.history_title.setVisible(bool(past))

    def make_compact(self) -> None:
        """For a card of the student page (which gives it its heading): no card of its own,
        one line instead of the grid, small buttons, the past years only when there are
        some."""
        from tadris.ui.widgets.compact import compact_empty, fit_height, small

        self._compact = True

        self.layout().setContentsMargins(0, 0, 0, 0)
        self.layout().setSpacing(8)
        self.card.setObjectName("")
        self.card.layout().setContentsMargins(0, 0, 0, 0)
        self.card.layout().setSpacing(4)
        self.title.setObjectName("rowTitle")
        self.grid.hide()
        self.summary.show()
        for button in (self.register, self.change_level, self.cancel):
            small(button)
        compact_empty(self.empty)
        self._empty_row.takeAt(0)  # the button on the left, under its line
        self.history_title.setObjectName("cardSection")
        self.history_title.setText(self.history_title.text().upper())
        fit_height(self.history, 3)
        self.refresh()

    @staticmethod
    def _cells(r: Registration) -> list:
        return [
            item(r.year_label, item_id=r.id),
            item(r.level),
            item(format_dzd(r.fee_amount), align=CENTER, mono=True),
            item(t[f"registration_status.{r.status}"], kind=kind_for("registration", r.status)),
            item(display_date(r.registered_at)),
        ]

    def _done(self, message: str) -> None:
        self.error.clear_error()
        self.refresh()
        self.changed.emit()
        toast(self, message)

    def _register(self) -> None:
        student = students.get(self._conn, self._ctx, self._student_id)
        if self.year is None:
            return
        dialog = RegistrationDialog(self._conn, self._ctx, student, self.year, parent=self)
        if ask(dialog):
            self._done(t["registration_tab.registered"].format(name=student.full_name,
                                                               label=self.year.label))

    def _change_level(self) -> None:
        if self.current is None:
            return
        if ask(ChangeLevelDialog(self._conn, self._ctx, self.current, parent=self)):
            self._done(t["registration_tab.level_changed"])

    def _cancel(self) -> None:
        if self.current is None:
            return
        student = students.get(self._conn, self._ctx, self._student_id)
        dialog = CancelRegistrationDialog(self._conn, self._ctx, self.current, student,
                                          parent=self)
        if ask(dialog):
            self._done(t["registration_tab.cancelled"].format(name=student.full_name))
