from datetime import date

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.dates import display_date
from tadris.core.errors import BusinessRuleError
from tadris.core.permissions import allowed
from tadris.core.phones import format_phone
from tadris.domain.models import StudentContact
from tadris.i18n.fr import t
from tadris.services import (
    attendance,
    contacts,
    debt,
    enrollments,
    payments,
    registrations,
    students,
    subscriptions,
)
from tadris.ui.contact_dialog import ContactDialog
from tadris.ui.pages.payments_tab import PaymentsTab
from tadris.ui.pages.registration_tab import RegistrationTab
from tadris.ui.pages.student_attendance_tab import StudentAttendanceTab
from tadris.ui.pages.student_groups_tab import StudentGroupsTab
from tadris.ui.pages.student_overview import GroupLines, link_button
from tadris.ui.pages.subscriptions_tab import SubscriptionsTab
from tadris.ui.student_dialog import StudentDialog
from tadris.ui.theme import icon
from tadris.ui.theme.status import kind_for
from tadris.ui.widgets.common import Badge, ask, confirm, primary_button, toast, variant_button
from tadris.ui.widgets.compact import (
    Segments,
    compact_empty,
    compact_list,
    fit_height,
    follow_current,
    heading,
    row_actions_below,
    share_width,
    small,
)
from tadris.ui.widgets.forms import SectionWindow
from tadris.ui.widgets.tables import ID_ROLE, fill, item, ruled_table, selected_id


class StudentDetailView(QWidget):
    """Three cards: the student (identity, registration, contacts) and the study side by
    side, the money under them, the whole page scrolling. Only the essentials stay on the
    page: the study is one line per group (its month, its attendance) and the money what is
    left to pay and the latest receipts. The whole lists (groups with their history, every
    session, every month, every payment) open in a window, with all their actions."""

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
        self.notes = QLabel()
        self.notes.setObjectName("caption")
        self.notes.setWordWrap(True)
        meta = QHBoxLayout()
        meta.setSpacing(12)
        meta.addWidget(self.number)
        meta.addWidget(self.status)
        meta.addStretch()
        identity = QVBoxLayout()
        identity.setSpacing(6)
        identity.addWidget(self.name)
        identity.addLayout(meta)
        identity.addWidget(self.notes)

        # Behind « ⋯ »: the details (birth date, age, file created) in a small window, then
        # the rare actions, out of reach of a stray click (then a confirmation).
        self.info = QAction(t["student_detail.info"], self)
        self.info.triggered.connect(self._show_info)
        self.edit = QAction(t["action.edit"], self)
        self.edit.triggered.connect(self._edit)
        self.edit.setVisible(allowed(ctx, "student.update"))
        self.deactivate = QAction(t["student_detail.deactivate"], self)
        self.deactivate.triggered.connect(self._deactivate)
        self.reactivate = QAction(t["student_detail.reactivate"], self)
        self.reactivate.triggered.connect(self._reactivate)
        self.more_menu = QMenu(self)
        self.more_menu.addAction(self.info)
        self.more_menu.addAction(self.edit)
        self.more_menu.addAction(self.deactivate)
        self.more_menu.addAction(self.reactivate)
        self.more = QToolButton()
        self.more.setObjectName("moreButton")
        self.more.setIcon(icon("ellipsis", size=40))
        self.more.setIconSize(QSize(20, 20))
        self.more.setToolTip(t["student_detail.more"])
        self.more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.more.setMenu(self.more_menu)

        # Each section keeps its own logic and dialogs; the cards below only arrange them.
        self.registration = RegistrationTab(conn, ctx, student_id)
        self.groups = StudentGroupsTab(conn, ctx, student_id)
        self.subscriptions = SubscriptionsTab(conn, ctx, student_id)
        self.payments = PaymentsTab(conn, ctx, student_id)
        self.attendance = StudentAttendanceTab(conn, ctx, student_id)
        self.contacts = ContactsTab(conn, ctx, student_id)
        self.all_payments = PaymentsTab(conn, ctx, student_id)  # the window's, whole
        # Each section shows what the others change: groups count, who may enroll, the
        # months an enrollment, a confirmed trial or a switch creates.
        self.registration.changed.connect(self.groups.refresh)
        self.groups.changed.connect(self.registration.refresh)
        self.groups.changed.connect(self.subscriptions.refresh)
        # What is owed and what was paid show on the registration, the months and payments.
        for section in (self.registration, self.groups, self.subscriptions):
            section.changed.connect(self.payments.refresh)
        self.payments.changed.connect(self.registration.refresh)
        self.payments.changed.connect(self.subscriptions.refresh)
        self.all_payments.changed.connect(self.payments.refresh)
        self.all_payments.changed.connect(self.registration.refresh)
        self.all_payments.changed.connect(self.subscriptions.refresh)
        self.contacts.changed.connect(self.refresh)
        # The study card's lines follow every change.
        for section in (self.registration, self.groups, self.subscriptions, self.payments,
                        self.all_payments):
            section.changed.connect(self.refresh_overview)

        self.windows = {
            "groups": SectionWindow(t["overview.window.groups"], self.groups, self),
            "sessions": SectionWindow(t["overview.window.sessions"], self.attendance, self),
            "subscriptions": SectionWindow(t["overview.window.subscriptions"],
                                           self.subscriptions, self),
            "payments": SectionWindow(t["overview.window.payments"], self.all_payments,
                                      self),
        }

        top = QHBoxLayout()
        top.setSpacing(16)
        for card, stretch in ((self._student_card(identity), 1), (self._study_card(), 1)):
            share_width(card)
            top.addWidget(card, stretch)
        content = QWidget()
        content.setObjectName("page")
        column = QVBoxLayout(content)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(16)
        column.addLayout(top)
        column.addWidget(self._money_card())
        column.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 14, 24, 16)
        layout.setSpacing(12)
        self.error = error_banner()
        layout.addLayout(back_row)
        layout.addWidget(self.error)
        layout.addWidget(scroll, 1)
        self.refresh()
        self.refresh_overview()

    # ----- the three cards -----

    def _student_card(self, identity) -> QFrame:
        """Who the student is: identity, this year's registration, contacts."""
        card = section_card()
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addLayout(identity, 1)
        head.addWidget(self.more, 0, Qt.AlignmentFlag.AlignTop)
        body = card.layout()
        body.addLayout(head)
        self.registration.make_compact()
        # Its own height only: the card's room left over goes below the contacts.
        self.registration.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.contacts.make_compact()
        for title, section in ((t["student_detail.tab.registration"], self.registration),
                               (None, self.contacts)):
            body.addWidget(rule())
            if title is not None:
                body.addWidget(heading(title))
            body.addWidget(section)
        body.addStretch()
        return card

    def _money_card(self) -> QFrame:
        """Everything about money: what is late, due soon and to come, and « Encaisser »;
        then the lines left to pay (grouped by urgency, ticked to pay) or the latest
        receipts."""
        card = section_card()
        body = card.layout()
        payments = self.payments
        title = QLabel(t["student_detail.money"])
        title.setObjectName("sectionTitle")
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(title)
        head.addStretch()
        head.addWidget(small(payments.receive))
        body.addLayout(head)
        compact_list(payments.history, None, 3)
        # The view's name is the segment's: the list's own title goes.
        first = payments.history.toolbar.itemAt(0).widget()
        if isinstance(first, QLabel):
            first.hide()
        self.money_views = QStackedWidget()
        for view in (payments.dues, payments.history):
            self.money_views.addWidget(view)
        payments.hide()  # its parts are in this card
        self.money_tabs = Segments([t["student_detail.money.due"],
                                    t["student_detail.money.receipts"]])
        self.money_tabs.changed.connect(self.money_views.setCurrentIndex)
        follow_current(self.money_views)
        self.open_payments = link_button()
        self.open_payments.clicked.connect(lambda: self.open_window("payments"))
        switch = QHBoxLayout()
        switch.addWidget(self.money_tabs)
        switch.addStretch()
        switch.addWidget(self.open_payments)
        body.addLayout(switch)
        body.addWidget(self.money_views)
        body.addStretch()
        return card

    def _study_card(self) -> QFrame:
        """The year's study at a glance: one line per group (its month, its attendance), or
        an empty state with the next step; at the foot, the groups with their history,
        every session and every month, each opening in a window (only when there is
        something in it)."""
        card = section_card()
        title = QLabel(t["student_detail.study"])
        title.setObjectName("sectionTitle")
        # « Inscrire dans un groupe » here does what the groups list's own button does.
        self.enroll = small(primary_button(t["student_groups.enroll"]))
        self.enroll.setDefault(False)
        self.enroll.clicked.connect(self.groups.enroll.click)
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(title)
        head.addStretch()
        head.addWidget(self.enroll)
        self.group_lines = GroupLines()
        self._empty_step: str | None = None  # what the empty state's button does
        self.group_lines.empty.action.clicked.connect(self._first_step)
        self.open_groups = link_button()
        self.open_sessions = link_button()
        self.open_subscriptions = link_button()
        links = QHBoxLayout()
        links.setSpacing(20)
        for key, button in (("groups", self.open_groups), ("sessions", self.open_sessions),
                            ("subscriptions", self.open_subscriptions)):
            button.clicked.connect(lambda _checked=False, k=key: self.open_window(k))
            links.addWidget(button)
        links.addStretch()
        # The links sit at the card's foot, under its lines (or its empty state).
        self.study_foot = QWidget()
        foot = QVBoxLayout(self.study_foot)
        foot.setContentsMargins(0, 0, 0, 0)
        foot.setSpacing(12)
        foot.addWidget(rule())
        foot.addLayout(links)
        body = card.layout()
        body.addLayout(head)
        body.addWidget(self.group_lines, 1)
        body.addWidget(self.study_foot)
        return card

    def refresh_overview(self) -> None:
        """The study card's lines and the counts on the links to the whole lists."""
        today = dates.iso(dates.today())
        groups = enrollments.for_student(self._conn, self._ctx, self.student_id)
        months = subscriptions.for_student(self._conn, self._ctx, self.student_id)
        marks = attendance.summary_by_enrollment(self._conn, self._ctx, self.student_id)
        left = debt.left_for_student(self._conn, self._ctx, self.student_id)
        self.group_lines.set_lines(groups, months, marks, today, left)
        counts = {"groups": len(groups), "sessions": sum(s.total for s in marks.values()),
                  "subscriptions": len(months)}
        # A link to an empty list says « (0) » for nothing: it goes, and the foot with them.
        for key, button in (("groups", self.open_groups), ("sessions", self.open_sessions),
                            ("subscriptions", self.open_subscriptions)):
            button.setText(t[f"overview.{key}"].format(count=counts[key]))
            button.setVisible(counts[key] > 0)
        self.study_foot.setVisible(any(counts.values()))
        self.open_payments.setText(t["overview.payments"].format(
            count=payments.count_for_student(self._conn, self._ctx, self.student_id)))
        # Next to the tiles, « Inscrire dans un groupe » stays in the card's head; without
        # any tile, the empty state offers it (one main button per card).
        can_enroll = not self.groups.enroll.isHidden()
        self.enroll.setVisible(can_enroll and bool(self.group_lines.lines))
        self.enroll.setEnabled(self.groups.enroll.isEnabled())
        if not self.group_lines.lines:
            self._show_empty(had_groups=bool(groups), can_enroll=can_enroll)

    def _show_empty(self, had_groups: bool, can_enroll: bool) -> None:
        """Why the student is in no group, and « Inscrire dans un groupe » when it is the next
        step. Not registered for the year: the student card's own button comes first, so
        the text points to it; deactivated: reactivated from « ⋯ »."""
        student = students.get(self._conn, self._ctx, self.student_id)
        registered = registrations.current(self._conn, self._ctx, self.student_id) is not None
        if student.status != "active":
            case, step = "inactive", None
        elif not registered:
            case, step = "not_registered", None
        elif had_groups:
            case, step = "left", "enroll" if can_enroll else None
        else:
            case, step = "none", "enroll" if can_enroll else None
        self._empty_step = step
        text = t[f"overview.empty.{case}.text"]
        if case == "none" and step is None:
            text = t["overview.no_group"]  # no right to enroll: only the fact
        action = t["student_groups.enroll"] if step == "enroll" else ""
        self.group_lines.empty.set_message(t[f"overview.empty.{case}.title"], text, action)

    def _first_step(self) -> None:
        """The empty state's button: what the groups list's own button does."""
        if self._empty_step == "enroll":
            self.groups.enroll.click()

    def open_window(self, key: str) -> None:
        """A whole list in a window; the page follows what was done there."""
        window = self.windows[key]
        window.section.refresh()
        window.exec()
        self.registration.refresh()
        self.payments.refresh()
        self.refresh_overview()

    def refresh(self) -> None:
        self.student = students.get(self._conn, self._ctx, self.student_id)
        s = self.student
        self.name.setText(s.full_name)
        self.number.setText(t["student_detail.number"].format(number=s.student_number))
        self.status.setText(t[f"student_status.{s.status}"])
        self.status.set_kind(kind_for("student", s.status))
        self.notes.setText(s.notes)
        self.notes.setVisible(bool(s.notes))
        active = s.status == "active"
        self.deactivate.setVisible(active and allowed(self._ctx, "student.deactivate"))
        self.reactivate.setVisible(not active and allowed(self._ctx, "student.reactivate"))

    def _show_info(self) -> None:
        StudentInfoDialog(self.student, parent=self).exec()

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
        self.refresh_overview()
        toast(self, t[message_key].format(name=self.student.full_name))


class StudentInfoDialog(QDialog):
    """The student's details kept off the card: birth date and age, file created on."""

    def __init__(self, s, parent=None):
        super().__init__(parent)
        self.setWindowTitle(s.full_name)
        title = QLabel(s.full_name)
        title.setObjectName("dialogTitle")
        born = "—"
        if s.birth_date:
            born = t["student_info.born_value"].format(
                date=display_date(s.birth_date), age=age_on(s.birth_date, dates.today()))
        rows = [
            ("number", s.student_number),
            ("status", t[f"student_status.{s.status}"]),
            ("born", born),
            ("since", display_date(s.created_at)),
        ]
        if s.notes:
            rows.append(("notes", s.notes))
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(8)
        self.values: dict[str, QLabel] = {}
        for r, (key, text) in enumerate(rows):
            label = QLabel(t[f"student_info.{key}"])
            label.setObjectName("fieldLabel")
            value = QLabel(text)
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(label, r, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(value, r, 1)
            self.values[key] = value
        grid.setColumnStretch(1, 1)
        close = QPushButton(t["action.close"])
        close.setAutoDefault(False)
        close.clicked.connect(self.accept)
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(close)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)
        layout.addWidget(title)
        layout.addLayout(grid)
        layout.addLayout(actions)
        self.setFixedWidth(400)


def age_on(birth: str, today: date) -> int:
    born = date.fromisoformat(birth)
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def section_card() -> QFrame:
    card = QFrame()
    card.setObjectName("card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(20, 16, 20, 18)
    layout.setSpacing(12)
    return card


def rule() -> QFrame:
    line = QFrame()
    line.setObjectName("cardRule")
    line.setFixedHeight(1)
    return line


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

    def make_compact(self) -> None:
        """For the student card: a small heading, the second phone and the SMS column left
        out (they are in the contact's dialog), the actions under the list."""
        layout = self.layout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        toolbar = layout.itemAt(layout.indexOf(self.error) + 1).layout()
        for button in (self.edit, self.make_main, self.unlink):
            toolbar.removeWidget(button)
        toolbar.insertWidget(0, heading(t["student_detail.tab.contacts"]))
        small(self.add)
        for column in (3, 4):
            self.table.setColumnHidden(column, True)
        compact_empty(self.empty)
        fit_height(self.table, 4)
        self.row_actions = row_actions_below(self.table, [self.edit, self.make_main,
                                                          self.unlink],
                                             layout, layout.indexOf(self.table) + 1)

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
