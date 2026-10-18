from datetime import date

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.dates import display_date, parse_display_date
from tadris.core.errors import BusinessRuleError
from tadris.domain.models import ContactInput, ContactLink, Student, StudentInput
from tadris.i18n.fr import t
from tadris.services import students
from tadris.ui.contact_dialog import relation_combo, row
from tadris.ui.widgets.common import (
    ErrorBanner,
    WarningBanner,
    fit_to_content,
    labeled,
    primary_button,
)
from tadris.ui.widgets.date_edit import DateLineEdit

NOTES_HEIGHT = 72
BIRTH_MIN = date(1940, 1, 1)
TYPICAL_AGE = 10  # the calendar opens on this many years ago


class StudentDialog(QDialog):
    """Create a student (with an optional main contact) or edit one.

    Possible duplicates show as a warning; submitting again with the same data goes ahead.
    """

    def __init__(self, conn, ctx: UserContext, student: Student | None = None, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._ctx = ctx
        self._student = student
        self._confirmed: tuple | None = None
        self.student_id: int | None = None if student is None else student.id
        creating = student is None
        title_text = t["student_dialog.new_title" if creating else "student_dialog.edit_title"]
        self.setWindowTitle(title_text)
        self.setFixedWidth(640)

        title = QLabel(title_text)
        title.setObjectName("dialogTitle")
        self.banner = ErrorBanner()
        self.warning = WarningBanner()
        self.last_name = QLineEdit()
        self.first_name = QLineEdit()
        today = dates.today()
        self.birth_date = DateLineEdit(
            minimum=BIRTH_MIN,
            maximum=today,
            suggested=date(today.year - TYPICAL_AGE, today.month, 1),
        )
        self.notes = QPlainTextEdit()
        self.notes.setFixedHeight(NOTES_HEIGHT)
        self.notes.setTabChangesFocus(True)

        if student is not None:
            self.last_name.setText(student.last_name)
            self.first_name.setText(student.first_name)
            if student.birth_date:
                self.birth_date.setText(display_date(student.birth_date))
            self.notes.setPlainText(student.notes)

        self.cancel = QPushButton(t["action.cancel"])
        self.cancel.setAutoDefault(False)
        self.cancel.clicked.connect(self.reject)
        self._submit_text = t["student_dialog.submit_new" if creating else "action.save"]
        self.submit = primary_button(self._submit_text)
        self.submit.clicked.connect(self._submit)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch()
        actions.addWidget(self.cancel)
        actions.addWidget(self.submit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)
        layout.addWidget(title)
        layout.addWidget(self.banner)
        layout.addWidget(self.warning)
        layout.addLayout(row(
            labeled(t["student_dialog.last_name"], self.last_name, required=True),
            labeled(t["student_dialog.first_name"], self.first_name, required=True),
        ))
        birth_row = row(labeled(t["student_dialog.birth_date"], self.birth_date))
        birth_row.addStretch(1)
        layout.addLayout(birth_row)
        layout.addWidget(labeled(t["student_dialog.notes"], self.notes))

        self.contact_name = QLineEdit()
        self.contact_relation = relation_combo()
        self.contact_phone = QLineEdit()
        self.contact_phone.setPlaceholderText("0661 90 25 47")
        self.contact_sms = QCheckBox(t["contact_dialog.can_receive_sms"])
        self.contact_sms.setChecked(True)
        if creating:
            section = QLabel(t["student_dialog.contact_section"])
            section.setObjectName("sectionTitle")
            caption = QLabel(t["student_dialog.contact_caption"])
            caption.setObjectName("caption")
            caption.setWordWrap(True)
            heading = QVBoxLayout()
            heading.setSpacing(2)
            heading.addWidget(section)
            heading.addWidget(caption)
            layout.addSpacing(4)
            layout.addLayout(heading)
            layout.addLayout(row(
                labeled(t["contact_dialog.full_name"], self.contact_name),
                labeled(t["contact_dialog.relation"], self.contact_relation),
            ))
            phone_row = row(labeled(t["contact_dialog.phone"], self.contact_phone))
            phone_row.addWidget(self.contact_sms, 1)
            layout.addLayout(phone_row)

        layout.addSpacing(4)
        layout.addLayout(actions)
        fit_to_content(self)
        self.last_name.setFocus()

    def _contact(self) -> ContactInput | None:
        if not (self.contact_name.text().strip() or self.contact_phone.text().strip()):
            return None
        return ContactInput(full_name=self.contact_name.text(), phone=self.contact_phone.text())

    def _submit(self) -> None:
        self.banner.clear_error()
        try:
            data = StudentInput(
                first_name=self.first_name.text(),
                last_name=self.last_name.text(),
                birth_date=parse_display_date(self.birth_date.text()),
                notes=self.notes.toPlainText(),
            )
            contact = self._contact()
            key = (data, contact)
            if key != self._confirmed and self._warn_duplicates(data, contact):
                self._confirmed = key
                return
            if self._student is None:
                link = ContactLink(relation=self.contact_relation.currentText(),
                                   is_main=True, can_receive_sms=self.contact_sms.isChecked())
                self.student_id = students.create(self._conn, self._ctx, data, contact, link)
            else:
                students.update(self._conn, self._ctx, self._student.id, data)
        except BusinessRuleError as exc:
            self.banner.show_error(exc.message)
            return
        self.accept()

    def _warn_duplicates(self, data: StudentInput, contact: ContactInput | None) -> bool:
        phones = () if contact is None else (contact.phone,)
        exclude = None if self._student is None else self._student.id
        matches = students.possible_duplicates(self._conn, self._ctx, data, phones, exclude)
        if not matches:
            self.warning.clear_warning()
            self.submit.setText(self._submit_text)
            return False
        lines = [t["student_dialog.duplicates"]]
        for match in matches:
            lines.append("• " + t[f"student_dialog.duplicate_{match.reason}"].format(
                name=match.full_name, number=match.student_number
            ))
        lines.append(t["student_dialog.duplicates_hint"])
        self.warning.show_warning("\n".join(lines))
        anyway = "student_dialog.submit_anyway" if self._student is None else "student_dialog.save_anyway"
        self.submit.setText(t[anyway])
        return True
