from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from tadris.core.context import UserContext
from tadris.core.dates import display_date
from tadris.core.errors import BusinessRuleError
from tadris.core.permissions import allowed
from tadris.core.phones import format_phone
from tadris.domain.models import StudentContact
from tadris.i18n.fr import t
from tadris.services import contacts, students
from tadris.ui.contact_dialog import ContactDialog
from tadris.ui.pages.payments_tab import PaymentsTab
from tadris.ui.pages.refunds_tab import RefundsTab
from tadris.ui.pages.registration_tab import RegistrationTab
from tadris.ui.pages.student_attendance_tab import StudentAttendanceTab
from tadris.ui.pages.student_groups_tab import StudentGroupsTab
from tadris.ui.pages.subscriptions_tab import SubscriptionsTab
from tadris.ui.student_dialog import StudentDialog
from tadris.ui.theme.status import kind_for
from tadris.ui.widgets.common import Badge, ask, confirm, primary_button, toast, variant_button
from tadris.ui.widgets.tables import ID_ROLE, fill, item, ruled_table, selected_id


class StudentDetailView(QWidget):
    """Header card with the student's identity and actions, and one tab per topic."""

    back = Signal()

    def __init__(self, conn, ctx: UserContext, student_id: int):
        super().__init__()
        self._conn = conn
        self._ctx = ctx
        self.student_id = student_id
        self.setObjectName("page")

        self.back_button = variant_button(t["action.back"], "ghost")

        self.back_button.setObjectName("backLink")
        self.back_button.clicked.connect(self.back.emit)
        back_row = QHBoxLayout()
        back_row.addWidget(self.back_button)
        back_row.addStretch()

        self.name = QLabel()
        self.name.setObjectName("pageTitle")
        self.number = QLabel()
        self.number.setObjectName("mono")
        self.status = Badge()
        self.born = QLabel()
        self.born.setObjectName("caption")
        self.notes = QLabel()
        self.notes.setObjectName("caption")
        self.notes.setWordWrap(True)
        meta = QHBoxLayout()
        meta.setSpacing(12)
        meta.addWidget(self.number)
        meta.addWidget(self.status)
        meta.addWidget(self.born)
        meta.addStretch()
        identity = QVBoxLayout()
        identity.setSpacing(6)
        identity.addWidget(self.name)
        identity.addLayout(meta)
        identity.addWidget(self.notes)

        self.edit = QPushButton(t["action.edit"])
        self.edit.setAutoDefault(False)
        self.edit.clicked.connect(self._edit)
        self.edit.setVisible(allowed(ctx, "student.update"))
        self.deactivate = variant_button(t["student_detail.deactivate"], "danger")
        self.deactivate.clicked.connect(self._deactivate)
        self.reactivate = QPushButton(t["student_detail.reactivate"])
        self.reactivate.setAutoDefault(False)
        self.reactivate.clicked.connect(self._reactivate)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addWidget(self.edit)
        actions.addWidget(self.deactivate)
        actions.addWidget(self.reactivate)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(20, 16, 20, 16)
        card_layout.addLayout(identity, 1)
        card_layout.addLayout(actions)
        card_layout.setAlignment(actions, Qt.AlignmentFlag.AlignTop)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.registration = RegistrationTab(conn, ctx, student_id)
        self.groups = StudentGroupsTab(conn, ctx, student_id)
        self.subscriptions = SubscriptionsTab(conn, ctx, student_id)
        self.payments = PaymentsTab(conn, ctx, student_id)
        self.refunds = RefundsTab(conn, ctx, student_id)
        # Each tab shows what the others change: groups count, who may enroll, the months
        # an enrollment, a confirmed trial or a switch creates.
        self.registration.changed.connect(self.groups.refresh)
        self.groups.changed.connect(self.registration.refresh)
        self.groups.changed.connect(self.subscriptions.refresh)
        # What is owed and what was paid show on the registration, the months and payments.
        for tab in (self.registration, self.groups, self.subscriptions):
            tab.changed.connect(self.payments.refresh)
        self.payments.changed.connect(self.registration.refresh)
        self.payments.changed.connect(self.subscriptions.refresh)
        # Payments change what can be refunded; a refund lets a month or a registration be
        # cancelled.
        for tab in (self.registration, self.subscriptions):
            self.refunds.changed.connect(tab.refresh)
        for tab in (self.groups, self.subscriptions, self.payments):
            tab.changed.connect(self.refunds.refresh)
        self.tabs.addTab(self.registration, t["student_detail.tab.registration"])
        self.tabs.addTab(self.groups, t["student_detail.tab.groups"])
        self.tabs.addTab(self.subscriptions, t["student_detail.tab.subscriptions"])
        self.tabs.addTab(self.payments, t["student_detail.tab.payments"])
        self.tabs.addTab(self.refunds, t["student_detail.tab.refunds"])
        self.attendance = StudentAttendanceTab(conn, ctx, student_id)
        self.tabs.addTab(self.attendance, t["student_detail.tab.attendance"])
        self.contacts = ContactsTab(conn, ctx, student_id)
        self.contacts.changed.connect(self.refresh)
        self.tabs.addTab(self.contacts, t["student_detail.tab.contacts"])
        self.tabs.setCurrentWidget(self.registration)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 14, 24, 24)
        layout.setSpacing(16)
        self.error = error_banner()
        layout.addLayout(back_row)
        layout.addWidget(self.error)
        layout.addWidget(card)
        layout.addWidget(self.tabs, 1)
        self.refresh()

    def refresh(self) -> None:
        self.student = students.get(self._conn, self._ctx, self.student_id)
        s = self.student
        self.name.setText(s.full_name)
        self.number.setText(t["student_detail.number"].format(number=s.student_number))
        self.status.setText(t[f"student_status.{s.status}"])
        self.status.set_kind(kind_for("student", s.status))
        born = t["student_detail.born"].format(date=display_date(s.birth_date)) if s.birth_date else ""
        since = t["student_detail.since"].format(date=display_date(s.created_at))
        self.born.setText(" · ".join(part for part in (born, since) if part))
        self.notes.setText(s.notes)
        self.notes.setVisible(bool(s.notes))
        active = s.status == "active"
        self.deactivate.setVisible(active and allowed(self._ctx, "student.deactivate"))
        self.reactivate.setVisible(not active and allowed(self._ctx, "student.reactivate"))

    def _edit(self) -> None:
        dialog = StudentDialog(self._conn, self._ctx, self.student, parent=self)
        if ask(dialog):
            self.refresh()
            toast(self, t["students.updated"].format(name=self.student.full_name))

    def _deactivate(self) -> None:
        s = self.student
        if not confirm(self, t["student_detail.confirm_deactivate_title"],
                       t["student_detail.confirm_deactivate"].format(
                           name=s.full_name, number=s.student_number),
                       t["student_detail.deactivate"]):
            return
        self._run(students.deactivate, "students.deactivated")

    def _reactivate(self) -> None:
        self._run(students.reactivate, "students.reactivated")

    def _run(self, action, message_key: str) -> None:
        try:
            action(self._conn, self._ctx, self.student_id)
        except BusinessRuleError as exc:
            self.error.setText(exc.message)
            self.error.show()
            return
        self.error.hide()
        self.refresh()
        self.registration.refresh()  # an inactive student cannot be registered or enrolled
        self.groups.refresh()
        toast(self, t[message_key].format(name=self.student.full_name))


def error_banner() -> QLabel:
    """Business errors raised by a page action (not in a dialog) show above the content."""
    banner = QLabel()
    banner.setObjectName("errorBanner")
    banner.setWordWrap(True)
    banner.hide()
    return banner


class ContactsTab(QWidget):
    changed = Signal()

    def __init__(self, conn, ctx: UserContext, student_id: int):
        super().__init__()
        self._conn = conn
        self._ctx = ctx
        self._student_id = student_id
        self._contacts: dict[int, StudentContact] = {}
        can_edit = allowed(ctx, "student.update")

        self.error = error_banner()
        self.add = primary_button(t["contacts.add"])
        self.add.setDefault(False)
        self.add.clicked.connect(self._add)
        self.edit = QPushButton(t["action.edit"])
        self.edit.setAutoDefault(False)
        self.edit.clicked.connect(self._edit)
        self.make_main = QPushButton(t["contacts.make_main"])
        self.make_main.setAutoDefault(False)
        self.make_main.clicked.connect(self._make_main)
        self.unlink = variant_button(t["contacts.unlink"], "danger")
        self.unlink.clicked.connect(self._unlink)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        for button in (self.edit, self.make_main, self.unlink):
            toolbar.addWidget(button)
            button.setVisible(can_edit)
        toolbar.addStretch()
        toolbar.addWidget(self.add)
        self.add.setVisible(can_edit)

        self.table = ruled_table([
            t["contacts.col.name"],
            t["contacts.col.relation"],
            t["contacts.col.phone"],
            t["contacts.col.phone_2"],
            t["contacts.col.sms"],
            t["contacts.col.main"],
        ])
        self.table.itemSelectionChanged.connect(self._update_buttons)
        if can_edit:
            self.table.activated.connect(lambda _index: self._edit())
        self.empty = QLabel(t["contacts.empty"])
        self.empty.setObjectName("emptyState")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 16, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self.error)
        layout.addLayout(toolbar)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.empty)
        layout.addStretch(0)
        self.refresh()

    def refresh(self) -> None:
        listed = contacts.list_for_student(self._conn, self._ctx, self._student_id)
        self._contacts = {c.contact_id: c for c in listed}
        fill(self.table, [self._cells(c) for c in listed])
        self.table.setVisible(bool(listed))
        self.empty.setVisible(not listed)
        self._update_buttons()

    @staticmethod
    def _cells(c: StudentContact) -> list:
        sms = t["contacts.sms_yes" if c.can_receive_sms else "contacts.sms_no"]
        main = item(t["contacts.main_badge"], kind="info") if c.is_main else item("")
        return [
            item(c.full_name, item_id=c.contact_id),
            item(c.relation),
            item(format_phone(c.phone), mono=True),
            item(format_phone(c.phone_2), mono=True),
            item(sms),
            main,
        ]

    def selected(self) -> StudentContact | None:
        contact_id = selected_id(self.table)
        return None if contact_id is None else self._contacts.get(contact_id)

    def select(self, contact_id: int) -> None:
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).data(ID_ROLE) == contact_id:
                self.table.selectRow(r)
                return

    def _update_buttons(self) -> None:
        contact = self.selected()
        self.edit.setEnabled(contact is not None)
        self.make_main.setEnabled(contact is not None and not contact.is_main)
        self.unlink.setEnabled(contact is not None)

    def _done(self, message: str, contact_id: int | None = None) -> None:
        self.error.hide()
        self.refresh()
        if contact_id is not None:
            self.select(contact_id)
        self.changed.emit()
        toast(self, message)

    def _add(self) -> None:
        dialog = ContactDialog(self._conn, self._ctx, self._student_id,
                               is_first=not self._contacts, parent=self)
        if ask(dialog):
            self._done(t["contacts.added"].format(name=dialog.saved_name()), dialog.contact_id)

    def _edit(self) -> None:
        contact = self.selected()
        if contact is None:
            return
        dialog = ContactDialog(self._conn, self._ctx, self._student_id, contact, parent=self)
        if ask(dialog):
            self._done(t["contacts.updated"].format(name=dialog.saved_name()), contact.contact_id)

    def _make_main(self) -> None:
        contact = self.selected()
        if contact is None:
            return
        try:
            contacts.set_main(self._conn, self._ctx, self._student_id, contact.contact_id)
        except BusinessRuleError as exc:
            self._show_error(exc.message)
            return
        self._done(t["contacts.main_set"].format(name=contact.full_name), contact.contact_id)

    def _unlink(self) -> None:
        contact = self.selected()
        if contact is None:
            return
        student = students.get(self._conn, self._ctx, self._student_id)
        if not confirm(self, t["contacts.confirm_unlink_title"],
                       t["contacts.confirm_unlink"].format(contact=contact.full_name,
                                                           student=student.full_name),
                       t["contacts.unlink"]):
            return
        try:
            contacts.unlink(self._conn, self._ctx, self._student_id, contact.contact_id)
        except BusinessRuleError as exc:
            self._show_error(exc.message)
            return
        self._done(t["contacts.unlinked"].format(name=contact.full_name))

    def _show_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.show()
