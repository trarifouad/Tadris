"""Choose a student without going through their page: « Encaisser un paiement » from the
dashboard. The late payers come first, the largest debt first; typing searches every active
student by name, number or phone, as the students list does."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLineEdit

from tadris.core.context import UserContext
from tadris.core.errors import ValidationError
from tadris.core.money import format_dzd
from tadris.core.phones import format_phone
from tadris.domain.models import StudentListItem
from tadris.i18n.fr import t
from tadris.services import debt, students
from tadris.ui.widgets.forms import FormDialog, caption
from tadris.ui.widgets.tables import (
    CENTER,
    ROW_HEIGHT,
    fill,
    fit_columns,
    item,
    ruled_table,
    selected_id,
)

VISIBLE_ROWS = 7
SHOWN = 50  # a search shows this many matches at most: typing more narrows them down
SEARCH_DELAY_MS = 150


class StudentPicker(FormDialog):
    def __init__(self, conn, ctx: UserContext, parent=None):
        super().__init__(t["picker.title"], t["picker.submit"], width=640, parent=parent)
        self._conn, self._ctx = conn, ctx
        self.student_id: int | None = None
        self._owed = {d.student_id: d.owed_now for d in debt.debtors(conn, ctx)}
        self.search = QLineEdit()
        self.search.setPlaceholderText(t["students.search"])
        self.search.setClearButtonEnabled(True)
        self.hint = caption()
        self.hint.setWordWrap(True)
        self.table = ruled_table([t["students.col.number"], t["picker.col.student"],
                                  t["students.col.phone"], t["picker.col.owed"]])
        header = self.table.horizontalHeader().height() or ROW_HEIGHT
        self.table.setFixedHeight(header + ROW_HEIGHT * VISIBLE_ROWS + 2)
        self.table.activated.connect(lambda _index: self._submit())
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(SEARCH_DELAY_MS)
        self._timer.timeout.connect(self._find)
        self.search.textChanged.connect(lambda _text: self._timer.start())
        self.add(self.search)
        self.add(self.hint)
        self.add(self.table)
        self._find()
        self.finish(self.search)

    def keyPressEvent(self, event) -> None:
        """Up and down move through the list while typing; Entrée takes the selected one."""
        if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up) and self.table.rowCount():
            row = self.table.currentRow() if self.table.selectedItems() else -1
            step = 1 if event.key() == Qt.Key.Key_Down else -1
            self.table.selectRow(max(0, min(row + step, self.table.rowCount() - 1)))
            return
        super().keyPressEvent(event)

    def _find(self) -> None:
        query = self.search.text().strip()
        found = students.search(self._conn, self._ctx, query, status="active",
                                limit=None if not query else SHOWN)
        if query:
            shown = found
            self.hint.setText(t["picker.none_found"].format(query=query) if not found
                              else t["picker.found"])
        else:
            # Nothing typed: the late payers, the largest first; then everyone by name.
            shown = sorted(found, key=lambda s: -self._owed.get(s.id, 0))[:SHOWN]
            self.hint.setText(t["picker.debtors_first"] if self._owed else t["picker.found"])
        fill(self.table, [self._cells(s) for s in shown])
        fit_columns(self.table, stretch=(1,))
        if shown:
            self.table.selectRow(0)
        self._selection_changed()

    def _cells(self, s: StudentListItem) -> list:
        owed = self._owed.get(s.id, 0)
        return [
            item(s.student_number, item_id=s.id, mono=True),
            item(f"{s.last_name} {s.first_name}"),
            item(format_phone(s.main_phone) if s.main_phone else "—", mono=True),
            item(format_dzd(owed) if owed else "—", align=CENTER, mono=True,
                 tone="danger" if owed else None),
        ]

    def _selection_changed(self) -> None:
        self.submit.setEnabled(selected_id(self.table) is not None)

    def save(self) -> None:
        student_id = selected_id(self.table)
        if student_id is None:
            raise ValidationError(t["picker.choose"])
        self.student_id = student_id
