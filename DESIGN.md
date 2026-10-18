# Tadris Design System

Calm teal for a front desk used all day, high contrast, dense but readable tables, and fonts that also cover Arabic so the later RTL release needs no redesign. Everything is defined as tokens, so a theme change means editing one file.

---

## 1. Fonts

| Role | Font | Why |
|---|---|---|
| UI and body | **IBM Plex Sans** | Clean, legible at 13 px, supports French accents |
| Arabic (later) | **IBM Plex Sans Arabic** | Designed to match Plex Sans, so mixed text looks consistent |
| Amounts, receipt numbers, IDs | **IBM Plex Mono** | Digits align in columns |

All three are open source (OFL). Bundle them in `ui/resources/fonts/`, because the app is offline and installed fonts cannot be relied on. Load them at startup with `QFontDatabase.addApplicationFont`, and set the fallback chain: `IBM Plex Sans, Segoe UI, sans-serif`.

### Type scale

| Style | Size / weight | Use |
|---|---|---|
| Page title | 22 px / 600 | Top of each page |
| Section title | 16 px / 600 | Cards, dialog headers |
| Body | 14 px / 400 | Forms, labels |
| Table text | 13 px / 400 | Rows, dense lists |
| Table header | 12 px / 600, uppercase, tracking +4% | Column headers |
| Caption | 12 px / 400, muted | Hints, timestamps |
| Money | 14 px / 500 mono, right-aligned | Every amount column |
| Big number | 28 px / 600 | Dashboard cards |

Use pixel sizes in QSS (not pt) so Windows scaling stays predictable. Line height is about 1.4.

---

## 2. Colors

### Brand and neutrals (light theme)

| Token | Hex | Use |
|---|---|---|
| `primary-50` | `#F0FDFA` | Selected row, subtle fills |
| `primary-100` | `#CCFBF1` | Hover on light areas, sidebar text |
| `primary-500` | `#14B8A6` | Focus ring |
| `primary-600` | `#0D9488` | Button hover |
| `primary-700` | `#0F766E` | **Primary buttons, links, active elements** |
| `primary-800` | `#115E59` | Button pressed, sidebar hover |
| `primary-900` | `#134E4A` | **Sidebar background** |
| `accent` | `#F59E0B` | Active-item marker, highlights (never as text on white) |
| `bg` | `#F8FAFC` | App background |
| `surface` | `#FFFFFF` | Cards, tables, dialogs |
| `surface-alt` | `#F1F5F9` | Table header, zebra rows, disabled fields |
| `border` | `#E2E8F0` | Dividers, card borders |
| `border-strong` | `#CBD5E1` | Input borders |
| `text` | `#0F172A` | Main text |
| `text-muted` | `#64748B` | Secondary text |
| `text-faint` | `#94A3B8` | Placeholders, disabled text |

### Semantic colors

| Meaning | Text | Background |
|---|---|---|
| Success | `#15803D` | `#DCFCE7` |
| Warning | `#B45309` | `#FEF3C7` |
| Danger | `#B91C1C` | `#FEE2E2` |
| Info | `#1D4ED8` | `#DBEAFE` |
| Neutral | `#475569` | `#E2E8F0` |

Contrast: `text` on `surface` is about 17:1, `primary-700` on white about 5.5:1, and every semantic text color is at least 4.5:1 on white and on its own soft background.

### Dark theme (optional, same token names)

| Token | Hex |
|---|---|
| `bg` | `#0B1220` |
| `surface` | `#111A2B` |
| `surface-alt` | `#172236` |
| `border` | `#263349` |
| `text` | `#E5EDF7` |
| `text-muted` | `#94A3B8` |
| `primary` | `#2DD4BF` (button text `#04201D`) |
| `sidebar` | `#0A1626` |

Ship light first and add dark after the pilot.

---

## 3. Spacing, shape, sizes

| Token | Value |
|---|---|
| Spacing scale | 4, 8, 12, 16, 24, 32 px |
| Radius | 4 badges, 6 inputs and buttons, 10 cards and dialogs |
| Control height | 36 px (inputs, buttons), 30 px compact |
| Table row | 40 px normal, 32 px compact (toggle in settings) |
| Top bar | 56 px |
| Sidebar | 232 px expanded, 64 px collapsed |
| Page padding | 24 px, card padding 16 to 20 px |
| Dialog widths | 480 px (simple), 640 px (forms), 880 px (payment, enrollment) |
| Focus ring | 2 px `primary-500`, offset 1 px |
| Elevation | Borders instead of shadows; one soft shadow only on dialogs and menus |

---

## 4. Component rules

### Buttons

- **Primary:** `primary-700` fill, white text. One per screen.
- **Secondary:** white fill, `border-strong` border, `text` color.
- **Danger:** `danger` text on white with a red border. Solid red only in the final confirm step of a destructive action.
- **Ghost:** no border, used in toolbars and table rows.
- **Disabled:** `surface-alt` fill, `text-faint` text.

### Inputs

- White fill, 1 px `border-strong`, 6 px radius.
- Focus: `primary-500` border plus ring. Error: `danger` border and a caption under the field in `danger`.
- Labels above fields; required fields marked with `*`.
- Money inputs: right-aligned, mono, suffix "DA".

### Tables

- Header row `surface-alt`, no vertical lines, 1 px `border` between rows.
- Selected row `primary-50` with a 3 px `primary-700` left edge.
- Text left-aligned, numbers and money right-aligned in mono, dates centered.
- Sticky header, sortable columns with an arrow, empty state with an icon and one French sentence.

### Sidebar

- `primary-900` background, text `primary-100`, icons 20 px.
- Hover `primary-800`. Active: `primary-700` fill with a 4 px `accent` bar on the leading edge.
- Menu order: Tableau de bord, Élèves, Groupes, Emploi du temps, Présences, Paiements, Enseignants, Rapports, SMS, Paramètres.
- Role-based items are hidden, not disabled.

### Badges

Pill shape, 4 px radius, 12 px text, soft background plus colored text.

| Domain | Value | Color |
|---|---|---|
| Student | active / inactive | Success / Neutral |
| Enrollment | trial / active / left / switched | Info / Success / Neutral / Neutral |
| Subscription | active / ended / cancelled | Success / Neutral / Danger |
| Session | planned / held / cancelled | Info / Success / Danger |
| Attendance | present / late / absent / excused | Success / Warning / Danger / Info |
| Debt | 0 / above 0 / credit | Success / Danger (bold) / Info |
| Refund | pending / approved / paid / rejected | Warning / Info / Success / Neutral |
| Payout | draft / approved / paid | Neutral / Info / Success |
| SMS | pending / sent / failed | Info / Success / Danger |

### Dialogs and feedback

- Titles in section style, actions at the bottom aligned to the end, secondary on the left of primary.
- Business errors (from `BusinessRuleError`) show as an inline red banner at the top of the dialog, not as a popup.
- Success: a toast at the bottom for 3 seconds.
- Destructive actions (void payment, cancel subscription) need a confirm dialog that restates the amount and the student.

---

## 5. Page patterns

- **List page:** title and primary action on one row, filter bar below (search, selects), then the table, then a footer with the count and pagination.
- **Detail page:** header card (name, number, badges, key actions) and tabs below: Inscription, Groupes, Abonnements, Paiements, Présences, Contacts.
- **Dashboard:** a row of 4 stat cards (big number, caption, small trend), then two columns: today's sessions and expiring subscriptions on the left, top debtors on the right.
- **Attendance screen:** one student per row with four large segmented buttons (Présent, Retard, Absent, Excusé), keyboard shortcuts P/R/A/E, and a sticky save bar.
- **Payment dialog:** student debt summary at the top, amount and method in the middle, allocation preview below, receipt preview after saving.

---

## 6. Print documents

Receipts, attendance sheets and payout slips must work in black and white.

- Header: school name in Plex Sans 600, a thin `primary-700` rule.
- Body: Plex Sans 10.5 pt.
- Amounts: Plex Mono.
- Receipt number in a bordered box.
- Footer: school phone and address, "Cachet et signature".
- No fills heavier than 5% gray.

---

## 7. Implementation

### Files

```
ui/theme/tokens.py     # dicts: LIGHT, DARK
ui/theme/qss.py        # build_qss(tokens) -> str
ui/theme/__init__.py   # apply_theme(app, mode)
ui/resources/fonts/    # IBM Plex Sans, Sans Arabic, Mono (.ttf)
ui/resources/icons/    # Lucide SVGs (MIT)
```

### `ui/theme/tokens.py`

```python
LIGHT = {
    "primary": "#0F766E", "primary_hover": "#0D9488", "primary_pressed": "#115E59",
    "primary_soft": "#F0FDFA", "focus": "#14B8A6", "accent": "#F59E0B",
    "sidebar": "#134E4A", "sidebar_hover": "#115E59", "sidebar_text": "#CCFBF1",
    "bg": "#F8FAFC", "surface": "#FFFFFF", "surface_alt": "#F1F5F9",
    "border": "#E2E8F0", "border_strong": "#CBD5E1",
    "text": "#0F172A", "muted": "#64748B", "faint": "#94A3B8",
    "success": "#15803D", "success_bg": "#DCFCE7",
    "warning": "#B45309", "warning_bg": "#FEF3C7",
    "danger": "#B91C1C", "danger_bg": "#FEE2E2",
    "info": "#1D4ED8", "info_bg": "#DBEAFE",
    "neutral": "#475569", "neutral_bg": "#E2E8F0",
}

DARK = {
    **LIGHT,
    "primary": "#2DD4BF", "primary_hover": "#5EEAD4", "primary_pressed": "#14B8A6",
    "primary_soft": "#12332F", "focus": "#2DD4BF",
    "sidebar": "#0A1626", "sidebar_hover": "#12233A", "sidebar_text": "#CBD5E1",
    "bg": "#0B1220", "surface": "#111A2B", "surface_alt": "#172236",
    "border": "#263349", "border_strong": "#34445F",
    "text": "#E5EDF7", "muted": "#94A3B8", "faint": "#64748B",
}
```

### `ui/theme/qss.py`

```python
def build_qss(t: dict) -> str:
    return f"""
    * {{ font-family: "IBM Plex Sans", "Segoe UI", sans-serif; font-size: 14px; color: {t['text']}; }}
    QMainWindow, QWidget#page {{ background: {t['bg']}; }}

    QPushButton {{ min-height: 36px; padding: 0 16px; border-radius: 6px;
                   border: 1px solid {t['border_strong']}; background: {t['surface']}; }}
    QPushButton:hover {{ background: {t['surface_alt']}; }}
    QPushButton[variant="primary"] {{ background: {t['primary']}; color: white; border: none; font-weight: 500; }}
    QPushButton[variant="primary"]:hover {{ background: {t['primary_hover']}; }}
    QPushButton[variant="primary"]:pressed {{ background: {t['primary_pressed']}; }}
    QPushButton[variant="danger"] {{ color: {t['danger']}; border: 1px solid {t['danger']}; }}
    QPushButton[variant="ghost"] {{ border: none; background: transparent; }}
    QPushButton:disabled {{ background: {t['surface_alt']}; color: {t['faint']}; }}

    QLineEdit, QComboBox, QDateEdit, QSpinBox {{ min-height: 36px; padding: 0 10px; border-radius: 6px;
        border: 1px solid {t['border_strong']}; background: {t['surface']}; }}
    QLineEdit:focus, QComboBox:focus, QDateEdit:focus {{ border: 2px solid {t['focus']}; }}
    QLineEdit[error="true"] {{ border: 1px solid {t['danger']}; }}

    QTableView {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 10px;
        gridline-color: transparent; font-size: 13px;
        selection-background-color: {t['primary_soft']}; selection-color: {t['text']}; }}
    QHeaderView::section {{ background: {t['surface_alt']}; border: none; padding: 10px 12px;
        font-size: 12px; font-weight: 600; color: {t['muted']}; }}

    QFrame#sidebar {{ background: {t['sidebar']}; }}
    QPushButton#navItem {{ background: transparent; border: none; color: {t['sidebar_text']};
        text-align: left; padding: 0 16px; min-height: 44px; border-radius: 0; }}
    QPushButton#navItem:hover {{ background: {t['sidebar_hover']}; }}
    QPushButton#navItem:checked {{ background: {t['primary']}; border-left: 4px solid {t['accent']}; color: white; }}

    QFrame#card {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 10px; }}
    QLabel#pageTitle {{ font-size: 22px; font-weight: 600; }}
    QLabel#sectionTitle {{ font-size: 16px; font-weight: 600; }}
    QLabel#caption {{ font-size: 12px; color: {t['muted']}; }}
    QLabel#bigNumber {{ font-size: 28px; font-weight: 600; }}
    QLabel#errorBanner {{ background: {t['danger_bg']}; color: {t['danger']};
        border: 1px solid {t['danger']}; border-radius: 6px; padding: 8px 12px; }}
    """
```

### `STATUS_STYLE` (single source for badges)

```python
STATUS_STYLE = {
    "student":      {"active": "success", "inactive": "neutral"},
    "enrollment":   {"trial": "info", "active": "success", "left": "neutral", "switched": "neutral"},
    "subscription": {"active": "success", "ended": "neutral", "cancelled": "danger"},
    "session":      {"planned": "info", "held": "success", "cancelled": "danger"},
    "attendance":   {"present": "success", "late": "warning", "absent": "danger", "excused": "info"},
    "refund":       {"pending": "warning", "approved": "info", "paid": "success", "rejected": "neutral"},
    "payout":       {"draft": "neutral", "approved": "info", "paid": "success"},
    "sms":          {"pending": "info", "sent": "success", "failed": "danger"},
}
```

### Notes

- Set button variants with `btn.setProperty("variant", "primary")`. After changing a property at runtime, call `style().unpolish(btn)` then `style().polish(btn)`.
- Badges: one reusable `Badge(text, kind)` widget that reads colors from the token dict (`kind` is `success`, `warning`, and so on) and takes `kind` from `STATUS_STYLE`.
- Icons: Lucide SVGs, recolored by replacing `currentColor` in the SVG text before creating the `QIcon`. Use 20 px in the sidebar and tables, 16 px inside buttons.
- Fonts: load them before building any widget, then call `app.setFont(QFont("IBM Plex Sans", 10))`.
- Theme switch: `apply_theme(app, "light" | "dark")` rebuilds the QSS from the chosen token dict and calls `app.setStyleSheet(...)`.
- RTL later: write layouts with standard Qt layouts so `app.setLayoutDirection(Qt.RightToLeft)` flips them. Avoid hardcoded left and right in QSS where you can, and keep digits Latin in Arabic mode (a common choice in Algeria).

---

## 8. Decisions needed

| # | Question | Default if not decided |
|---|---|---|
| 1 | **Brand color.** If the school has a logo or color, give the hex and the palette gets rebuilt around it. | Teal `#0F766E` |
| 2 | **Density.** Comfortable 40 px rows, or compact 32 px as default at the front desk? | Comfortable (40 px) |
| 3 | **Dark theme.** Needed in v1, or after the pilot? | After the pilot |
| 4 | **Logo.** A logo file (SVG or PNG) for the sidebar, login window and printed documents. | Text wordmark "Tadris" in Plex Sans 600 |
| 5 | **Receipt paper.** A4 or thermal 80 mm. This changes the print layout. | A4 first |
