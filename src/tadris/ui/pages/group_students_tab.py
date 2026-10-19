"""The group page's Élèves tab: who is in the group, the free seats, and who left."""

from PySide6.QtWidgets import QCheckBox, QLabel, QVBoxLayout, QWidget

from tadris.core.context import UserContext
from tadris.core.dates import display_date
from tadris.domain.models import Enrollment, Group
from tadris.i18n.fr import t
from tadris.services import enrollments
from tadris.ui.theme.status import kind_for
from tadris.ui.widgets.forms import ListSection
from tadris.ui.widgets.tables import fit_columns, item


class GroupStudentsTab(QWidget):
    """Read-only: students are enrolled, switched and removed from their own page."""

    def __init__(self, conn, ctx: UserContext, group_id: int):
        super().__init__()
        self._conn = conn
        self._ctx = ctx
        self._group_id = group_id
        self._group: Group | None = None
        self.summary = QLabel()
        self.summary.setObjectName("sectionTitle")
        self.show_past = QCheckBox()
        self.show_past.toggled.connect(lambda _on: self.refresh())
        self.list = ListSection([t["group_students.col.name"], t["group_students.col.number"],
                                 t["group_students.col.status"], t["group_students.col.entry"],
                                 t["group_students.col.exit"], t["group_students.col.note"]],
                                t["group_students.empty"], sortable=True)
        self.list.toolbar.insertWidget(0, self.summary)
        self.list.toolbar.addWidget(self.show_past)
        fit_columns(self.list.table, stretch=(0, 5))
        hint = QLabel(t["group_students.hint"])
        hint.setObjectName("caption")
        hint.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.list, 1)
        layout.addWidget(hint)

    def show_group(self, group: Group) -> None:
        """Called by the group page with its freshly loaded group."""
        self._group = group
        self.refresh()

    def refresh(self) -> None:
        if self._group is None:
            return
        listed = enrollments.for_group(self._conn, self._ctx, self._group_id)
        live = [e for e in listed if e.is_live]
        g = self._group
        self.summary.setText(t["group_students.summary"].format(
            enrolled=len(live), seats=g.seats, free=max(g.seats - len(live), 0),
            trials=sum(e.status == "trial" for e in live)))
        shown = listed if self.show_past.isChecked() else live
        past = len(listed) - len(live)
        self.show_past.setText(t["group_students.show_past"].format(count=past))
        self.show_past.setEnabled(past > 0)
        self.list.set_rows([self._cells(e) for e in shown])

    @staticmethod
    def _cells(e: Enrollment) -> list:
        notes = []
        if e.other_level:
            notes.append(t["student_groups.note.other_level"].format(level=e.registration_level))
        if e.switched_from_id is not None:
            notes.append(t["group_students.note.switched_in"])
        if e.started_as_trial and e.status != "trial":
            notes.append(t["student_groups.note.after_trial"])
        live_first = (0 if e.is_live else 1, e.student_name.casefold())
        return [
            item(e.student_name, live_first, item_id=e.id),
            item(e.student_number, mono=True),
            item(t[f"enrollment_status.{e.status}"], (0 if e.is_live else 1, e.status),
                 kind=kind_for("enrollment", e.status)),
            item(display_date(e.enrolled_on), e.enrolled_on),
            item(display_date(e.left_on) if e.left_on else "", e.left_on or ""),
            item(" · ".join(notes)),
        ]
