"""What a student has left to pay, as the desk reads it: a few figures (late, due within a
week, to come, credit), then the lines grouped by urgency, each one ticked or paid on its own.

Late (red): due on or before today. Due soon (amber): within DUE_SOON_DAYS. To come
(grey): later, months renewed ahead; folded away so they never inflate what is owed now. The
figures are after the credit, which pays the oldest lines first (as a payment would)."""

from dataclasses import dataclass
from datetime import date, timedelta

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tadris.core.dates import display_date, short_period
from tadris.core.money import format_dzd
from tadris.domain.models import ChargeDue, Debt
from tadris.i18n.fr import t
from tadris.ui.theme import tokens
from tadris.ui.theme.delegates import EDGE_WIDTH, TEXT_INSET, BadgeDelegate
from tadris.ui.widgets.common import primary_button
from tadris.ui.widgets.tables import ID_ROLE, RIGHT, fill, fit_columns, item, ruled_table

DUE_SOON_DAYS = 7
LATE, SOON, LATER = "late", "soon", "later"
GROUPS = (LATE, SOON, LATER)
KINDS = {LATE: "danger", SOON: "warning", LATER: "neutral"}
# A pill drawn at the end of a cell's text: (text, kind).
PILL_ROLE = Qt.ItemDataRole.UserRole + 20
# A row drawn with a thin coloured edge on its leading side: a kind.
EDGE_ROLE = Qt.ItemDataRole.UserRole + 21
COLUMNS = 6  # tick, item, period, due date, left, « Encaisser »


def urgency(c: ChargeDue, today: date) -> str:
    due = date.fromisoformat(c.due_date)
    if due <= today:
        return LATE
    if due <= today + timedelta(days=DUE_SOON_DAYS):
        return SOON
    return LATER


@dataclass(frozen=True)
class Buckets:
    late: int
    soon: int
    later: int
    credit: int  # what is left of the credit once every line is paid


def buckets(d: Debt, today: date) -> Buckets:
    """What is owed by urgency, the credit taken off the oldest first."""
    sums = dict.fromkeys(GROUPS, 0)
    for c in d.charges:
        sums[urgency(c, today)] += c.due
    credit = d.credit
    net = {}
    for key in GROUPS:
        taken = min(credit, sums[key])
        net[key] = sums[key] - taken
        credit -= taken
    return Buckets(late=net[LATE], soon=net[SOON], later=net[LATER], credit=credit)


def tabular(font: QFont | None = None, size: int = 13) -> QFont:
    """The UI font with figures of one width, so amounts line up without a monospace."""
    font = QFont(font) if font is not None else QFont()
    font.setPixelSize(size)
    font.setFeature(QFont.Tag("tnum"), 1)
    return font


def designation(c: ChargeDue) -> str:
    """A month: its group's name (« Physique 4AM »); the fee: its own line."""
    return c.group_name or c.description


def left_text(c: ChargeDue) -> str:
    """What is left, or « 1 000 / 2 500 DA » once part of it was paid."""
    if c.paid:
        return t["dues.left_of"].format(left=format_dzd(c.due).removesuffix(" DA"),
                                        amount=format_dzd(c.amount))
    return format_dzd(c.due)


# ----- the figures -----

class StatBlock(QFrame):
    def __init__(self, label: str, kind: str):
        super().__init__()
        self.setObjectName("statBlock")
        self.setProperty("kind", kind)
        self.label = QLabel(label)
        self.label.setObjectName("statLabel")
        self.value = QLabel()
        self.value.setObjectName("statValue")
        self.value.setProperty("kind", kind)
        self.value.setFont(tabular(self.value.font(), 17))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(0)
        layout.addWidget(self.label)
        layout.addWidget(self.value)


class StatBlocks(QWidget):
    """« Crédit », only when money paid ahead is left once every line is paid (the lines
    themselves say what is late, due soon or to come)."""

    def __init__(self):
        super().__init__()
        self.credit = StatBlock(t["dues.stat.credit"], "info")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.credit)
        layout.addStretch()

    def set_buckets(self, b: Buckets) -> None:
        self.credit.value.setText(format_dzd(b.credit))
        self.credit.setVisible(b.credit > 0)
        self.setVisible(b.credit > 0)


# ----- the lines -----

class DueDelegate(BadgeDelegate):
    """Badges as in every list; a pill after a cell's text (PILL_ROLE); a thin coloured edge
    on the leading side of a row (EDGE_ROLE, on its first cell)."""

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        edge = index.data(EDGE_ROLE)
        if edge and index.column() == 0:
            painter.fillRect(QRect(option.rect.left(), option.rect.top(), EDGE_WIDTH,
                                   option.rect.height()), QColor(self._tokens[edge]))

    def paint_content(self, painter, option, index) -> None:
        pill = index.data(PILL_ROLE)
        if not pill:
            super().paint_content(painter, option, index)
            return
        text, kind = pill
        font = QFont(option.font)
        font.setPixelSize(11)
        font.setWeight(QFont.Weight.Medium)
        metrics = QFontMetrics(font)
        width, height = metrics.horizontalAdvance(text) + 14, metrics.height() + 2
        label = index.data(Qt.ItemDataRole.DisplayRole) or ""
        room = option.rect.width() - TEXT_INSET - width - 12
        shown = QFontMetrics(option.font).elidedText(label, Qt.TextElideMode.ElideRight,
                                                     max(room, 0))
        painter.save()
        painter.setFont(option.font)
        painter.setPen(QColor(self._tokens["text"]))
        text_rect = option.rect.adjusted(TEXT_INSET, 0, 0, 0)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         shown)
        left = option.rect.left() + TEXT_INSET + QFontMetrics(option.font).horizontalAdvance(
            shown) + 8
        rect = QRect(left, option.rect.center().y() - height // 2 + 1, width, height)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._tokens[f"{kind}_bg"]))
        painter.drawRoundedRect(rect, 4, 4)
        painter.setPen(QColor(self._tokens[kind]))
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()


class DueGroup(QWidget):
    """One urgency: a header that folds the lines (« À venir · 4 échéances · 10 000 DA »),
    then the lines."""

    ticked = Signal()
    pay_one = Signal(int)

    def __init__(self, key: str, open_: bool, can_pay: bool):
        super().__init__()
        self.key = key
        self.can_pay = can_pay
        self.charges: list[ChargeDue] = []
        self._title = ""
        self.header = QPushButton()
        self.header.setObjectName("dueGroup")
        self.header.setProperty("kind", KINDS[key])
        self.header.setCheckable(True)
        self.header.setChecked(open_)
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.toggled.connect(self._toggled)
        self.table = ruled_table(["", t["payments_tab.col.item"], t["payments_tab.col.period"],
                                  t["payments_tab.col.due_date"], t["payments_tab.col.left"],
                                  ""])
        self.table.setItemDelegate(DueDelegate(tokens(), self.table))
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.horizontalHeader().hide()
        fit_columns(self.table, stretch=(1,))
        if can_pay:  # a cell widget does not size its column: the button's own width
            probe = QPushButton(t["dues.pay_one"])
            probe.setObjectName("link")
            self.table.horizontalHeader().setSectionResizeMode(
                5, self.table.horizontalHeader().ResizeMode.Fixed)
            self.table.setColumnWidth(5, probe.sizeHint().width() + 28)
        else:
            self.table.setColumnHidden(5, True)
        self.table.itemChanged.connect(self._item_changed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.header)
        layout.addWidget(self.table)

    def set_charges(self, charges: list[ChargeDue], keep: set[int]) -> None:
        self.charges = charges
        self.table.blockSignals(True)
        try:
            fill(self.table, [self._cells(c, c.id in keep) for c in charges])
            for r, c in enumerate(charges):
                if self.can_pay:
                    button = QPushButton(t["dues.pay_one"])
                    button.setObjectName("link")
                    button.setCursor(Qt.CursorShape.PointingHandCursor)
                    button.clicked.connect(lambda _checked=False, i=c.id: self.pay_one.emit(i))
                    self.table.setCellWidget(r, 5, button)
        finally:
            self.table.blockSignals(False)
        total = sum(c.due for c in charges)
        self._title = t["dues.group"].format(
            name=t[f"dues.group.{self.key}"], count=len(charges),
            plural="s" if len(charges) > 1 else "", total=format_dzd(total))
        self.setVisible(bool(charges))
        self._toggled(self.header.isChecked())

    def _cells(self, c: ChargeDue, ticked: bool) -> list:
        tick = QTableWidgetItem()
        tick.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
        tick.setCheckState(Qt.CheckState.Checked if ticked else Qt.CheckState.Unchecked)
        tick.setData(ID_ROLE, c.id)
        name = item(designation(c))
        name.setToolTip(c.description)
        late = self.key == LATE
        if late:
            name.setData(PILL_ROLE, (t["dues.badge.late"], "danger"))
            tick.setData(EDGE_ROLE, "danger")
        period = short_period(c.start_date, c.end_date) if c.start_date and c.end_date else "—"
        left = item(left_text(c), align=RIGHT, tone="danger" if late else None)
        left.setFont(tabular())
        return [tick, name, item(period), item(display_date(c.due_date), c.due_date), left,
                item("")]

    def ticked_ids(self) -> list[int]:
        return [self.table.item(r, 0).data(ID_ROLE) for r in range(self.table.rowCount())
                if self.table.item(r, 0).checkState() == Qt.CheckState.Checked]

    def set_ticked(self, ids: set[int]) -> None:
        self.table.blockSignals(True)
        try:
            for r in range(self.table.rowCount()):
                cell = self.table.item(r, 0)
                cell.setCheckState(Qt.CheckState.Checked if cell.data(ID_ROLE) in ids
                                   else Qt.CheckState.Unchecked)
        finally:
            self.table.blockSignals(False)
        self.ticked.emit()

    def _item_changed(self, cell) -> None:
        if cell.column() == 0:
            self.ticked.emit()

    def _toggled(self, open_: bool) -> None:
        self.header.setText(f"{self._title} {'▾' if open_ else '▸'}")
        self.header.setProperty("open", open_)
        self.header.style().unpolish(self.header)
        self.header.style().polish(self.header)
        self.table.setVisible(open_ and bool(self.charges))
        self.table.setFixedHeight(self.table.verticalHeader().defaultSectionSize()
                                  * len(self.charges) + 2)


class DuesView(QWidget):
    """The lines left to pay, grouped by urgency (late and due soon open, to come folded),
    with a tick on each; a bar sums what is ticked and pays it in one go."""

    pay = Signal(list)  # charge ids to pay

    def __init__(self, can_pay: bool):
        super().__init__()
        self.groups = {key: DueGroup(key, key != LATER, can_pay) for key in GROUPS}
        self.empty = QLabel(t["payments_tab.nothing_due"])
        self.empty.setObjectName("emptyState")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        self.bar = QFrame()
        self.bar.setObjectName("selectionBar")
        self.bar_text = QLabel()
        self.bar_text.setObjectName("selectionText")
        self.pay_selection = primary_button(t["dues.pay_selection"])
        self.pay_selection.setDefault(False)
        self.pay_selection.setAutoDefault(False)
        self.pay_selection.clicked.connect(lambda: self.pay.emit(self.ticked_ids()))
        self.pay_selection.setVisible(can_pay)
        bar = QHBoxLayout(self.bar)
        bar.setContentsMargins(14, 8, 8, 8)
        bar.addWidget(self.bar_text, 1)
        bar.addWidget(self.pay_selection)
        self.bar.hide()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self.bar)
        for group in self.groups.values():
            group.ticked.connect(self._ticked)
            group.pay_one.connect(lambda charge_id: self.pay.emit([charge_id]))
            layout.addWidget(group)
        layout.addWidget(self.empty)
        self.charges: dict[int, ChargeDue] = {}

    def set_debt(self, d: Debt, today: date) -> None:
        keep = set(self.ticked_ids())
        self.charges = {c.id: c for c in d.charges}
        keep &= set(self.charges)
        for key, group in self.groups.items():
            group.set_charges([c for c in d.charges if urgency(c, today) == key], keep)
        self.empty.setVisible(not d.charges)
        self._ticked()

    def ticked_ids(self) -> list[int]:
        return [i for group in self.groups.values() for i in group.ticked_ids()]

    def urgent_ids(self) -> list[int]:
        """What is late or due soon: what « Encaisser un paiement » ticks first."""
        return [c.id for key in (LATE, SOON) for c in self.groups[key].charges]

    def _ticked(self) -> None:
        ids = self.ticked_ids()
        self.bar.setVisible(bool(ids))
        total = sum(self.charges[i].due for i in ids if i in self.charges)
        self.bar_text.setText(t["dues.selection"].format(
            count=len(ids), plural="s" if len(ids) > 1 else "", total=format_dzd(total)))
