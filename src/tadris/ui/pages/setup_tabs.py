"""The lists of Paramètres → Structure, each opened whole in a window: years, holidays,
levels, subjects and rooms."""

from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from tadris.core.context import UserContext
from tadris.core.dates import display_date
from tadris.i18n.fr import t
from tadris.services import catalog, holidays, rooms, school_years
from tadris.ui.setup_dialogs import HolidayDialog, NameDialog, RoomDialog, YearDialog
from tadris.ui.theme.status import kind_for
from tadris.ui.widgets.common import ask, confirm, primary_button, toast, variant_button
from tadris.ui.widgets.forms import ListSection
from tadris.ui.widgets.tables import CENTER, item


class SetupTab(QWidget):
    """A caption over a ListSection; subclasses fill the rows in refresh()."""

    def __init__(self, conn, ctx: UserContext, caption: str, headers: list[str], empty: str):
        super().__init__()
        self._conn = conn
        self._ctx = ctx
        text = QLabel(caption)
        text.setObjectName("caption")
        text.setWordWrap(True)
        self.list = ListSection(headers, empty)
        self.list.selection_changed.connect(self._update_buttons)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 16, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(text)
        layout.addWidget(self.list, 1)

    def button(self, text: str, slot, variant: str | None = None) -> QPushButton:
        button = variant_button(text, variant) if variant else QPushButton(text)
        button.clicked.connect(slot)
        return self.list.add_button(button)

    def main_button(self, text: str, slot) -> QPushButton:
        button = primary_button(text)
        button.setDefault(False)
        button.clicked.connect(slot)
        return self.list.add_button(button, end=True)

    def refresh(self) -> None:
        raise NotImplementedError

    def _update_buttons(self) -> None:
        pass

    def _done(self, message: str, item_id: int | None = None) -> None:
        self.list.clear_error()
        self.refresh()
        if item_id is not None:
            self.list.select_id(item_id)
        toast(self, message)


class YearsTab(SetupTab):
    def __init__(self, conn, ctx: UserContext):
        super().__init__(conn, ctx, t["years.caption"], [
            t["years.col.label"], t["years.col.start"], t["years.col.end"],
            t["years.col.status"], t["years.col.groups"],
        ], t["years.empty"])
        self._years = {}
        self.edit = self.button(t["action.edit"], self._edit)
        self.open = self.button(t["years.open"], self._open)
        self.close_year = self.button(t["years.close"], self._close, "danger")
        self.new = self.main_button(t["years.new"], self._new)
        self.refresh()

    def refresh(self) -> None:
        years = school_years.list_years(self._conn, self._ctx)
        self._years = {y.id: y for y in years}
        self.list.set_rows([[
            item(y.label, item_id=y.id),
            item(display_date(y.start_date), y.start_date, align=CENTER),
            item(display_date(y.end_date), y.end_date, align=CENTER),
            item(t[f"year_state.{y.state}"], kind=kind_for("year", y.state)),
            item(str(y.group_count), y.group_count, align=CENTER),
        ] for y in years])

    def selected(self):
        return self._years.get(self.list.selected_id())

    def _update_buttons(self) -> None:
        year = self.selected()
        self.edit.setEnabled(year is not None)
        self.open.setEnabled(year is not None and school_years.can_open(year))
        self.close_year.setEnabled(year is not None and year.status == "open")

    def _new(self) -> None:
        dialog = YearDialog(self._conn, self._ctx, parent=self)
        if ask(dialog):
            label = school_years.get(self._conn, self._ctx, dialog.year_id).label
            self._done(t["years.created"].format(label=label), dialog.year_id)

    def _edit(self) -> None:
        year = self.selected()
        if year is None:
            return
        dialog = YearDialog(self._conn, self._ctx, year, parent=self)
        if ask(dialog):
            label = school_years.get(self._conn, self._ctx, year.id).label
            self._done(t["years.updated"].format(label=label), year.id)

    def _open(self) -> None:
        year = self.selected()
        if year is not None and self.list.run(school_years.open_year, self._conn, self._ctx,
                                              year.id):
            self._done(t["years.opened"].format(label=year.label), year.id)

    def _close(self) -> None:
        year = self.selected()
        if year is None:
            return
        if not confirm(self, t["years.confirm_close_title"],
                       t["years.confirm_close"].format(label=year.label, count=year.group_count),
                       t["years.close"]):
            return
        if self.list.run(school_years.close, self._conn, self._ctx, year.id):
            self._done(t["years.closed"].format(label=year.label, count=self.list.last_result),
                       year.id)


class CatalogTab(SetupTab):
    """Levels (with Monter / Descendre) or subjects."""

    def __init__(self, conn, ctx: UserContext, kind: str):
        plural = "levels" if kind == "level" else "subjects"
        super().__init__(conn, ctx, t[f"{plural}.caption"], [
            t["catalog.col.name"], t["catalog.col.status"], t["catalog.col.groups"],
        ], t[f"{plural}.empty"])
        self.kind = kind
        self._items = {}
        self.rename = self.button(t["action.rename"], self._rename)
        self.move_up = self.move_down = None
        if kind == "level":
            self.move_up = self.button(t["action.move_up"], lambda: self._move(-1))
            self.move_down = self.button(t["action.move_down"], lambda: self._move(1))
        self.toggle = self.button(t["action.deactivate"], self._toggle)
        self.new = self.main_button(t[f"{plural}.new"], self._new)
        self.refresh()

    def refresh(self) -> None:
        listed = catalog.list_items(self._conn, self._ctx, self.kind)
        self._items = {i.id: i for i in listed}
        self.list.set_rows([[
            item(i.name, item_id=i.id),
            item(t["active.yes" if i.is_active else "active.no"],
                 kind=kind_for("flag", "yes" if i.is_active else "no")),
            item(str(i.group_count), i.group_count, align=CENTER),
        ] for i in listed])

    def selected(self):
        return self._items.get(self.list.selected_id())

    def _update_buttons(self) -> None:
        current = self.selected()
        ids = self.list.ids()
        self.rename.setEnabled(current is not None)
        self.toggle.setEnabled(current is not None)
        self.toggle.setText(t["action.activate" if current is not None and not current.is_active
                              else "action.deactivate"])
        if self.move_up is not None:
            position = ids.index(current.id) if current is not None else -1
            self.move_up.setEnabled(position > 0)
            self.move_down.setEnabled(0 <= position < len(ids) - 1)

    def _new(self) -> None:
        dialog = NameDialog(self._conn, self._ctx, self.kind, parent=self)
        if ask(dialog):
            self._done(t["catalog.saved"].format(name=dialog.name.text().strip()), dialog.item_id)

    def _rename(self) -> None:
        current = self.selected()
        if current is None:
            return
        dialog = NameDialog(self._conn, self._ctx, self.kind, current, parent=self)
        if ask(dialog):
            self._done(t["catalog.saved"].format(name=dialog.name.text().strip()), current.id)

    def _toggle(self) -> None:
        current = self.selected()
        if current is not None and self.list.run(catalog.set_active, self._conn, self._ctx,
                                                 self.kind, current.id, not current.is_active):
            self._done(t["catalog.saved"].format(name=current.name), current.id)

    def _move(self, offset: int) -> None:
        current = self.selected()
        if current is not None and self.list.run(catalog.move_level, self._conn, self._ctx,
                                                 current.id, offset):
            self.refresh()
            self.list.select_id(current.id)


class RoomsTab(SetupTab):
    def __init__(self, conn, ctx: UserContext):
        super().__init__(conn, ctx, t["rooms.caption"], [
            t["rooms.col.name"], t["rooms.col.capacity"], t["rooms.col.status"],
            t["rooms.col.slots"],
        ], t["rooms.empty"])
        self._rooms = {}
        self.edit = self.button(t["action.edit"], self._edit)
        self.toggle = self.button(t["action.deactivate"], self._toggle)
        self.new = self.main_button(t["rooms.new"], self._new)
        self.refresh()

    def refresh(self) -> None:
        listed = rooms.list_rooms(self._conn, self._ctx)
        self._rooms = {r.id: r for r in listed}
        self.list.set_rows([[
            item(r.name, item_id=r.id),
            item(str(r.capacity), r.capacity, align=CENTER, mono=True),
            item(t[f"active.{'yes' if r.status == 'active' else 'no'}"],
                 kind=kind_for("room", r.status)),
            item(str(r.slot_count), r.slot_count, align=CENTER),
        ] for r in listed])

    def selected(self):
        return self._rooms.get(self.list.selected_id())

    def _update_buttons(self) -> None:
        room = self.selected()
        self.edit.setEnabled(room is not None)
        self.toggle.setEnabled(room is not None)
        inactive = room is not None and room.status != "active"
        self.toggle.setText(t["action.activate" if inactive else "action.deactivate"])

    def _new(self) -> None:
        dialog = RoomDialog(self._conn, self._ctx, parent=self)
        if ask(dialog):
            self._done(t["catalog.saved"].format(name=dialog.name.text().strip()), dialog.room_id)

    def _edit(self) -> None:
        room = self.selected()
        if room is None:
            return
        dialog = RoomDialog(self._conn, self._ctx, room, parent=self)
        if ask(dialog):
            self._done(t["catalog.saved"].format(name=dialog.name.text().strip()), room.id)

    def _toggle(self) -> None:
        room = self.selected()
        if room is not None and self.list.run(rooms.set_active, self._conn, self._ctx, room.id,
                                              room.status != "active"):
            self._done(t["catalog.saved"].format(name=room.name), room.id)


class HolidaysTab(SetupTab):
    def __init__(self, conn, ctx: UserContext):
        super().__init__(conn, ctx, t["holidays.caption"], [
            t["holidays.col.label"], t["holidays.col.start"], t["holidays.col.end"],
            t["holidays.col.days"],
        ], t["holidays.empty"])
        self._holidays = {}
        self.edit = self.button(t["action.edit"], self._edit)
        self.remove = self.button(t["holidays.remove"], self._remove, "danger")
        self.new = self.main_button(t["holidays.new"], self._new)
        self.list.activated.connect(lambda _id: self._edit())
        self.refresh()

    def refresh(self) -> None:
        listed = holidays.list_holidays(self._conn, self._ctx)
        self._holidays = {h.id: h for h in listed}
        self.list.set_rows([[
            item(h.label, item_id=h.id),
            item(display_date(h.start_date), h.start_date, align=CENTER),
            item(display_date(h.end_date), h.end_date, align=CENTER),
            item(str(h.days), h.days, align=CENTER),
        ] for h in listed])

    def selected(self):
        return self._holidays.get(self.list.selected_id())

    def _update_buttons(self) -> None:
        self.edit.setEnabled(self.selected() is not None)
        self.remove.setEnabled(self.selected() is not None)

    def _new(self) -> None:
        dialog = HolidayDialog(self._conn, self._ctx, parent=self)
        if ask(dialog):
            self._done(t["holidays.saved"].format(label=dialog.label.text().strip()),
                       dialog.holiday_id)

    def _edit(self) -> None:
        holiday = self.selected()
        if holiday is None:
            return
        dialog = HolidayDialog(self._conn, self._ctx, holiday, parent=self)
        if ask(dialog):
            self._done(t["holidays.saved"].format(label=dialog.label.text().strip()), holiday.id)

    def _remove(self) -> None:
        holiday = self.selected()
        if holiday is None or not confirm(
                self, t["holidays.confirm_remove_title"],
                t["holidays.confirm_remove"].format(label=holiday.label), t["holidays.remove"]):
            return
        if self.list.run(holidays.remove, self._conn, self._ctx, holiday.id):
            self._done(t["holidays.removed"].format(label=holiday.label))

