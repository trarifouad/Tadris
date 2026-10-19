"""Dialogs for the school structure kept in Paramètres: years, levels, subjects, rooms,
holidays."""

from datetime import date

from PySide6.QtWidgets import QLineEdit

from tadris.core.context import UserContext
from tadris.core.dates import parse_display_date
from tadris.core.errors import ValidationError
from tadris.domain.models import Holiday, NamedItem, Room, SchoolYear
from tadris.i18n.fr import t
from tadris.services import catalog, holidays, rooms, school_years
from tadris.ui.widgets.common import labeled
from tadris.ui.widgets.date_edit import DateLineEdit
from tadris.ui.widgets.forms import FormDialog, caption, row
from tadris.ui.widgets.inputs import count_spin


def required_date(field: DateLineEdit) -> date:
    value = parse_display_date(field.text())
    if value is None:
        raise ValidationError(t["date.invalid"])
    return value


class YearDialog(FormDialog):
    def __init__(self, conn, ctx: UserContext, year: SchoolYear | None = None, parent=None):
        key = "year_dialog.new_title" if year is None else "year_dialog.edit_title"
        super().__init__(t[key], t["action.save"], parent=parent)
        self._conn, self._ctx, self._year = conn, ctx, year
        self.year_id: int | None = None if year is None else year.id
        self.label = QLineEdit()
        self.label.setPlaceholderText("2026-2027")
        self.start = DateLineEdit()
        self.end = DateLineEdit()
        if year is not None:
            self.label.setText(year.label)
            self.start.set_value(date.fromisoformat(year.start_date))
            self.end.set_value(date.fromisoformat(year.end_date))
        else:
            # Suggest the label from the first day while the user has not typed one.
            self.start.textChanged.connect(self._suggest_label)
        self.add(labeled(t["year_dialog.label"], self.label, required=True))
        self.add(row(labeled(t["year_dialog.start"], self.start, required=True),
                     labeled(t["year_dialog.end"], self.end, required=True)))
        self.finish(self.label if year is not None else self.start)

    def _suggest_label(self) -> None:
        start = self.start.value()
        if start is not None and not self.label.isModified():
            self.label.setText(school_years.suggest_label(start))

    def save(self) -> None:
        start, end = required_date(self.start), required_date(self.end)
        if self._year is None:
            self.year_id = school_years.create(self._conn, self._ctx, self.label.text(),
                                               start, end)
        else:
            school_years.update(self._conn, self._ctx, self._year.id, self.label.text(),
                                start, end)


class NameDialog(FormDialog):
    """New or renamed level or subject."""

    def __init__(self, conn, ctx: UserContext, kind: str, item: NamedItem | None = None,
                 parent=None):
        key = f"name_dialog.{kind}_{'new' if item is None else 'edit'}"
        super().__init__(t[key], t["action.save"], parent=parent)
        self._conn, self._ctx, self._kind, self._item = conn, ctx, kind, item
        self.item_id: int | None = None if item is None else item.id
        self.name = QLineEdit("" if item is None else item.name)
        self.add(labeled(t["name_dialog.name"], self.name, required=True))
        self.finish(self.name)

    def save(self) -> None:
        if self._item is None:
            self.item_id = catalog.create(self._conn, self._ctx, self._kind, self.name.text())
        else:
            catalog.rename(self._conn, self._ctx, self._kind, self._item.id, self.name.text())


class RoomDialog(FormDialog):
    def __init__(self, conn, ctx: UserContext, room: Room | None = None, parent=None):
        key = "room_dialog.new_title" if room is None else "room_dialog.edit_title"
        super().__init__(t[key], t["action.save"], parent=parent)
        self._conn, self._ctx, self._room = conn, ctx, room
        self.room_id: int | None = None if room is None else room.id
        self.name = QLineEdit("" if room is None else room.name)
        self.capacity = count_spin(20 if room is None else room.capacity)
        self.add(row(labeled(t["room_dialog.name"], self.name, required=True),
                     labeled(t["room_dialog.capacity"], self.capacity, required=True)))
        self.finish(self.name)

    def save(self) -> None:
        if self._room is None:
            self.room_id = rooms.create(self._conn, self._ctx, self.name.text(),
                                        self.capacity.value())
        else:
            rooms.update(self._conn, self._ctx, self._room.id, self.name.text(),
                         self.capacity.value())


class HolidayDialog(FormDialog):
    """A period off (both days included); leave the end empty for a single day."""

    def __init__(self, conn, ctx: UserContext, holiday: Holiday | None = None, parent=None):
        key = "holiday_dialog.new_title" if holiday is None else "holiday_dialog.edit_title"
        super().__init__(t[key], t["action.save"], parent=parent)
        self._conn, self._ctx, self._holiday = conn, ctx, holiday
        self.holiday_id: int | None = None if holiday is None else holiday.id
        self.label = QLineEdit()
        self.label.setPlaceholderText(t["holiday_dialog.placeholder"])
        self.start = DateLineEdit()
        self.end = DateLineEdit()
        if holiday is not None:
            self.label.setText(holiday.label)
            self.start.set_value(date.fromisoformat(holiday.start_date))
            if holiday.end_date != holiday.start_date:
                self.end.set_value(date.fromisoformat(holiday.end_date))
        self.add(labeled(t["holiday_dialog.label"], self.label, required=True))
        self.add(row(labeled(t["holiday_dialog.start"], self.start, required=True),
                     labeled(t["holiday_dialog.end"], self.end)))
        note = caption(t["holiday_dialog.caption"])
        note.setWordWrap(True)
        self.add(note)
        self.finish(self.label)

    def save(self) -> None:
        start = required_date(self.start)
        end = parse_display_date(self.end.text()) if self.end.text().strip() else None
        if self._holiday is None:
            self.holiday_id = holidays.create(self._conn, self._ctx, self.label.text(), start,
                                              end)
        else:
            holidays.update(self._conn, self._ctx, self._holiday.id, self.label.text(), start,
                            end)
