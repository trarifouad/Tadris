"""Paramètres → Structure: the school's skeleton, set up in this order: the school year (and
its holidays), the levels taught, the subjects, the rooms. One card per step, ✓ once it
holds something; « Gérer » opens its whole list in a window, with all its actions."""

from collections.abc import Callable

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from tadris.core import dates
from tadris.core.context import UserContext
from tadris.core.dates import display_date
from tadris.i18n.fr import t
from tadris.services import catalog, holidays, rooms, school_years
from tadris.ui.pages.setup_tabs import CatalogTab, HolidaysTab, RoomsTab, YearsTab
from tadris.ui.theme.status import kind_for
from tadris.ui.widgets.common import Badge
from tadris.ui.widgets.compact import StepCard, rule, small
from tadris.ui.widgets.flow import chips_box, set_chips
from tadris.ui.widgets.forms import SectionWindow, caption

# What « Gérer » opens: the window's title and the list it shows.
LISTS: dict[str, tuple[str, Callable]] = {
    "years": ("structure.window.years", YearsTab),
    "holidays": ("structure.window.holidays", HolidaysTab),
    "levels": ("structure.window.levels", lambda conn, ctx: CatalogTab(conn, ctx, "level")),
    "subjects": ("structure.window.subjects",
                 lambda conn, ctx: CatalogTab(conn, ctx, "subject")),
    "rooms": ("structure.window.rooms", RoomsTab),
}


def hint(text: str = "") -> QLabel:
    label = caption(text)
    label.setWordWrap(True)
    return label


class StructureSection(QWidget):
    def __init__(self, conn, ctx: UserContext):
        super().__init__()
        self._conn, self._ctx = conn, ctx
        intro = hint(t["structure.caption"])

        manage = t["settings.manage"]
        self.years = StepCard(1, t["structure.years"], manage)
        self.year = QLabel()
        self.year.setObjectName("summaryTitle")
        self.year_state = Badge()
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_row.addWidget(self.year)
        title_row.addWidget(self.year_state)
        title_row.addStretch()
        self.year_detail = hint()
        self.next_year = hint()
        self.holidays_text = hint()
        self.manage_holidays = small(QPushButton(t["structure.manage_holidays"]))
        self.manage_holidays.setAutoDefault(False)
        holidays_row = QHBoxLayout()
        holidays_row.setSpacing(8)
        holidays_row.addWidget(self.holidays_text, 1)
        holidays_row.addWidget(self.manage_holidays)
        self.years.body.addLayout(title_row)
        self.years.body.addWidget(self.year_detail)
        self.years.body.addWidget(self.next_year)
        self.years.body.addWidget(rule())
        self.years.body.addLayout(holidays_row)

        self.levels, self.level_chips, self.levels_empty = self._chips_step(
            2, "structure.levels", "structure.levels_empty")
        self.subjects, self.subject_chips, self.subjects_empty = self._chips_step(
            3, "structure.subjects", "structure.subjects_empty")
        self.rooms, self.room_chips, self.rooms_empty = self._chips_step(
            4, "structure.rooms", "structure.rooms_empty")

        for button, key in ((self.years.manage, "years"), (self.manage_holidays, "holidays"),
                            (self.levels.manage, "levels"), (self.subjects.manage, "subjects"),
                            (self.rooms.manage, "rooms")):
            button.clicked.connect(lambda _on=False, k=key: self.open_list(k))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(intro)
        for step in (self.years, self.levels, self.subjects, self.rooms):
            layout.addWidget(step)
        self.refresh()

    @staticmethod
    def _chips_step(number: int, title: str, empty: str):
        step = StepCard(number, t[title], t["settings.manage"])
        box, chips = chips_box()
        none = hint(t[empty])
        step.body.addWidget(box)
        step.body.addWidget(none)
        return step, chips, none

    # ----- the summaries -----

    def refresh(self) -> None:
        self._show_years()
        self._show_holidays()
        levels = catalog.list_items(self._conn, self._ctx, "level")
        self._show_chips(self.levels, self.level_chips, self.levels_empty,
                         [(i.name, i.is_active) for i in levels])
        subjects = catalog.list_items(self._conn, self._ctx, "subject")
        self._show_chips(self.subjects, self.subject_chips, self.subjects_empty,
                         [(i.name, i.is_active) for i in subjects])
        listed = rooms.list_rooms(self._conn, self._ctx)
        self._show_chips(self.rooms, self.room_chips, self.rooms_empty,
                         [(t["structure.room_chip"].format(name=r.name, capacity=r.capacity),
                           r.status == "active") for r in listed])

    def _show_years(self) -> None:
        years = school_years.list_years(self._conn, self._ctx)
        current = next((y for y in years if y.state == "open"), None)
        coming = sorted((y for y in years if y.state == "upcoming"), key=lambda y: y.start_date)
        self.years.set_done(current is not None)
        self.year.setVisible(current is not None)
        self.year_state.setVisible(current is not None)
        if current is not None:
            self.year.setText(current.label)
            self.year_state.setText(t[f"year_state.{current.state}"])
            self.year_state.set_kind(kind_for("year", current.state))
            self.year_detail.setText(t["structure.year_dates"].format(
                start=display_date(current.start_date), end=display_date(current.end_date),
                groups=current.group_count))
        else:
            self.year_detail.setText(t["structure.no_open_year" if years else "structure.no_year"])
        self.next_year.setVisible(bool(coming))
        if coming:
            self.next_year.setText(t["structure.year_next"].format(
                label=coming[0].label, start=display_date(coming[0].start_date)))

    def _show_holidays(self) -> None:
        listed = holidays.list_holidays(self._conn, self._ctx)
        today = dates.iso(dates.today())
        coming = sorted((h for h in listed if h.end_date >= today), key=lambda h: h.start_date)
        if not listed:
            self.holidays_text.setText(t["structure.no_holidays"])
        elif coming:
            nxt = coming[0]
            period = (t["structure.holiday_day"].format(day=display_date(nxt.start_date))
                      if nxt.start_date == nxt.end_date else
                      t["structure.holiday_period"].format(start=display_date(nxt.start_date),
                                                           end=display_date(nxt.end_date)))
            self.holidays_text.setText(t["structure.holidays"].format(
                count=len(listed), label=nxt.label, period=period))
        else:
            self.holidays_text.setText(t["structure.holidays_past"].format(count=len(listed)))

    @staticmethod
    def _show_chips(step: StepCard, chips, empty: QLabel, items: list[tuple[str, bool]]) -> None:
        set_chips(chips, items)
        step.set_done(any(in_use for _text, in_use in items))
        chips.parentWidget().setVisible(bool(items))
        empty.setVisible(not items)

    # ----- the whole lists -----

    def open_list(self, key: str) -> SectionWindow:
        """The step's whole list in a window, with all its actions; the summaries are read
        again once it is closed."""
        title, make = LISTS[key]
        window = SectionWindow(t[title], make(self._conn, self._ctx), self)
        window.exec()
        self.refresh()
        return window
