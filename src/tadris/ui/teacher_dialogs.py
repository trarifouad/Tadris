from datetime import date

from PySide6.QtWidgets import QLineEdit

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.dates import parse_display_date
from tadris.core.percent import format_percent
from tadris.core.phones import format_phone
from tadris.domain.models import Teacher, TeacherInput
from tadris.i18n.fr import t
from tadris.services import teachers
from tadris.ui.setup_dialogs import required_date
from tadris.ui.widgets.common import labeled
from tadris.ui.widgets.date_edit import DateLineEdit
from tadris.ui.widgets.forms import FormDialog, caption, row
from tadris.ui.widgets.inputs import percent_edit, read_percent


class TeacherDialog(FormDialog):
    """New teacher with a starting rate (from the arrival date unless another day is chosen),
    or edit the teacher: name, phone, arrival date and the rate (a new rate from a date, the
    old one kept in the history; the same rate from an earlier date makes the first rate
    start earlier)."""

    def __init__(self, conn, ctx: UserContext, teacher: Teacher | None = None, parent=None):
        key = "teacher_dialog.new_title" if teacher is None else "teacher_dialog.edit_title"
        super().__init__(t[key], t["action.save"], width=640, parent=parent)
        self._conn, self._ctx, self._teacher = conn, ctx, teacher
        self.teacher_id: int | None = None if teacher is None else teacher.id
        self.rate_changed = False
        self.full_name = QLineEdit()
        self.phone = QLineEdit()
        self.phone.setPlaceholderText("0661 90 25 47")
        self.hire_date = DateLineEdit(maximum=dates.today())
        self.rate = percent_edit(None if teacher is None else teacher.current_rate_bp)
        self.rate_from = DateLineEdit()
        self.rate_from.set_value(dates.today())
        self._rate_follows = dates.today()  # the rate's day while it follows the arrival
        if teacher is not None:
            self.full_name.setText(teacher.full_name)
            self.phone.setText(format_phone(teacher.phone))
            if teacher.hire_date:
                self.hire_date.set_value(date.fromisoformat(teacher.hire_date))
        self.add(labeled(t["teacher_dialog.name"], self.full_name, required=True))
        self.add(row(labeled(t["teacher_dialog.phone"], self.phone),
                     labeled(t["teacher_dialog.hire_date"], self.hire_date)))
        self.add(row(labeled(t["teacher_dialog.rate"], self.rate, required=True),
                     labeled(t["teacher_dialog.rate_from"], self.rate_from, required=True)))
        if teacher is None or teacher.current_rate_bp is None:
            note = caption(t["teacher_dialog.rate_caption"])
            self.hire_date.textChanged.connect(lambda _text: self._follow_arrival())
        else:
            note = caption(t["teacher_dialog.rate_change_caption"].format(
                rate=format_percent(teacher.current_rate_bp),
                date=dates.display_date(teacher.current_rate_from)
                if teacher.current_rate_from else "—"))
        note.setWordWrap(True)
        self.add(note)
        self.finish(self.full_name)

    def _follow_arrival(self) -> None:
        """A new teacher's rate starts on their arrival date, until another day is chosen."""
        arrival = self.hire_date.value()
        if arrival is None or self.rate_from.value() != self._rate_follows:
            return
        self.rate_from.set_value(arrival)
        self._rate_follows = arrival

    def _data(self) -> TeacherInput:
        return TeacherInput(self.full_name.text(), self.phone.text(),
                            parse_display_date(self.hire_date.text()))

    def save(self) -> None:
        data = self._data()
        if self._teacher is None:
            self.teacher_id = teachers.create(self._conn, self._ctx, data,
                                              read_percent(self.rate),
                                              required_date(self.rate_from))
        else:
            # The rate only when it changed, or when the same rate is to start earlier than
            # the current one (it was set to start too late): otherwise it keeps running.
            bp = read_percent(self.rate)
            start = required_date(self.rate_from)
            current_from = self._teacher.current_rate_from
            earlier = current_from is not None and dates.iso(start) < current_from
            self.rate_changed = bp != self._teacher.current_rate_bp or earlier
            if self.rate_changed:
                teachers.update(self._conn, self._ctx, self._teacher.id, data, bp, start)
            else:
                teachers.update(self._conn, self._ctx, self._teacher.id, data)
