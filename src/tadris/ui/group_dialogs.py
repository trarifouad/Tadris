from datetime import date

from PySide6.QtWidgets import QLineEdit

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.errors import BusinessRuleError, ValidationError
from tadris.domain.models import Group, GroupInput, Slot, SlotInput
from tadris.i18n.fr import t
from tadris.services import catalog, groups, rooms, school_years, settings, teachers, timetable
from tadris.ui.setup_dialogs import required_date
from tadris.ui.widgets.common import confirm, labeled, variant_button
from tadris.ui.widgets.date_edit import DateLineEdit
from tadris.ui.widgets.forms import FormDialog, caption, row
from tadris.ui.widgets.inputs import (
    STEP_MINUTES,
    WEEK_ORDER,
    count_spin,
    id_combo,
    money_edit,
    read_money,
    read_time,
    time_combo,
)

DEFAULT_SLOT_MINUTES = 90
PREFERRED_START = "17:00"


def default_start(opens_at: str, closes_at: str) -> str:
    """17:00 when a 1 h 30 slot still fits before closing, else as late as one fits."""
    latest = dates.add_minutes(closes_at, -DEFAULT_SLOT_MINUTES)
    return max(opens_at, min(PREFERRED_START, latest))


def required_id(combo) -> int:
    value = combo.currentData()
    if value is None:
        raise ValidationError(t["validation.generic"])
    return value


def day_name(weekday: int) -> str:
    name = t[f"weekday.{weekday}"]
    return name[:1].upper() + name[1:]


class GroupDialog(FormDialog):
    """New group (year, level, subject, name, price, places, start, teacher) or edit one.
    The year is fixed once created; the teacher changes through ChangeTeacherDialog."""

    def __init__(self, conn, ctx: UserContext, group: Group | None = None,
                 year_id: int | None = None, parent=None):
        key = "group_dialog.new_title" if group is None else "group_dialog.edit_title"
        super().__init__(t[key], t["action.save"], width=640, parent=parent)
        self._conn, self._ctx, self._group = conn, ctx, group
        self.group_id: int | None = None if group is None else group.id
        creating = group is None

        if creating:
            years = school_years.usable(conn, ctx)
            self._years = {y.id: y for y in years}
            default_year = year_id if year_id in self._years else next(
                (y.id for y in years if y.state == "open"), years[0].id if years else None)
            self.year = id_combo([(y.label, y.id) for y in years], default_year)
        else:
            self._years = {}
            self.year = id_combo([(group.year_label, group.school_year_id)])
            self.year.setEnabled(False)
        self.level = id_combo(self._named("level", None if creating else group.level_id),
                              None if creating else group.level_id)
        self.subject = id_combo(self._named("subject", None if creating else group.subject_id),
                                None if creating else group.subject_id)
        self.name = QLineEdit("" if creating else group.name)
        self.name.setPlaceholderText(t["group_dialog.name_placeholder"])
        self.price = money_edit(None if creating else group.price)
        self.capacity = count_spin(12 if creating else group.capacity)
        self.start = DateLineEdit()
        self.teacher = id_combo([(x.full_name, x.id) for x in teachers.search(conn, ctx)])

        self.add(labeled(t["group_dialog.year"], self.year, required=True))
        self.add(row(labeled(t["group_dialog.level"], self.level, required=True),
                     labeled(t["group_dialog.subject"], self.subject, required=True)))
        self.add(labeled(t["group_dialog.name"], self.name, required=True))
        self.add(row(labeled(t["group_dialog.price"], self.price, required=True),
                     labeled(t["group_dialog.capacity"], self.capacity, required=True),
                     labeled(t["group_dialog.start"], self.start, required=True)))
        if creating:
            self.add(labeled(t["group_dialog.teacher"], self.teacher, required=True))
            if self.teacher.count() == 0:
                self.add(caption(t["group_dialog.no_teacher"]))
                self.submit.setEnabled(False)
            self.year.currentIndexChanged.connect(self._default_start)
            self._default_start()
        else:
            self.start.set_value(date.fromisoformat(group.start_date))
            note = caption(t["group_dialog.price_caption"])
            note.setWordWrap(True)
            self.add(note)
        self.finish(self.level if creating else self.name)

    def _named(self, kind: str, keep_id: int | None) -> list[tuple[str, int]]:
        """Active items, plus the group's current one even if it was deactivated."""
        return [(i.name, i.id) for i in catalog.list_items(self._conn, self._ctx, kind)
                if i.is_active or i.id == keep_id]

    def _default_start(self) -> None:
        """Start on the year's first day, or today if the year already started."""
        year = self._years.get(self.year.currentData())
        if year is None or self.start.isModified():
            return
        self.start.set_value(max(dates.today(), date.fromisoformat(year.start_date)))

    def _data(self) -> GroupInput:
        return GroupInput(
            school_year_id=required_id(self.year), level_id=required_id(self.level),
            subject_id=required_id(self.subject), name=self.name.text(),
            price=read_money(self.price), capacity=self.capacity.value(),
            start_date=required_date(self.start),
        )

    def save(self) -> None:
        data = self._data()
        if self._group is None:
            self.group_id = groups.create(self._conn, self._ctx, data, required_id(self.teacher))
        else:
            groups.update(self._conn, self._ctx, self._group.id, data)


class ChangeTeacherDialog(FormDialog):
    def __init__(self, conn, ctx: UserContext, group: Group, parent=None):
        super().__init__(t["change_teacher.title"], t["action.save"], parent=parent)
        self._conn, self._ctx, self._group = conn, ctx, group
        self.teacher = id_combo([(x.full_name, x.id) for x in teachers.search(conn, ctx)
                                 if x.id != group.teacher_id])
        self.valid_from = DateLineEdit()
        self.valid_from.set_value(dates.today())
        self.add(row(labeled(t["change_teacher.teacher"], self.teacher, required=True),
                     labeled(t["change_teacher.from"], self.valid_from, required=True)))
        if group.teacher:
            note = caption(t["change_teacher.caption"].format(current=group.teacher))
            note.setWordWrap(True)
            self.add(note)
        self.finish(self.teacher)

    def save(self) -> None:
        groups.change_teacher(self._conn, self._ctx, self._group.id, required_id(self.teacher),
                              required_date(self.valid_from))


def open_groups(conn, ctx: UserContext) -> list[Group]:
    """Groups that can get slots: not closed, in the open or an upcoming year."""
    usable = {y.id for y in school_years.usable(conn, ctx)}
    return [g for g in groups.search(conn, ctx)
            if g.status != "closed" and g.school_year_id in usable]


class SlotDialog(FormDialog):
    """Add a weekly slot, or edit / remove one. Group, room, day and start can be preset
    (from a group page or a click on the timetable grid)."""

    def __init__(self, conn, ctx: UserContext, slot: Slot | None = None,
                 group_id: int | None = None, room_id: int | None = None,
                 weekday: int | None = None, start: str | None = None, parent=None):
        key = "slot_dialog.new_title" if slot is None else "slot_dialog.edit_title"
        super().__init__(t[key], t["action.save"], parent=parent)
        self._conn, self._ctx, self._slot = conn, ctx, slot
        self.slot_id: int | None = None if slot is None else slot.id
        self.removed = False
        if slot is not None:
            group_id, room_id, weekday, start = (slot.group_id, slot.room_id, slot.weekday,
                                                 slot.start_time)
        self.group = id_combo([(g.title, g.id) for g in open_groups(conn, ctx)], group_id)
        # The group of an existing slot, or of a group page, does not change here.
        self.group.setEnabled(slot is None and group_id is None)
        room_items = [(f"{r.name} ({r.capacity})", r.id)
                      for r in rooms.list_rooms(conn, ctx, active_only=True)]
        self.room = id_combo(room_items, room_id)
        self.day = id_combo([(day_name(d), d) for d in WEEK_ORDER], weekday)
        # The lists offer the school's opening hours only (Paramètres, onglet École).
        opens_at, closes_at = settings.school_hours(conn)
        start = start or default_start(opens_at, closes_at)
        self.start = time_combo(start, opens_at, dates.add_minutes(closes_at, -STEP_MINUTES))
        end = slot.end_time if slot is not None else min(
            dates.add_minutes(start, DEFAULT_SLOT_MINUTES), closes_at)
        self.end = time_combo(end, dates.add_minutes(opens_at, STEP_MINUTES), closes_at)
        self._closes_at = closes_at
        self._end_touched = slot is not None
        self.start.currentTextChanged.connect(self._follow_start)
        self.end.activated.connect(self._touch_end)
        self.end.lineEdit().textEdited.connect(self._touch_end)

        self.add(labeled(t["slot_dialog.group"], self.group, required=True))
        self.add(row(labeled(t["slot_dialog.room"], self.room, required=True),
                     labeled(t["slot_dialog.day"], self.day, required=True)))
        self.add(row(labeled(t["slot_dialog.start"], self.start, required=True),
                     labeled(t["slot_dialog.end"], self.end, required=True)))
        if not room_items:
            self.add(caption(t["slot_dialog.no_rooms"]))
            self.submit.setEnabled(False)
        if slot is not None:
            self.remove = variant_button(t["slot_dialog.remove"], "danger")
            self.remove.clicked.connect(self._remove)
            self.add_left_action(self.remove)
        self.finish(self.room)

    def _touch_end(self, *_args) -> None:
        self._end_touched = True

    def _follow_start(self, text: str) -> None:
        """Keep a 1 h 30 slot while the end time has not been chosen."""
        if self._end_touched:
            return
        try:
            self.end.setCurrentText(min(dates.add_minutes(dates.parse_time(text),
                                                          DEFAULT_SLOT_MINUTES),
                                        self._closes_at))
        except ValidationError:
            pass  # reported on save

    def _data(self) -> SlotInput:
        return SlotInput(required_id(self.group), required_id(self.room), required_id(self.day),
                         read_time(self.start), read_time(self.end))

    def save(self) -> None:
        data = self._data()
        if self._slot is None:
            self.slot_id = timetable.add_slot(self._conn, self._ctx, data)
        else:
            self.slot_id = timetable.update_slot(self._conn, self._ctx, self._slot.id, data)

    def _remove(self) -> None:
        s = self._slot
        if not confirm(self, t["slots.confirm_remove_title"], t["slots.confirm_remove"].format(
                day=t[f"weekday.{s.weekday}"], start=s.start_time, end=s.end_time,
                group=s.group), t["slot_dialog.remove"]):
            return
        self.banner.clear_error()
        try:
            timetable.remove_slot(self._conn, self._ctx, s.id)
        except BusinessRuleError as exc:
            self.banner.show_error(exc.message)
            return
        self.removed = True
        self.accept()
