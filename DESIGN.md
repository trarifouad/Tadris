# Tadris Design System: Encre

Built from the objects a tutoring school handles every day. Each object has one job in the interface, so every color carries a meaning:

| Object | Job |
|---|---|
| **Encre violette** (the school ink) | Sidebar and primary button, one per screen. Also the focus ring. |
| **Cachet** (the stamp, same ink) | The PAYÉ mark on settled receipts and the receipt number box. Used rarely, like the real stamp. |
| **Cahier Seyès** (the ruled notebook) | Table rhythm: fine blue rules between rows, a stronger rule every fifth row. |
| **Stylo rouge** (the red correction pen) | Errors, debts and destructive actions only. |

If a new screen seems to need a color that is not listed here, it probably needs one of these jobs instead. Everything is defined as tokens, so a theme change means editing one file.

---

## 1. Fonts

| Role | Font | Why |
|---|---|---|
| Display | **Reem Kufi** | Kufi-rooted geometric face. Page titles, dialog titles, big numbers and the wordmark only. |
| UI and body | **Readex Pro** | Legible at 13 px, draws Latin and Arabic from one design, so the Arabic release needs no new font |
| Amounts, receipt numbers, IDs | **IBM Plex Mono** | Digits align in columns |

All three are open source (OFL). Bundle them in `ui/resources/fonts/`, because the app is offline and installed fonts cannot be relied on. Load them at startup with `QFontDatabase.addApplicationFont`, and set the fallback chain: `Readex Pro, Segoe UI, sans-serif`.

### Type scale

| Style | Size / weight | Face | Use |
|---|---|---|---|
| Page title | 24 px / 600 | Reem Kufi | Top of each page |
| Dialog title | 18 px / 600 | Reem Kufi | Dialog headers |
| Big number | 30 px / 600 | Reem Kufi | Dashboard cards |
| Section title | 16 px / 500 | Readex Pro | Cards, groups of fields |
| Body | 14 px / 400 | Readex Pro | Forms, labels, inputs |
| Table text | 13 px / 400 | Readex Pro | Rows, dense lists |
| Table header | 11.5 px / 500, uppercase, tracking +6% | Readex Pro | Column headers |
| Caption | 12 px / 400, muted | Readex Pro | Hints, timestamps |
| Money and IDs | 13 px / 500, centered in tables | Plex Mono | Every amount column, receipt and student numbers |

Use pixel sizes in QSS (not pt) so Windows scaling stays predictable. Line height is about 1.4 to 1.5.

---

## 2. Colors

### Light theme (ships first)

| Group | Token | Hex | Use |
|---|---|---|---|
| Ink | `primary` | `#5A3E9E` | **Primary buttons, links, stamp, focus ring** |
| | `primary_hover` | `#6B4FB3` | Button hover |
| | `primary_pressed` | `#48307F` | Button pressed |
| | `primary_soft` | `#EEEAF7` | Selected row, subtle fills |
| | `on_primary` | `#FFFFFF` | Text on primary |
| | `sidebar` | `#2E2152` | **Sidebar background** |
| | `sidebar_hover` | `#3A2B66` | Sidebar item hover |
| | `chalk` | `#ECE8F5` | Sidebar text, active sidebar item background |
| Paper | `bg` | `#F4F3F7` | App background |
| | `surface` | `#FFFFFF` | Cards, tables, dialogs |
| | `surface_alt` | `#ECEAF2` | Table header, hover rows, disabled fields |
| | `border` | `#DEDBE7` | Dividers, card borders |
| | `border_strong` | `#C3BED2` | Input borders |
| Text | `text` | `#1D1830` | Main text |
| | `muted` | `#5D5870` | Secondary text |
| | `faint` | `#928DA3` | Placeholders and disabled text only |
| Seyès | `rule` | `#CBD6EA` | Row dividers |
| | `rule_strong` | `#9DB0D4` | Every fifth row, under the table header |

Neutrals lean slightly violet toward the ink instead of a plain blue-grey.

### Semantic colors

| Meaning | Text | Background | Dark text | Dark background |
|---|---|---|---|---|
| Success | `#2B7A33` | `#E1F2DF` | `#78CF84` | `#16301B` |
| Warning | `#9A5A06` | `#FBEFD3` | `#F0B85A` | `#33270F` |
| Danger (red pen) | `#BE2A2F` | `#FBE3E2` | `#FF8E86` | `#3A1A19` |
| Info (Seyès blue) | `#2E529E` | `#E3EAF8` | `#93B2F4` | `#18243D` |
| Neutral | `#5A5868` | `#E9E7EF` | `#B3AEC0` | `#2A2635` |

None of the semantic colors is close to the violet, so a status badge never reads as a button.

### Dark theme (after the pilot, same token names)

| Token | Hex |
|---|---|
| `primary` | `#B9A3F5` (text on it: `on_primary` `#1C1236`) |
| `primary_hover` / `primary_pressed` | `#CBB9FA` / `#A28BE8` |
| `primary_soft` | `#2A2140` |
| `sidebar` / `sidebar_hover` | `#120D1F` / `#1D1630` |
| `chalk` | `#E2DCF0` |
| `bg` / `surface` / `surface_alt` | `#110F18` / `#1A1724` / `#221E2E` |
| `border` / `border_strong` | `#302B3E` / `#423B53` |
| `text` / `muted` / `faint` | `#E9E6F0` / `#A6A0B5` / `#77718A` |
| `rule` / `rule_strong` | `#26344D` / `#3A4F7C` |

### Contrast

| Pair | Light | Dark |
|---|---|---|
| `text` on `surface` | 17.1:1 | 14.3:1 |
| `muted` on `surface` | 6.8:1 | 7.0:1 |
| `on_primary` on `primary` | 8.0:1 | 8.1:1 |
| `primary` on `surface` | 8.0:1 | 8.1:1 |
| `chalk` on `sidebar` | 12.0:1 | 14.3:1 |
| Semantic text on its soft background | at least 4.6:1 | at least 6.5:1 |

`faint` is below 4.5:1 on purpose and is never used for text that must be read.

---

## 3. Spacing, shape, sizes

| Token | Value |
|---|---|
| Spacing scale | 4, 8, 12, 16, 24, 32 px |
| Radius | 4 badges, 6 inputs and buttons, 10 cards and dialogs |
| Control height | 36 px (inputs, buttons), 30 px compact |
| Table row | 40 px normal, 32 px compact (toggle in settings) |
| Top bar | 56 px |
| Sidebar | 216 px expanded, 64 px collapsed |
| Page padding | 24 px, card padding 16 to 20 px |
| Dialog widths | 480 px (simple), 640 px (forms), 880 px (payment, enrollment) |
| Focus ring | 2 px `primary` border plus a soft violet halo |
| Elevation | Borders instead of shadows; one soft shadow only on dialogs and menus |

---

## 4. Component rules

### Buttons

- **Primary:** `primary` fill, `on_primary` text. One per screen. The label names the action and, for money, the amount: "Encaisser 5 500 DA".
- **Secondary:** `surface` fill, `border_strong` border, `text` color.
- **Danger:** `danger` text with a `danger` border. Solid red only in the final confirm step of a destructive action.
- **Ghost:** no border, `muted` text. Used in toolbars and table rows.
- **Disabled:** `surface_alt` fill, `faint` text.

### Inputs

- `surface` fill, 1 px `border_strong`, 6 px radius.
- Focus: `primary` border plus ring. Errors are red, so focus and error never look alike.
- Error: `danger` border and a caption under the field in `danger` that says what is wrong and gives an example: "Le numéro doit avoir 10 chiffres, par exemple 0661 90 25 47."
- Labels above fields; required fields marked with a red `*`.
- Money inputs: right-aligned, Plex Mono, suffix "DA".

### Tables (Seyès rules)

- Header row `surface_alt`, uppercase header text in `muted`, `rule_strong` line under the header.
- No vertical lines. A 1 px `rule` line between rows, and `rule_strong` under every fifth row, so the eye keeps its place in long lists. Applies to every list longer than 10 rows.
- Hover row `surface_alt`. Selected row `primary_soft` with a 3 px `primary` leading edge.
- Text left-aligned; numbers, money (Plex Mono) and dates centered. Each header takes its column's alignment, and headers, text and status pills start at the same inset (15 px), so a column reads as one line. On paper (PDF, Excel) amounts stay right-aligned.
- Debt amounts in `danger` weight 500, zero amounts in `faint`, credit in `info`. Debt is the only red in a list, so it can be found without reading every row.
- Sticky header, sortable columns with an arrow, empty state with an icon and one French sentence that says how to add the first item.

### Sidebar

- `sidebar` background, text `chalk` at about 74% opacity, 13 px; Lucide icons 18 px in the same dim chalk.
- Hover `sidebar_hover` with full `chalk` text.
- Active item: a light label, `chalk` background with `sidebar` text and icon, weight 500. No edge bar.
- Wordmark at the top: "Tadris" in Reem Kufi 700 with "تدريس" beside it.
- Menu, in three parts. The day's work: Aujourd'hui (the Tableau de bord), Élèves, Groupes, Emploi du temps, Présences. **ARGENT**: Abonnements, Paiements, Paie enseignants, Rapports. **ÉCOLE**: Enseignants, SMS, Paramètres. Section headings are small uppercase chalk at 50%.
- Role-based items are hidden, not disabled; a heading shows only above an item the user has.
- Footer: a round avatar with two initials, the user name and role, and a log-out icon button on the right (its label in the tooltip).

### Badges

Pill shape, 4 px radius, 11.5 px text weight 500, soft background plus colored text.

| Domain | Value | Color |
|---|---|---|
| Student | active / inactive | Success / Neutral |
| Enrollment | trial / active / left / switched | Info / Success / Neutral / Neutral |
| Subscription | active / expiring within 7 days / ended / cancelled | Success / Warning / Neutral / Danger |
| Session | planned / held / cancelled | Info / Success / Danger |
| Attendance | present / late / absent / excused | Success / Warning / Danger / Info |
| Debt | 0 / above 0 / credit | Success / Danger (bold) / Info |
| Payout | draft / approved / paid | Neutral / Info / Success |
| SMS | pending / sent / failed | Info / Success / Danger |

### Stamp (cachet)

- A rotated circle (about -10°) with a double ring in `primary`, uppercase text in Reem Kufi 700 and the date in Plex Mono.
- On screen: drawn in the receipt preview and the payment confirmation so the receptionist sees at a glance that the receipt is settled.
- On paper: printed as a grey outline, leaving room for the real school stamp beside the signature line.
- Drawn in code (`QPainter` on screen, reportlab circle and rotated text in the PDF). No image file.

### Attendance row

- One student per row: name and student number on the left, a four-part segmented control on the right: Présent (P), Retard (R), Absent (A), Excusé (E).
- The chosen segment takes its semantic soft background and text color. Keyboard shortcuts shown in Plex Mono inside each segment.

### Dialogs and feedback

- Titles in Reem Kufi, actions at the bottom aligned to the end, secondary on the left of primary.
- Business errors (from `BusinessRuleError`) show as an inline banner at the top of the dialog (`danger_bg`, `danger` border and text), not as a popup. The message gives the reason and the way out: "Le groupe est complet. Maths 4AM G2 a 18 élèves sur 18 places. Choisissez un autre groupe ou demandez à la direction d'augmenter la capacité."
- Success: a toast at the bottom for 3 seconds that states what happened ("Paiement enregistré").
- Destructive actions (void payment, cancel subscription) need a confirm dialog that restates the amount and the student.

---

## 5. Page patterns

- **List page:** title and primary action on one row, filter bar below (search, selects, a "Avec dette" toggle in `danger` when active), then the table, then a footer with the count and pagination.
- **Detail page:** header card (name, number, badges, key actions) and tabs below: Inscription, Groupes, Abonnements, Paiements, Présences, Contacts.
- **Student page:** no tabs. Two cards side by side, equal halves: « Élève » (name, number, status, birth; « Modifier », « Désactiver »; then Inscription, Groupes, Contacts, each under a small uppercase heading with a rule above) and « Paiements » (what is owed and « Encaisser un paiement », then À payer / Reçus as a segmented switch). Under them, full width, « Scolarité »: Séances et présences / Abonnements. Lists in cards are as tall as their rows (capped, then they scroll), their row actions sit just under them, and the page scrolls as one.
- **Dashboard (Aujourd'hui):** a 56 px top bar (`surface`, bottom border): « Tableau de bord » and the date on the left; « Ajouter un élève » (secondary) and « Encaisser un paiement » (the screen's primary button; a student picker with the late payers first, then the payment dialog) on the right. Below it, « Bonjour, <name> » and one line (who is late, the next session, the months to renew). Left: « Encaissé par jour » (director only), a bar a day with the average of open days dashed and the hovered day read out top right; then « Plus gros retards » sorted by amount or age, each row with « Encaisser <amount> ». Right: « Séances du jour » on a strip of the opening hours with a now mark, « Places libres » (most free seats first, a thin fill bar), and today's backup (director only). Each card's link opens its page; the lists take the window's height and the page never scrolls; content stops at 1280 px wide.
- **Attendance screen:** attendance rows as described above, and a sticky save bar.
- **Payment dialog:** student debt summary at the top, amount and method in the middle, allocation preview below, receipt preview with the stamp after saving.

---

## 6. Print documents

Receipts, attendance sheets and payout slips must work on a black-and-white laser printer.

- Header: school name in Reem Kufi 600, address and phone below, a thin `primary` rule (prints as dark grey, so nothing depends on it).
- Receipt number in a bordered box at the top right, in Plex Mono.
- Body: Readex Pro 10.5 pt. Amounts: Plex Mono, right-aligned.
- Receipt lines: designation with the subscription period underneath, amount, then "Total payé" and "Reste à payer".
- PAYÉ stamp as a grey outline.
- Footer: "Merci. Conservez ce reçu." and a "Cachet et signature" line.
- No fills heavier than 5% grey.

---

## 7. Implementation

### Files

```
ui/theme/tokens.py     # dicts: LIGHT, DARK
ui/theme/qss.py        # build_qss(tokens) -> str
ui/theme/delegates.py  # RuledDelegate for Seyès table rows
ui/theme/stamp.py      # draw_stamp(painter, rect, text, date, color)
ui/theme/__init__.py   # apply_theme(app, mode)
ui/resources/fonts/    # Reem Kufi, Readex Pro, IBM Plex Mono (.ttf)
ui/resources/icons/    # Lucide SVGs (MIT)
```

### `ui/theme/tokens.py`

```python
LIGHT = {
    # Encre: violet ink, also the stamp
    "primary": "#5A3E9E", "primary_hover": "#6B4FB3",
    "primary_pressed": "#48307F", "primary_soft": "#EEEAF7", "on_primary": "#FFFFFF",
    "sidebar": "#2E2152", "sidebar_hover": "#3A2B66", "chalk": "#ECE8F5",
    "focus": "#5A3E9E",
    # Cahier: paper and Seyès rules
    "bg": "#F4F3F7", "surface": "#FFFFFF", "surface_alt": "#ECEAF2",
    "border": "#DEDBE7", "border_strong": "#C3BED2",
    "rule": "#CBD6EA", "rule_strong": "#9DB0D4",
    "text": "#1D1830", "muted": "#5D5870", "faint": "#928DA3",
    # Semantics (danger is the red pen)
    "success": "#2B7A33", "success_bg": "#E1F2DF",
    "warning": "#9A5A06", "warning_bg": "#FBEFD3",
    "danger": "#BE2A2F", "danger_bg": "#FBE3E2",
    "info": "#2E529E", "info_bg": "#E3EAF8",
    "neutral": "#5A5868", "neutral_bg": "#E9E7EF",
}

DARK = {
    **LIGHT,
    "primary": "#B9A3F5", "primary_hover": "#CBB9FA",
    "primary_pressed": "#A28BE8", "primary_soft": "#2A2140", "on_primary": "#1C1236",
    "sidebar": "#120D1F", "sidebar_hover": "#1D1630", "chalk": "#E2DCF0",
    "focus": "#B9A3F5",
    "bg": "#110F18", "surface": "#1A1724", "surface_alt": "#221E2E",
    "border": "#302B3E", "border_strong": "#423B53",
    "rule": "#26344D", "rule_strong": "#3A4F7C",
    "text": "#E9E6F0", "muted": "#A6A0B5", "faint": "#77718A",
    "success": "#78CF84", "success_bg": "#16301B",
    "warning": "#F0B85A", "warning_bg": "#33270F",
    "danger": "#FF8E86", "danger_bg": "#3A1A19",
    "info": "#93B2F4", "info_bg": "#18243D",
    "neutral": "#B3AEC0", "neutral_bg": "#2A2635",
}
```

### `ui/theme/qss.py`

```python
def rgba(hex_color: str, alpha: float) -> str:
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r}, {g}, {b}, {alpha})"


def build_qss(t: dict) -> str:
    return f"""
    * {{ font-family: "Readex Pro", "Segoe UI", sans-serif; font-size: 14px; color: {t['text']}; }}
    QMainWindow, QWidget#page {{ background: {t['bg']}; }}

    QPushButton {{ min-height: 36px; padding: 0 16px; border-radius: 6px; font-weight: 500;
                   border: 1px solid {t['border_strong']}; background: {t['surface']}; }}
    QPushButton:hover {{ background: {t['surface_alt']}; }}
    QPushButton[variant="primary"] {{ background: {t['primary']}; color: {t['on_primary']}; border: none; }}
    QPushButton[variant="primary"]:hover {{ background: {t['primary_hover']}; }}
    QPushButton[variant="primary"]:pressed {{ background: {t['primary_pressed']}; }}
    QPushButton[variant="danger"] {{ color: {t['danger']}; border: 1px solid {t['danger']}; }}
    QPushButton[variant="danger"]:hover {{ background: {t['danger_bg']}; }}
    QPushButton[variant="ghost"] {{ border: none; background: transparent; color: {t['muted']}; }}
    QPushButton:disabled {{ background: {t['surface_alt']}; color: {t['faint']}; border-color: {t['surface_alt']}; }}

    QLineEdit, QComboBox, QDateEdit, QSpinBox {{ min-height: 36px; padding: 0 10px; border-radius: 6px;
        border: 1px solid {t['border_strong']}; background: {t['surface']}; }}
    QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QSpinBox:focus {{ border: 2px solid {t['focus']}; }}
    QLineEdit[error="true"] {{ border: 1px solid {t['danger']}; }}
    QLineEdit[money="true"] {{ font-family: "IBM Plex Mono"; qproperty-alignment: AlignRight; }}

    QTableView {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 10px;
        gridline-color: transparent; font-size: 13px; show-decoration-selected: 1;
        selection-background-color: {t['primary_soft']}; selection-color: {t['text']}; }}
    QTableView::item:hover {{ background: {t['surface_alt']}; }}
    QHeaderView::section {{ background: {t['surface_alt']}; border: none;
        border-bottom: 1px solid {t['rule_strong']}; padding: 9px 12px;
        font-size: 11.5px; font-weight: 500; color: {t['muted']}; }}

    QFrame#sidebar {{ background: {t['sidebar']}; }}
    QLabel#wordmark {{ font-family: "Reem Kufi"; font-size: 24px; font-weight: 700; color: {t['chalk']}; }}
    QPushButton#navItem {{ background: transparent; border: none; color: {rgba(t['chalk'], 0.74)};
        text-align: left; padding: 0 12px; min-height: 38px; border-radius: 6px; font-weight: 400; }}
    QPushButton#navItem:hover {{ background: {t['sidebar_hover']}; color: {t['chalk']}; }}
    QPushButton#navItem:checked {{ background: {t['chalk']}; color: {t['sidebar']}; font-weight: 500; }}

    QFrame#card {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 10px; }}
    QLabel#pageTitle {{ font-family: "Reem Kufi"; font-size: 24px; font-weight: 600; }}
    QLabel#dialogTitle {{ font-family: "Reem Kufi"; font-size: 18px; font-weight: 600; }}
    QLabel#bigNumber {{ font-family: "Reem Kufi"; font-size: 30px; font-weight: 600; }}
    QLabel#sectionTitle {{ font-size: 16px; font-weight: 500; }}
    QLabel#caption {{ font-size: 12px; color: {t['muted']}; }}
    QLabel#money {{ font-family: "IBM Plex Mono"; font-size: 13px; font-weight: 500; }}
    QLabel#errorBanner {{ background: {t['danger_bg']}; color: {t['danger']};
        border: 1px solid {t['danger']}; border-radius: 6px; padding: 10px 14px; }}
    """
```

### `ui/theme/delegates.py`

QSS cannot target every fifth row, so the Seyès rules are painted by a delegate set on each table view.

```python
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import QStyledItemDelegate


class RuledDelegate(QStyledItemDelegate):
    def __init__(self, tokens: dict, parent=None):
        super().__init__(parent)
        self._rule = QColor(tokens["rule"])
        self._strong = QColor(tokens["rule_strong"])

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        color = self._strong if (index.row() + 1) % 5 == 0 else self._rule
        painter.save()
        painter.setPen(QPen(color, 1))
        painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())
        painter.restore()
```

### `STATUS_STYLE` (single source for badges)

```python
STATUS_STYLE = {
    "student":      {"active": "success", "inactive": "neutral"},
    "enrollment":   {"trial": "info", "active": "success", "left": "neutral", "switched": "neutral"},
    "subscription": {"active": "success", "expiring": "warning", "ended": "neutral", "cancelled": "danger"},
    "session":      {"planned": "info", "held": "success", "cancelled": "danger"},
    "attendance":   {"present": "success", "late": "warning", "absent": "danger", "excused": "info"},
    "payout":       {"draft": "neutral", "approved": "info", "paid": "success"},
    "sms":          {"pending": "info", "sent": "success", "failed": "danger"},
}
```

`expiring` is a display state computed from `end_date` (within 7 days), not a database status.

### Notes

- Set button variants with `btn.setProperty("variant", "primary")`. After changing a property at runtime, call `style().unpolish(btn)` then `style().polish(btn)`.
- Badges: one reusable `Badge(text, kind)` widget that reads colors from the token dict (`kind` is `success`, `warning`, and so on) and takes `kind` from `STATUS_STYLE`.
- Icons: Lucide SVGs, recolored by replacing `currentColor` in the SVG text before creating the `QIcon`. Use 20 px in the sidebar and tables, 16 px inside buttons.
- Fonts: load them before building any widget, then call `app.setFont(QFont("Readex Pro", 10))`.
- Theme switch: `apply_theme(app, "light" | "dark")` rebuilds the QSS from the chosen token dict, calls `app.setStyleSheet(...)` and recreates the table delegates with the new tokens.
- The snippets above show the core rules. `ui/theme/qss.py` and `ui/theme/tokens.py` in the code are the source of truth; they add selectors for dialogs, the sidebar footer, combo boxes and table cells.
- Combo-box arrows: QSS drops the native arrow once the drop-down is styled, so `ui/resources/icons/chevron-down-{light,dark}.svg` (Lucide, in each theme's `muted` color) is passed to `build_qss`.
- Dialog height: fixed-width dialogs call `fit_to_content()` instead of `adjustSize()`, which undersizes layouts with word-wrapped labels and clips the inputs.
- RTL later: write layouts with standard Qt layouts so `app.setLayoutDirection(Qt.RightToLeft)` flips them. Avoid hardcoded left and right in QSS where you can, and keep digits Latin in Arabic mode (a common choice in Algeria).

---

## 8. Decisions

### Decided

| Question | Decision |
|---|---|
| Brand color | Violet ink `#5A3E9E`. The stamp and the focus ring use the same ink; there is no separate accent hue. |
| Display face | Reem Kufi for page titles, dialog titles, big numbers and the wordmark only. |
| PAYÉ stamp | Violet on screen, grey outline on paper. |
| Fifth-row rule | Yes, on every list longer than 10 rows. |
| Receipt paper | Thermal 80 mm for payment receipts: one column, 72 mm printed, the page as long as the ticket, black only (no grey fills; the stamp in ink). Payout slips, sheets and reports stay A4. |

### Still open

| # | Question | Default if not decided |
|---|---|---|
| 1 | **Logo.** A logo file (SVG or PNG) for the sidebar, login window and printed documents. If it has its own color, the ink can shift toward it. | Wordmark "Tadris" in Reem Kufi 700 with "تدريس" |
| 2 | **Density.** Comfortable 40 px rows, or compact 32 px as default at the front desk? | Comfortable (40 px) |
| 3 | **Dark theme.** Needed in v1, or after the pilot? | After the pilot |
