from datetime import timedelta

from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.dates import week_start
from tadris.core.errors import BusinessRuleError
from tadris.core.permissions import allowed
from tadris.domain.models import Session, Slot
from tadris.i18n.fr import t
from tadris.services import rooms, sessions, settings, teachers, timetable
from tadris.ui.group_dialogs import SlotDialog, open_groups
from tadris.ui.session_dialogs import RescheduleDialog
from tadris.ui.widgets.common import PageBanner, ask, confirm, primary_button, toast
from tadris.ui.widgets.date_edit import DateLineEdit
from tadris.ui.widgets.forms import caption
from tadris.ui.widgets.inputs import fill_combo, id_combo
from tadris.ui.widgets.timetable_grid import TimetableGrid, short_day

BY_ROOM, BY_GROUP, BY_TEACHER = "room", "group", "teacher"
RESCHEDULE, UNDO, EDIT = "reschedule", "undo", "edit"


class TimetablePage(QWidget):
    """The weekly timetable of one room, group or teacher, on a chosen week, as that week
    goes: a session moved this week shows muted, its makeup at its new place. Clicking a
    session offers to move it this week only (« Reporter », a makeup the same week, with a
    reason), to undo that, or to change its slot for every week."""

    def __init__(self, conn, ctx: UserContext):
        super().__init__()
        self._conn = conn
        self._ctx = ctx
        self.setObjectName("page")
        self.plans = allowed(ctx, "timetable.manage")
        self.moves = allowed(ctx, "session.manage")
        self.menu: QMenu | None = None

        heading = QLabel(t["nav.timetable"])
        heading.setObjectName("pageTitle")
        self.new_slot = primary_button(t["timetable.new"])
        self.new_slot.setDefault(False)
        self.new_slot.clicked.connect(lambda: self._create())
        self.new_slot.setVisible(self.plans)
        head = QHBoxLayout()
        head.addWidget(heading)
        head.addStretch()
        head.addWidget(self.new_slot)

        self.mode = id_combo([(t["timetable.view.room"], BY_ROOM),
                              (t["timetable.view.group"], BY_GROUP),
                              (t["timetable.view.teacher"], BY_TEACHER)])
        self.entity = id_combo([])
        self.on = DateLineEdit()
        self.on.set_value(dates.today())
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.entity.currentIndexChanged.connect(self.refresh)
        self.on.textChanged.connect(self._date_changed)
        controls = QHBoxLayout()
        controls.setSpacing(12)
        controls.addWidget(self.mode, 1)
        controls.addWidget(self.entity, 2)
        controls.addStretch(1)
        week = QHBoxLayout()
        week.setSpacing(8)
        week.addWidget(caption(t["timetable.on"]))
        week.addWidget(self.on)
        controls.addLayout(week)

        self.grid = TimetableGrid()
        self.grid.slot_clicked.connect(self._slot_clicked)
        self.grid.makeup_clicked.connect(self._makeup_clicked)
        self.grid.empty_double_clicked.connect(self._create)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidget(self.grid)
        self.hint = caption()
        self.error = PageBanner()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 24)
        layout.setSpacing(16)
        layout.addLayout(head)
        layout.addLayout(controls)
        layout.addWidget(self.error)
        layout.addWidget(self.hint)
        layout.addWidget(self.scroll, 1)
        self._load_entities()
        self.refresh()

    # ----- state -----

    def _entities(self) -> list[tuple[str, int]]:
        mode = self.mode.currentData()
        if mode == BY_ROOM:
            return [(r.name, r.id) for r in rooms.list_rooms(self._conn, self._ctx,
                                                             active_only=True)]
        if mode == BY_GROUP:
            return [(g.title, g.id) for g in open_groups(self._conn, self._ctx)]
        return [(x.full_name, x.id) for x in teachers.search(self._conn, self._ctx)]

    def _load_entities(self) -> None:
        fill_combo(self.entity, self._entities(), self.entity.currentData())

    def _mode_changed(self) -> None:
        fill_combo(self.entity, self._entities())
        self.refresh()

    def _date_changed(self) -> None:
        if self.on.value() is not None:
            self.refresh()

    def refresh(self) -> None:
        self._load_entities()
        mode, entity = self.mode.currentData(), self.entity.currentData()
        on = self.on.value() or dates.today()
        slots: list[Slot] = []
        week: dict[int, Session] = {}
        makeups: list[Session] = []
        if entity is not None:
            slots = timetable.week(self._conn, self._ctx, on, **{f"{mode}_id": entity})
            first = week_start(on)
            for s in sessions.listing(self._conn, self._ctx, first, first + timedelta(days=6),
                                      **{f"{mode}_id": entity}):
                if s.source == "makeup":
                    if s.status != "cancelled":
                        makeups.append(s)
                elif s.slot_id is not None:
                    week[s.slot_id] = s
        detail = "teacher" if mode == BY_ROOM else "room"
        today = dates.today()
        same_week = week_start(on) == week_start(today)
        today_weekday = dates.weekday_1_to_7(today) if same_week else None
        self.grid.set_slots(slots, detail, today_weekday, settings.school_hours(self._conn),
                            week, makeups)
        if entity is None:
            self.hint.setText(t["timetable.nothing"])
        elif not slots:
            self.hint.setText(t["timetable.empty"])
        else:
            self.hint.setText(t["timetable.hint"] if self.plans else "")
        self.hint.setVisible(bool(self.hint.text()))

    # ----- actions -----

    def _create(self, weekday: int | None = None, start: str | None = None) -> None:
        if not self.plans:
            return
        mode, entity = self.mode.currentData(), self.entity.currentData()
        dialog = SlotDialog(
            self._conn, self._ctx,
            group_id=entity if mode == BY_GROUP else None,
            room_id=entity if mode == BY_ROOM else None,
            weekday=weekday, start=start, parent=self,
        )
        if ask(dialog):
            self.refresh()
            toast(self, t["slots.added"])

    def slot_actions(self, slot: Slot) -> list[str]:
        """What a click on a slot offers, on the week shown."""
        session = self.grid.week.get(slot.id)
        today = dates.iso(dates.today())
        actions = []
        if self.moves and session is not None and session.date >= today:
            if session.status == "planned" and not session.attendance_count:
                actions.append(RESCHEDULE)
            elif session.status == "cancelled" and session.makeup_id is not None:
                actions.append(UNDO)
        if self.plans:
            actions.append(EDIT)
        return actions

    def makeup_actions(self, makeup: Session) -> list[str]:
        today = dates.iso(dates.today())
        if (self.moves and makeup.makeup_of_session_id is not None and makeup.date >= today
                and (makeup.makeup_of_date or "") >= today and not makeup.attendance_count):
            return [UNDO]
        return []

    def _slot_clicked(self, slot: Slot) -> None:
        session = self.grid.week.get(slot.id)
        self._offer(self.slot_actions(slot), slot, session.id if session else None)

    def _makeup_clicked(self, makeup: Session) -> None:
        self._offer(self.makeup_actions(makeup), None, makeup.makeup_of_session_id)

    def _offer(self, actions: list[str], slot: Slot | None, session_id: int | None) -> None:
        """One action runs at once; several open a menu under the pointer."""
        if len(actions) == 1:
            self.run_action(actions[0], slot, session_id)
            return
        if not actions:
            return
        self.menu = QMenu(self)
        for action in actions:
            self.menu.addAction(t[f"timetable.action.{action}"]).triggered.connect(
                lambda _checked=False, a=action: self.run_action(a, slot, session_id))
        self.menu.popup(QCursor.pos())

    def run_action(self, action: str, slot: Slot | None, session_id: int | None) -> None:
        if action == EDIT and slot is not None:
            self._edit(slot)
        elif action == RESCHEDULE and session_id is not None:
            self._reschedule(session_id)
        elif action == UNDO and session_id is not None:
            self._undo(session_id)

    def _reschedule(self, session_id: int) -> None:
        dialog = RescheduleDialog(self._conn, self._ctx,
                                  sessions.get(self._conn, self._ctx, session_id), parent=self)
        if ask(dialog):
            makeup = sessions.get(self._conn, self._ctx, dialog.makeup_id)
            self.refresh()
            toast(self, t["timetable.rescheduled"].format(
                when=f"{short_day(makeup.date)} {makeup.start_time}"))

    def _undo(self, session_id: int) -> None:
        if not confirm(self, t["timetable.undo_title"], t["timetable.undo_text"],
                       t["timetable.action.undo"]):
            return
        try:
            sessions.undo_reschedule(self._conn, self._ctx, session_id)
        except BusinessRuleError as exc:
            self.error.show_error(exc.message)
            return
        self.error.clear_error()
        self.refresh()
        toast(self, t["timetable.undone"])

    def _edit(self, slot: Slot) -> None:
        if not self.plans:
            return
        dialog = SlotDialog(self._conn, self._ctx, slot, parent=self)
        if ask(dialog):
            self.refresh()
            toast(self, t["slots.removed" if dialog.removed else "slots.updated"])

