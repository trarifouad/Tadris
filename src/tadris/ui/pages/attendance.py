"""Présences: the sessions of a day or a week, with what can be done to each one."""

from datetime import date, timedelta

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.permissions import allowed
from tadris.domain.models import Session
from tadris.i18n.fr import t
from tadris.services import groups, printing, sessions, teachers
from tadris.ui.pages.attendance_entry import AttendanceView
from tadris.ui.pages.timetable import week_start
from tadris.ui.session_dialogs import CancelSessionDialog, MakeupDialog, SubstituteDialog
from tadris.ui.theme.status import kind_for
from tadris.ui.widgets import common
from tadris.ui.widgets.common import ask, primary_button, toast, variant_button
from tadris.ui.widgets.date_edit import DateLineEdit
from tadris.ui.widgets.forms import ListDetailPage, ListSection
from tadris.ui.widgets.inputs import fill_combo, id_combo
from tadris.ui.widgets.tables import CENTER, fit_columns, item

DAY, WEEK = "day", "week"
MAX_CONFLICTS_SHOWN = 3


class SessionsView(QWidget):
    """The list; a double-click opens the session's attendance."""

    opened = Signal(int)

    def __init__(self, conn, ctx: UserContext):
        super().__init__()
        self._conn = conn
        self._ctx = ctx
        self.setObjectName("page")
        self._sessions: dict[int, Session] = {}
        manages = allowed(ctx, "session.manage")

        title = QLabel(t["nav.attendance"])
        title.setObjectName("pageTitle")
        self.mode = QComboBox()
        self.mode.addItem(t["sessions_page.day"], DAY)
        self.mode.addItem(t["sessions_page.week"], WEEK)
        self.mode.currentIndexChanged.connect(lambda _i: self.refresh())
        self.previous = QPushButton("◀")
        self.previous.setAutoDefault(False)
        self.previous.clicked.connect(lambda: self._step(-1))
        self.on = DateLineEdit()
        self.on.set_value(dates.today())
        self.on.textChanged.connect(lambda _text: self._date_changed())
        self.following = QPushButton("▶")
        self.following.setAutoDefault(False)
        self.following.clicked.connect(lambda: self._step(1))
        self.today = QPushButton(t["sessions_page.today"])
        self.today.setAutoDefault(False)
        self.today.clicked.connect(lambda: self.on.set_value(dates.today()))
        self.group = id_combo([])
        self.group.currentIndexChanged.connect(lambda _i: self.refresh())
        self.teacher = id_combo([])
        self.teacher.currentIndexChanged.connect(lambda _i: self.refresh())
        self.period = QLabel()
        self.period.setObjectName("sectionTitle")
        controls = QHBoxLayout()
        controls.setSpacing(8)
        for widget in (self.mode, self.previous, self.on, self.following, self.today):
            controls.addWidget(widget)
        controls.addSpacing(16)
        controls.addWidget(self.group, 1)
        controls.addWidget(self.teacher, 1)

        self.list = ListSection([t["sessions_page.col.date"], t["sessions_page.col.time"],
                                 t["sessions_page.col.group"], t["sessions_page.col.room"],
                                 t["sessions_page.col.teacher"], t["sessions_page.col.status"],
                                 t["sessions_page.col.attendance"], t["sessions_page.col.note"]],
                                t["sessions_page.empty"])
        fit_columns(self.list.table, stretch=(2, 7))
        self.list.toolbar.insertWidget(0, self.period)
        self.cancel = self.list.add_button(variant_button(t["sessions_page.cancel"], "danger"))
        self.cancel.clicked.connect(self._cancel)
        self.restore = self.list.add_button(QPushButton(t["sessions_page.restore"]))
        self.restore.clicked.connect(self._restore)
        self.makeup = self.list.add_button(QPushButton(t["sessions_page.makeup"]))
        self.makeup.clicked.connect(self._makeup)
        self.substitute = self.list.add_button(QPushButton(t["sessions_page.substitute"]))
        self.substitute.clicked.connect(self._substitute)
        self.week_sheet = self.list.add_button(QPushButton(t["sessions_page.week_sheet"]),
                                               end=True)
        self.week_sheet.clicked.connect(self._print_week)
        self.week_sheet.setVisible(allowed(ctx, "print.document"))
        self.regenerate = self.list.add_button(primary_button(t["sessions_page.regenerate"]),
                                               end=True)
        self.regenerate.setDefault(False)
        self.regenerate.clicked.connect(self._regenerate)
        for button in (self.cancel, self.restore, self.makeup, self.substitute,
                       self.regenerate):
            button.setVisible(manages)
        self.list.selection_changed.connect(self._update_buttons)
        self.list.activated.connect(self.opened.emit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addLayout(controls)
        layout.addWidget(self.list, 1)
        self.load_filters()
        self.refresh()

    def load_filters(self) -> None:
        fill_combo(self.group, [(t["sessions_page.all_groups"], None)] + [
            (g.title, g.id) for g in groups.search(self._conn, self._ctx)
            if g.status != "closed"], self.group.currentData())
        fill_combo(self.teacher, [(t["sessions_page.all_teachers"], None)] + [
            (teacher.full_name, teacher.id) for teacher in teachers.search(self._conn, self._ctx)
        ], self.teacher.currentData())

    def window_dates(self):
        on = self.on.value() or dates.today()
        if self.mode.currentData() == WEEK:
            first = week_start(on)
            return first, first + timedelta(days=6)
        return on, on

    def refresh(self) -> None:
        first, last = self.window_dates()
        if first == last:
            self.period.setText(t["sessions_page.period_day"].format(
                day=t[f"weekday.{dates.weekday_1_to_7(first)}"],
                date=dates.display_date(dates.iso(first))))
        else:
            self.period.setText(t["sessions_page.period_week"].format(
                first=dates.display_date(dates.iso(first)),
                last=dates.display_date(dates.iso(last))))
        listed = sessions.listing(self._conn, self._ctx, first, last,
                                  group_id=self.group.currentData(),
                                  teacher_id=self.teacher.currentData())
        self._sessions = {s.id: s for s in listed}
        self.list.set_rows([self._cells(s) for s in listed])
        self.week_sheet.setEnabled(self.group.currentData() is not None)
        self.week_sheet.setToolTip("" if self.group.currentData() is not None
                                   else t["sessions_page.week_sheet_hint"])

    def _cells(self, s: Session) -> list:
        day = t[f"weekday.{dates.weekday_1_to_7(date.fromisoformat(s.date))}"]
        teacher = s.teacher + (f" · {t['sessions_page.substitute_mark']}" if s.substitute else "")
        if s.status == "cancelled":
            recorded = "—"
        else:
            recorded = t["sessions_page.recorded"].format(done=s.attendance_count,
                                                          total=s.expected)
        return [
            item(f"{day} {dates.display_date(s.date)}", s.date + s.start_time, item_id=s.id),
            item(f"{s.start_time} – {s.end_time}", mono=True),
            item(s.group_title),
            item(s.room),
            item(teacher),
            item(t[f"session_status.{s.status}"], kind=kind_for("session", s.status)),
            item(recorded, align=CENTER),
            item(self._note(s)),
        ]

    @staticmethod
    def _note(s: Session) -> str:
        notes = []
        if s.makeup_of_date:
            notes.append(t["sessions_page.note.makeup_of"].format(
                date=dates.display_date(s.makeup_of_date)))
        if s.status == "cancelled" and s.cancellation_reason:
            notes.append(s.cancellation_reason)
        if s.makeup_date:
            notes.append(t["sessions_page.note.made_up"].format(
                date=dates.display_date(s.makeup_date)))
        return " · ".join(notes)

    def selected(self) -> Session | None:
        session_id = self.list.selected_id()
        return None if session_id is None else self._sessions.get(session_id)

    def _update_buttons(self) -> None:
        s = self.selected()
        self.cancel.setEnabled(s is not None and s.status == "planned"
                               and not s.attendance_count)
        free = s is not None and s.status == "cancelled" and s.makeup_id is None
        self.restore.setEnabled(free)
        self.makeup.setEnabled(free)
        self.substitute.setEnabled(s is not None and s.status != "cancelled")

    def _step(self, direction: int) -> None:
        days = 7 if self.mode.currentData() == WEEK else 1
        self.on.set_value((self.on.value() or dates.today()) + timedelta(days=direction * days))

    def _date_changed(self) -> None:
        if self.on.value() is not None:
            self.refresh()

    def _done(self, message: str, select: int | None = None) -> None:
        self.list.clear_error()
        self.refresh()
        if select is not None:
            self.list.select_id(select)
        toast(self, message)

    def _regenerate(self) -> None:
        if not self.list.run(sessions.generate, self._conn, self._ctx):
            return
        result = self.list.last_result
        self._done(t["sessions_page.generated"].format(count=result.created))
        if result.conflicts:
            lines = [t["sessions_page.conflict_line"].format(
                date=dates.display_date(day), message=message)
                for day, _group, message in result.conflicts[:MAX_CONFLICTS_SHOWN]]
            self.list.show_error(t["sessions_page.conflicts"].format(
                count=len(result.conflicts), lines="\n".join(lines)))

    def _print_week(self) -> None:
        group_id = self.group.currentData()
        if group_id is None:
            return
        first = week_start(self.on.value() or dates.today())
        if not self.list.run(printing.week_sheet, self._conn, self._ctx, group_id, first):
            return
        common.open_document(self.list.last_result)
        toast(self, t["print.done"].format(name=self.list.last_result.name))

    def _cancel(self) -> None:
        s = self.selected()
        if s is not None and ask(CancelSessionDialog(self._conn, self._ctx, s, parent=self)):
            self._done(t["sessions_page.cancelled"].format(group=s.group_name), s.id)

    def _restore(self) -> None:
        s = self.selected()
        if s is not None and self.list.run(sessions.restore, self._conn, self._ctx, s.id):
            self._done(t["sessions_page.restored"].format(group=s.group_name), s.id)

    def _makeup(self) -> None:
        s = self.selected()
        if s is None:
            return
        dialog = MakeupDialog(self._conn, self._ctx, s, parent=self)
        if ask(dialog):
            makeup = sessions.get(self._conn, self._ctx, dialog.makeup_id)
            self._done(t["sessions_page.made_up"].format(
                group=s.group_name, date=dates.display_date(makeup.date),
                start=makeup.start_time), s.id)

    def _substitute(self) -> None:
        s = self.selected()
        if s is not None and ask(SubstituteDialog(self._conn, self._ctx, s, parent=self)):
            self._done(t["sessions_page.teacher_set"].format(group=s.group_name), s.id)


class AttendancePage(ListDetailPage):
    """Présences in the sidebar: the sessions, and a session's attendance in place of them."""

    def __init__(self, conn, ctx: UserContext):
        super().__init__(SessionsView(conn, ctx),
                         lambda session_id: AttendanceView(conn, ctx, session_id))

    @property
    def sessions(self) -> SessionsView:
        return self.list

    def has_unsaved(self) -> bool:
        """A session's attendance is open with marks not saved yet."""
        return self.detail is not None and self.detail.dirty()

    def refresh(self) -> None:
        if self.detail is None:
            self.list.load_filters()
        super().refresh()
