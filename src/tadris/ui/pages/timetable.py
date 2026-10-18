from datetime import date, timedelta

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.permissions import allowed
from tadris.domain.models import Slot
from tadris.i18n.fr import t
from tadris.services import rooms, settings, teachers, timetable
from tadris.ui.group_dialogs import SlotDialog, open_groups
from tadris.ui.widgets.common import ask, primary_button, toast
from tadris.ui.widgets.date_edit import DateLineEdit
from tadris.ui.widgets.forms import caption
from tadris.ui.widgets.inputs import fill_combo, id_combo
from tadris.ui.widgets.timetable_grid import TimetableGrid

BY_ROOM, BY_GROUP, BY_TEACHER = "room", "group", "teacher"


def week_start(day: date) -> date:
    """The Saturday that starts the (Algerian) week of a day."""
    return day - timedelta(days=(dates.weekday_1_to_7(day) - 6) % 7)


class TimetablePage(QWidget):
    """The weekly timetable of one room, group or teacher, on a chosen week."""

    def __init__(self, conn, ctx: UserContext):
        super().__init__()
        self._conn = conn
        self._ctx = ctx
        self.setObjectName("page")
        self.plans = allowed(ctx, "timetable.manage")

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
        self.grid.slot_clicked.connect(self._edit)
        self.grid.empty_double_clicked.connect(self._create)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidget(self.grid)
        self.hint = caption()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 24)
        layout.setSpacing(16)
        layout.addLayout(head)
        layout.addLayout(controls)
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
        if entity is not None:
            slots = timetable.week(self._conn, self._ctx, on, **{f"{mode}_id": entity})
        detail = "teacher" if mode == BY_ROOM else "room"
        today = dates.today()
        same_week = week_start(on) == week_start(today)
        today_weekday = dates.weekday_1_to_7(today) if same_week else None
        self.grid.set_slots(slots, detail, today_weekday, settings.school_hours(self._conn))
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

    def _edit(self, slot: Slot) -> None:
        if not self.plans:
            return
        dialog = SlotDialog(self._conn, self._ctx, slot, parent=self)
        if ask(dialog):
            self.refresh()
            toast(self, t["slots.removed" if dialog.removed else "slots.updated"])

