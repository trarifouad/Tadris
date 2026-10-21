from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from tadris.core.context import UserContext
from tadris.core.dates import display_date
from tadris.core.errors import BusinessRuleError
from tadris.core.money import format_dzd
from tadris.core.permissions import allowed
from tadris.core.text import fold
from tadris.domain.models import Group
from tadris.i18n.fr import t
from tadris.services import catalog, groups, school_years, subscriptions, timetable
from tadris.ui.group_dialogs import ChangeTeacherDialog, GroupDialog, SlotDialog, day_name
from tadris.ui.pages.group_students_tab import GroupStudentsTab
from tadris.ui.subscription_dialogs import BulkRenewDialog
from tadris.ui.theme.status import kind_for
from tadris.ui.widgets.common import (
    Badge,
    PageBanner,
    ask,
    confirm,
    primary_button,
    toast,
    variant_button,
)
from tadris.ui.widgets.forms import HeaderCard, ListDetailPage, ListSection, caption, padded
from tadris.ui.widgets.inputs import FilterButton, fill_combo, id_combo
from tadris.ui.widgets.tables import CENTER, item

SEARCH_DELAY_MS = 250
SEARCH_WIDTH = 420
OPEN, CLOSED, ALL = "open", "closed", "all"


class GroupsPage(ListDetailPage):
    def __init__(self, conn, ctx: UserContext):
        super().__init__(GroupListView(conn, ctx),
                         lambda group_id: GroupDetailView(conn, ctx, group_id))


class GroupListView(QWidget):
    opened = Signal(int)

    def __init__(self, conn, ctx: UserContext):
        super().__init__()
        self._conn = conn
        self._ctx = ctx
        self.setObjectName("page")
        self.manages = allowed(ctx, "group.manage")

        heading = QLabel(t["nav.groups"])
        heading.setObjectName("pageTitle")
        self.new_group = primary_button(t["groups.new"])
        self.new_group.setDefault(False)
        self.new_group.clicked.connect(self._create)
        self.new_group.setVisible(self.manages)
        head = QHBoxLayout()
        head.addWidget(heading)
        head.addStretch()
        head.addWidget(self.new_group)

        self.year = QComboBox()
        self.level = QComboBox()
        self.subject = QComboBox()
        self.status = id_combo([(t["groups.filter.open"], OPEN),
                                (t["groups.filter.closed"], CLOSED), (t["filter.all"], ALL)])
        self.search = QLineEdit()
        self.search.setPlaceholderText(t["groups.search"])
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(SEARCH_WIDTH)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(SEARCH_DELAY_MS)
        self._debounce.timeout.connect(self.refresh)
        self.search.textChanged.connect(self._debounce.start)
        self.filters = FilterButton()
        self.filters.add_filter(t["groups.filter.year"], self.year)
        self.filters.add_filter(t["groups.filter.level_label"], self.level)
        self.filters.add_filter(t["groups.filter.subject_label"], self.subject)
        self.filters.add_filter(t["groups.filter.status_label"], self.status, OPEN)
        self._load_filters()
        for combo in (self.year, self.level, self.subject, self.status):
            combo.currentIndexChanged.connect(self.refresh)
        filters = QHBoxLayout()
        filters.setSpacing(12)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.filters)
        filters.addStretch(1)

        self.list = ListSection([
            t["groups.col.name"], t["groups.col.subject"], t["groups.col.level"],
            t["groups.col.teacher"], t["groups.col.price"], t["groups.col.places"],
            t["groups.col.start"], t["groups.col.status"],
        ], "", sortable=True)
        self.list.activated.connect(self.opened.emit)
        self.count = caption()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 24)
        layout.setSpacing(16)
        layout.addLayout(head)
        layout.addLayout(filters)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.count)
        self.refresh()

    def _load_filters(self) -> None:
        """Years (open year first by default), levels and subjects, keeping the choices."""
        years = school_years.list_years(self._conn, self._ctx)
        default = next((y.id for y in years if y.state == "open"), years[0].id if years else None)
        fill_combo(self.year, [(y.label, y.id) for y in years],
                   self.year.currentData() if self.year.count() else default)
        fill_combo(self.level, [(t["groups.filter.level"], None)] + [
            (i.name, i.id) for i in catalog.list_items(self._conn, self._ctx, "level")],
            self.level.currentData())
        fill_combo(self.subject, [(t["groups.filter.subject"], None)] + [
            (i.name, i.id) for i in catalog.list_items(self._conn, self._ctx, "subject")],
            self.subject.currentData())
        self.filters.set_default(self.year, default)  # also recounts: fill_combo is silent

    def refresh(self) -> None:
        self._debounce.stop()
        self._load_filters()
        year_id = self.year.currentData()
        status = self.status.currentData()
        found = [] if year_id is None else groups.search(
            self._conn, self._ctx, year_id=year_id, level_id=self.level.currentData(),
            subject_id=self.subject.currentData(), query=self.search.text(),
            status="closed" if status == CLOSED else None)
        if status == OPEN:
            found = [g for g in found if g.status != "closed"]
        self.list.set_rows([self._cells(g) for g in found])
        self.list.empty.setText(self._empty_text(year_id))
        self.count.setText(t["groups.count"].format(count=len(found)))

    def _empty_text(self, year_id) -> str:
        if year_id is None:
            return t["groups.no_year"]
        filtered = (bool(self.search.text().strip()) or self.level.currentData() is not None
                    or self.subject.currentData() is not None)
        if filtered:
            return t["groups.no_match"]
        return t["groups.empty" if self.manages else "groups.empty_receptionist"]

    @staticmethod
    def _cells(g: Group) -> list:
        return [
            item(g.name, fold(g.name), item_id=g.id),
            item(g.subject, fold(g.subject)),
            item(g.level, fold(g.level)),
            item(g.teacher or "", fold(g.teacher or "")),
            item(format_dzd(g.price), g.price, align=CENTER, mono=True),
            item(f"{g.enrolled} / {g.seats}", (g.enrolled, g.seats), align=CENTER, mono=True),
            item(display_date(g.start_date), g.start_date, align=CENTER),
            item(t[f"group_state.{g.state}"], g.state, kind=kind_for("group", g.state)),
        ]

    def _create(self) -> None:
        dialog = GroupDialog(self._conn, self._ctx, year_id=self.year.currentData(), parent=self)
        if not ask(dialog):
            return
        group = groups.get(self._conn, self._ctx, dialog.group_id)
        toast(self, t["groups.created"].format(name=group.name))
        self.refresh()
        self.opened.emit(group.id)


class GroupDetailView(QWidget):
    back = Signal()

    def __init__(self, conn, ctx: UserContext, group_id: int):
        super().__init__()
        self._conn = conn
        self._ctx = ctx
        self.group_id = group_id
        self.setObjectName("page")
        self.manages = allowed(ctx, "group.manage")
        self.plans = allowed(ctx, "timetable.manage")

        self.back_button = variant_button(t["groups.back"], "ghost")

        self.back_button.setObjectName("backLink")
        self.back_button.clicked.connect(self.back.emit)
        back_row = QHBoxLayout()
        back_row.addWidget(self.back_button)
        back_row.addStretch()

        self.header = HeaderCard()
        self.status = self.header.add_meta(Badge())
        self.meta = self.header.add_meta(caption())
        self.teacher = self.header.add_meta(caption())
        self.price = self.header.add_meta(QLabel())
        self.price.setObjectName("mono")
        self.places = self.header.add_meta(caption())
        self.starts = self.header.add_meta(caption())
        self.header.close_meta()
        self.edit = self.header.add_action(QPushButton(t["action.edit"]))
        self.edit.clicked.connect(self._edit)
        self.change_teacher = self.header.add_action(
            QPushButton(t["group_detail.change_teacher"]))
        self.change_teacher.clicked.connect(self._change_teacher)
        self.close_group = self.header.add_action(
            variant_button(t["group_detail.close"], "danger"))
        self.close_group.clicked.connect(self._close)
        self.reopen = self.header.add_action(QPushButton(t["group_detail.reopen"]))
        self.reopen.clicked.connect(self._reopen)
        self.renew = self.header.add_action(QPushButton(t["group_detail.renew"]))
        self.renew.clicked.connect(self._renew)

        self.slots = ListSection([
            t["slots.col.day"], t["slots.col.time"], t["slots.col.room"], t["slots.col.from"],
        ], t["slots.empty"])
        self.add_slot = primary_button(t["slots.add"])
        self.add_slot.setDefault(False)
        self.add_slot.clicked.connect(self._add_slot)
        self.slots.add_button(self.add_slot, end=True)
        self.edit_slot = self.slots.add_button(QPushButton(t["action.edit"]))
        self.edit_slot.clicked.connect(self._edit_slot)
        self.slots.selection_changed.connect(
            lambda: self.edit_slot.setEnabled(self.slots.selected_id() is not None))
        if self.plans:
            self.slots.activated.connect(lambda _id: self._edit_slot())
        self.history = ListSection([
            t["history.col.teacher"], t["history.col.from"], t["history.col.to"],
        ], "")
        self.students = GroupStudentsTab(conn, ctx, group_id)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(padded(self.students), t["group_detail.tab.students"])
        self.tabs.addTab(padded(self.slots), t["group_detail.tab.slots"])
        self.tabs.addTab(padded(self.history), t["group_detail.tab.teachers"])

        self.error = PageBanner()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 14, 24, 24)
        layout.setSpacing(16)
        layout.addLayout(back_row)
        layout.addWidget(self.error)
        layout.addWidget(self.header)
        layout.addWidget(self.tabs, 1)
        self.refresh()

    def refresh(self) -> None:
        g = groups.get(self._conn, self._ctx, self.group_id)
        self.group = g
        self.header.title.setText(g.name)
        self.status.setText(t[f"group_state.{g.state}"])
        self.status.set_kind(kind_for("group", g.state))
        self.meta.setText(t["group_detail.meta"].format(subject=g.subject, level=g.level,
                                                        year=g.year_label))
        self.teacher.setText(t["group_detail.teacher"].format(teacher=g.teacher) if g.teacher
                             else t["group_detail.no_teacher"])
        self.price.setText(t["group_detail.price"].format(price=format_dzd(g.price)))
        if g.room_limited:
            self.places.setText(t["group_detail.places_room"].format(
                enrolled=g.enrolled, seats=g.seats, room=g.limiting_room, capacity=g.capacity))
        else:
            self.places.setText(t["group_detail.places"].format(enrolled=g.enrolled,
                                                                capacity=g.capacity))
        self.starts.setText(t["group_detail.starts"].format(date=display_date(g.start_date)))
        self.students.show_group(g)
        is_open = g.status != "closed"
        self.edit.setVisible(self.manages and is_open)
        self.change_teacher.setVisible(self.manages and is_open)
        self.close_group.setVisible(self.manages and is_open)
        self.reopen.setVisible(self.manages and not is_open)
        self.renew.setVisible(is_open and allowed(self._ctx, "subscription.manage"))
        self.add_slot.setVisible(self.plans and is_open)
        self.edit_slot.setVisible(self.plans and is_open)

        self._slots = {s.id: s for s in timetable.group_slots(self._conn, self._ctx, g.id)}
        self.slots.set_rows([[
            item(day_name(s.weekday), item_id=s.id),
            item(f"{s.start_time} – {s.end_time}", mono=True),
            item(s.room),
            item(display_date(s.valid_from), align=CENTER),
        ] for s in self._slots.values()])
        self.history.set_rows([[
            item(p.teacher, item_id=p.id),
            item(display_date(p.valid_from), align=CENTER),
            item(t["rates.current"] if p.valid_to is None else display_date(p.valid_to),
                 align=CENTER),
        ] for p in groups.teacher_history(self._conn, self._ctx, g.id)])

    def _done(self, message: str) -> None:
        self.error.clear_error()
        self.refresh()
        toast(self, message)

    def _edit(self) -> None:
        dialog = GroupDialog(self._conn, self._ctx, self.group, parent=self)
        if ask(dialog):
            self._done(t["groups.updated"].format(name=dialog.name.text().strip()))

    def _change_teacher(self) -> None:
        dialog = ChangeTeacherDialog(self._conn, self._ctx, self.group, parent=self)
        if ask(dialog):
            self._done(t["groups.teacher_changed"].format(
                name=self.group.name, teacher=dialog.teacher.currentText()))

    def _close(self) -> None:
        if confirm(self, t["group_detail.confirm_close_title"],
                   t["group_detail.confirm_close"].format(
                       name=self.group.name, enrolled=self.group.enrolled),
                   t["group_detail.close"]):
            self._run(groups.close, t["groups.closed_msg"].format(name=self.group.name))

    def _renew(self) -> None:
        months = subscriptions.renewable(self._conn, self._ctx, self.group_id)
        if not months:
            self.error.show_error(t["group_detail.nothing_to_renew"])
            return
        dialog = BulkRenewDialog(self._conn, self._ctx, months,
                                 t["group_detail.renew_title"].format(name=self.group.name),
                                 parent=self)
        if ask(dialog):
            self._done(t["bulk_renew.done"].format(count=len(dialog.renewed)))

    def _reopen(self) -> None:
        self._run(groups.reopen, t["groups.reopened"].format(name=self.group.name))

    def _run(self, action, message: str) -> None:
        try:
            action(self._conn, self._ctx, self.group_id)
        except BusinessRuleError as exc:
            self.error.show_error(exc.message)
            return
        self._done(message)

    def _add_slot(self) -> None:
        dialog = SlotDialog(self._conn, self._ctx, group_id=self.group_id, parent=self)
        if ask(dialog):
            self._done(t["slots.added"])

    def _edit_slot(self) -> None:
        slot = self._slots.get(self.slots.selected_id())
        if slot is None:
            return
        dialog = SlotDialog(self._conn, self._ctx, slot, parent=self)
        if ask(dialog):
            self._done(t["slots.removed" if dialog.removed else "slots.updated"])

