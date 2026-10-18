from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError
from tadris.core.phones import format_phone
from tadris.domain.models import ContactInput, ContactLink, ExistingContact, StudentContact
from tadris.i18n.fr import t
from tadris.services import contacts
from tadris.ui.widgets.common import (
    ErrorBanner,
    WarningBanner,
    fit_to_content,
    labeled,
    primary_button,
    variant_button,
)

RELATIONS = ("father", "mother", "guardian", "sibling", "grandparent", "self")


def relation_combo() -> QComboBox:
    """Common relations to pick from; any other text can be typed."""
    combo = QComboBox()
    combo.setEditable(True)
    combo.addItem("")
    for key in RELATIONS:
        combo.addItem(t[f"relation.{key}"])
    return combo


def row(*widgets) -> QHBoxLayout:
    layout = QHBoxLayout()
    layout.setSpacing(12)
    for widget in widgets:
        layout.addWidget(widget, 1)
    return layout


class ContactDialog(QDialog):
    """Add a parent or guardian to a student, or edit one of its contacts.

    A new contact whose phone is already on file (a sibling's parent) is linked rather than
    duplicated, unless the user chooses to create a new contact.
    """

    def __init__(self, conn, ctx: UserContext, student_id: int,
                 contact: StudentContact | None = None, is_first: bool = False, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._ctx = ctx
        self._student_id = student_id
        self._contact = contact
        self._existing: ExistingContact | None = None
        self.contact_id: int | None = None if contact is None else contact.contact_id
        title_text = t["contact_dialog.new_title" if contact is None else "contact_dialog.edit_title"]
        self.setWindowTitle(title_text)
        self.setFixedWidth(640)

        title = QLabel(title_text)
        title.setObjectName("dialogTitle")
        self.banner = ErrorBanner()
        self.warning = WarningBanner()
        self.full_name = QLineEdit()
        self.relation = relation_combo()
        self.phone = QLineEdit()
        self.phone.setPlaceholderText("0661 90 25 47")
        self.phone.textEdited.connect(self._forget_existing)
        self.phone_2 = QLineEdit()
        self.address = QLineEdit()
        self.is_main = QCheckBox(t["contact_dialog.is_main"])
        self.can_receive_sms = QCheckBox(t["contact_dialog.can_receive_sms"])
        self.can_receive_sms.setChecked(True)
        self.note = QLabel()
        self.note.setObjectName("caption")
        self.note.setWordWrap(True)
        self.note.hide()

        if contact is not None:
            self.full_name.setText(contact.full_name)
            self.relation.setCurrentText(contact.relation)
            self.phone.setText(format_phone(contact.phone))
            self.phone_2.setText(format_phone(contact.phone_2))
            self.address.setText(contact.address or "")
            self.is_main.setChecked(contact.is_main)
            self.can_receive_sms.setChecked(contact.can_receive_sms)
            notes = []
            if contact.is_main:
                notes.append(t["contact_dialog.main_locked"])
            if contact.shared_with:
                notes.append(t["contact_dialog.shared"].format(names=", ".join(contact.shared_with)))
            if notes:
                self.note.setText(" ".join(notes))
                self.note.show()
        # The main contact can only change by naming another one; a first contact is main.
        if is_first or (contact is not None and contact.is_main):
            self.is_main.setChecked(True)
            self.is_main.setEnabled(False)

        self.cancel = QPushButton(t["action.cancel"])
        self.cancel.setAutoDefault(False)
        self.cancel.clicked.connect(self.reject)
        self.create_new = variant_button(t["contact_dialog.create_new"], "ghost")
        self.create_new.clicked.connect(self._create_new)
        self.create_new.hide()
        self.submit = primary_button(t["contact_dialog.submit"])
        self.submit.clicked.connect(self._submit)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addWidget(self.create_new)
        actions.addStretch()
        actions.addWidget(self.cancel)
        actions.addWidget(self.submit)

        checks = QHBoxLayout()
        checks.setSpacing(24)
        checks.addWidget(self.is_main)
        checks.addWidget(self.can_receive_sms)
        checks.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)
        layout.addWidget(title)
        layout.addWidget(self.banner)
        layout.addWidget(self.warning)
        layout.addLayout(row(
            labeled(t["contact_dialog.full_name"], self.full_name, required=True),
            labeled(t["contact_dialog.relation"], self.relation),
        ))
        layout.addLayout(row(
            labeled(t["contact_dialog.phone"], self.phone, required=True),
            labeled(t["contact_dialog.phone_2"], self.phone_2),
        ))
        layout.addWidget(labeled(t["contact_dialog.address"], self.address))
        layout.addLayout(checks)
        layout.addWidget(self.note)
        layout.addSpacing(4)
        layout.addLayout(actions)
        fit_to_content(self)
        self.full_name.setFocus()

    def _data(self) -> ContactInput:
        return ContactInput(
            full_name=self.full_name.text(),
            phone=self.phone.text(),
            phone_2=self.phone_2.text(),
            address=self.address.text(),
        )

    def _link(self) -> ContactLink:
        return ContactLink(
            relation=self.relation.currentText(),
            is_main=self.is_main.isChecked(),
            can_receive_sms=self.can_receive_sms.isChecked(),
        )

    def _forget_existing(self) -> None:
        if self._existing is not None:
            self._existing = None
            self.warning.clear_warning()
            self.create_new.hide()
            self.submit.setText(t["contact_dialog.submit"])

    def _offer_existing(self, existing: ExistingContact) -> None:
        self._existing = existing
        if existing.students:
            message = t["contact_dialog.existing"].format(
                name=existing.full_name, students=", ".join(existing.students)
            )
        else:
            message = t["contact_dialog.existing_no_student"].format(name=existing.full_name)
        self.warning.show_warning(message)
        self.create_new.show()
        self.submit.setText(t["contact_dialog.link_existing"])

    def _submit(self) -> None:
        self.banner.clear_error()
        try:
            if self._contact is not None:
                contacts.update(self._conn, self._ctx, self._student_id,
                                self._contact.contact_id, self._data(), self._link())
            elif self._existing is not None:
                contacts.link_existing(self._conn, self._ctx, self._student_id,
                                       self._existing.contact_id, self._link())
                self.contact_id = self._existing.contact_id
            else:
                found = contacts.find_by_phone(self._conn, self._ctx, self.phone.text(),
                                               self._student_id)
                if found:
                    self._offer_existing(found[0])
                    return
                self._add()
        except BusinessRuleError as exc:
            self.banner.show_error(exc.message)
            return
        self.accept()

    def _create_new(self) -> None:
        self.banner.clear_error()
        try:
            self._add()
        except BusinessRuleError as exc:
            self.banner.show_error(exc.message)
            return
        self.accept()

    def _add(self) -> None:
        self.contact_id = contacts.add(
            self._conn, self._ctx, self._student_id, self._data(), self._link()
        )

    def saved_name(self) -> str:
        if self._existing is not None:
            return self._existing.full_name
        return " ".join(self.full_name.text().split())
