BADGE_KINDS = ("success", "warning", "danger", "info", "neutral")


def rgba(hex_color: str, alpha: float) -> str:
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r}, {g}, {b}, {alpha})"


def build_qss(t: dict, chevron: str = "", check: str = "") -> str:
    """chevron, check: absolute paths (forward slashes) of the combo-box arrow and the
    check-box tick for this theme."""
    chalk_dim = rgba(t["chalk"], 0.74)
    badges = "\n".join(
        f'    QLabel#badge[kind="{kind}"] {{ background: {t[kind + "_bg"]}; color: {t[kind]}; }}'
        for kind in BADGE_KINDS
    )
    return f"""
    * {{ font-family: "Readex Pro", "Segoe UI", sans-serif; font-size: 14px; color: {t['text']}; }}
    QMainWindow, QWidget#page {{ background: {t['bg']}; }}
    QDialog {{ background: {t['surface']}; }}

    QPushButton {{ min-height: 36px; padding: 0 16px; border-radius: 6px; font-weight: 500;
                   border: 1px solid {t['border_strong']}; background: {t['surface']}; }}
    QPushButton:hover {{ background: {t['surface_alt']}; }}
    QPushButton[variant="primary"] {{ background: {t['primary']}; color: {t['on_primary']};
                                      border: none; }}
    QPushButton[variant="primary"]:hover {{ background: {t['primary_hover']}; }}
    QPushButton[variant="primary"]:pressed {{ background: {t['primary_pressed']}; }}
    QPushButton[variant="danger"] {{ color: {t['danger']}; border: 1px solid {t['danger']}; }}
    QPushButton[variant="danger"]:hover {{ background: {t['danger_bg']}; }}
    QPushButton[variant="ghost"] {{ border: none; background: transparent; color: {t['muted']}; }}
    QPushButton:disabled {{ background: {t['surface_alt']}; color: {t['faint']};
                            border-color: {t['surface_alt']}; }}

    QLineEdit, QComboBox, QDateEdit, QSpinBox {{ min-height: 36px; padding: 0 10px;
        border-radius: 6px; border: 1px solid {t['border_strong']}; background: {t['surface']}; }}
    QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QSpinBox:focus {{
        border: 2px solid {t['focus']}; padding: 0 9px; }}
    QPlainTextEdit {{ padding: 6px 8px; border-radius: 6px; border: 1px solid {t['border_strong']};
        background: {t['surface']}; }}
    QPlainTextEdit:focus {{ border: 2px solid {t['focus']}; padding: 5px 7px; }}
    QCheckBox {{ spacing: 8px; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px;
        border: 1px solid {t['border_strong']}; background: {t['surface']}; }}
    QCheckBox::indicator:focus {{ border: 2px solid {t['focus']}; }}
    QCheckBox::indicator:checked {{ background: {t['primary']}; border-color: {t['primary']};
        image: url("{check}"); }}
    QCheckBox::indicator:disabled {{ background: {t['surface_alt']}; }}
    QCheckBox::indicator:checked:disabled {{ background: {t['faint']};
        border-color: {t['faint']}; }}
    QCheckBox:disabled {{ color: {t['muted']}; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {t['border_strong']}; border-radius: 3px;
        min-height: 32px; }}
    QScrollBar::handle:vertical:hover {{ background: {t['faint']}; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {t['border_strong']}; border-radius: 3px;
        min-width: 32px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QComboBox::drop-down {{ border: none; width: 28px; }}
    /* The stock spin arrows do not fit the Encre inputs. Collapse them here: with
       setButtonSymbols(NoButtons) the stylesheet squeezes the text field to 1 px. */
    QSpinBox::up-button, QSpinBox::down-button {{ width: 0px; border: none; }}
    QComboBox::down-arrow {{ image: url("{chevron}"); width: 14px; height: 14px; }}
    QComboBox QAbstractItemView {{ background: {t['surface']}; border: 1px solid {t['border']};
        selection-background-color: {t['primary_soft']}; selection-color: {t['text']}; }}
    QLineEdit[error="true"] {{ border: 1px solid {t['danger']}; }}
    QLineEdit[money="true"] {{ font-family: "IBM Plex Mono"; qproperty-alignment: AlignRight; }}
    QLabel#fieldLabel {{ font-size: 13px; font-weight: 500; }}

    QTableView {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 10px;
        gridline-color: transparent; font-size: 13px; show-decoration-selected: 1; outline: 0;
        selection-background-color: {t['primary_soft']}; selection-color: {t['text']}; }}
    /* Row hover and selection are painted by RuledDelegate, so they span the whole row. */
    QTableView::item {{ padding: 0 12px; }}
    QHeaderView::section {{ background: {t['surface_alt']}; border: none;
        border-bottom: 1px solid {t['rule_strong']}; padding: 9px 12px;
        font-size: 11.5px; font-weight: 500; color: {t['muted']}; }}

    QFrame#sidebar {{ background: {t['sidebar']}; }}
    QLabel#wordmark {{ font-family: "Reem Kufi"; font-size: 24px; font-weight: 700;
                       color: {t['chalk']}; }}
    QLabel#wordmarkAr {{ font-family: "Reem Kufi"; font-size: 16px; color: {chalk_dim}; }}
    QPushButton#navItem {{ background: transparent; border: none; color: {chalk_dim};
        text-align: left; padding: 0 12px; min-height: 38px; border-radius: 6px;
        font-weight: 400; }}
    QPushButton#navItem:hover {{ background: {t['sidebar_hover']}; color: {t['chalk']}; }}
    QPushButton#navItem:checked {{ background: {t['chalk']}; color: {t['sidebar']};
                                   font-weight: 500; }}
    QFrame#sidebarFooter {{ border-top: 1px solid {rgba(t['chalk'], 0.14)}; }}
    QLabel#sidebarUser {{ color: {t['chalk']}; font-size: 13px; font-weight: 500; }}
    QLabel#sidebarRole {{ color: {chalk_dim}; font-size: 12px; }}

    QLabel#brandWordmark {{ font-family: "Reem Kufi"; font-size: 30px; font-weight: 700;
                            color: {t['primary']}; }}
    QLabel#brandWordmarkAr {{ font-family: "Reem Kufi"; font-size: 18px; color: {t['muted']}; }}

    QFrame#card {{ background: {t['surface']}; border: 1px solid {t['border']};
                   border-radius: 10px; }}
    QLabel#pageTitle {{ font-family: "Reem Kufi"; font-size: 24px; font-weight: 600; }}
    QLabel#dialogTitle {{ font-family: "Reem Kufi"; font-size: 18px; font-weight: 600; }}
    QLabel#bigNumber {{ font-family: "Reem Kufi"; font-size: 30px; font-weight: 600; }}
    QLabel#sectionTitle {{ font-size: 16px; font-weight: 500; }}
    QLabel#caption {{ font-size: 12px; color: {t['muted']}; }}
    QLabel#money {{ font-family: "IBM Plex Mono"; font-size: 13px; font-weight: 500; }}
    QLabel#errorBanner {{ background: {t['danger_bg']}; color: {t['danger']};
        border: 1px solid {t['danger']}; border-radius: 6px; padding: 10px 14px; }}
    QLabel#warningBanner {{ background: {t['warning_bg']}; color: {t['warning']};
        border: 1px solid {t['warning']}; border-radius: 6px; padding: 10px 14px; }}
    QLabel#mono {{ font-family: "IBM Plex Mono"; font-size: 13px; font-weight: 500;
                   color: {t['muted']}; }}
    QLabel#emptyState {{ background: {t['surface']}; border: 1px solid {t['border']};
        border-radius: 10px; padding: 48px 24px; color: {t['muted']}; font-size: 13px; }}
    QLabel#badge {{ border-radius: 4px; padding: 2px 8px; font-size: 11.5px; font-weight: 500; }}
{badges}
    QFrame#datePopup {{ background: {t['surface']}; border: 1px solid {t['border']};
        border-radius: 10px; }}
    QToolButton#calendarNav {{ border: none; border-radius: 6px; padding: 6px; }}
    QToolButton#calendarNav:hover {{ background: {t['surface_alt']}; }}
    QToolButton#calendarNav:disabled {{ background: transparent; }}
    QPushButton#calendarTitle {{ border: none; background: transparent; min-height: 32px;
        padding: 0 8px; font-size: 15px; font-weight: 600; }}
    QPushButton#calendarTitle:hover {{ background: {t['primary_soft']}; color: {t['primary']}; }}
    QLabel#calendarRange {{ font-size: 15px; font-weight: 600; padding: 0 8px; }}
    QPushButton#calendarCell {{ border: none; background: transparent; min-height: 44px;
        padding: 0; font-weight: 400; }}
    QPushButton#calendarCell:hover {{ background: {t['primary_soft']}; }}
    QPushButton#calendarCell:checked {{ background: {t['primary']}; color: {t['on_primary']};
        font-weight: 500; }}
    QPushButton#calendarCell:disabled {{ background: transparent; color: {t['faint']}; }}
    QCalendarWidget QTableView {{ border: none; border-radius: 0; font-size: 13px;
        background: {t['surface']}; selection-background-color: {t['primary']};
        selection-color: {t['on_primary']}; outline: 0; }}
    QCalendarWidget QTableView::item {{ padding: 0; border-radius: 6px; }}
    QCalendarWidget QTableView::item:hover {{ background: {t['primary_soft']}; }}
    QCalendarWidget QTableView::item:selected {{ background: {t['primary']};
        color: {t['on_primary']}; }}
    QCalendarWidget QTableView:disabled {{ color: {t['faint']}; }}
    QTabWidget::pane {{ border: none; border-top: 1px solid {t['border']}; top: -1px; }}
    QTabBar {{ qproperty-drawBase: 0; }}
    QTabBar::tab {{ background: transparent; color: {t['muted']}; padding: 8px 16px;
        border: none; border-bottom: 2px solid transparent; }}
    QTabBar::tab:hover {{ color: {t['text']}; }}
    QTabBar::tab:selected {{ color: {t['text']}; font-weight: 500;
        border-bottom: 2px solid {t['primary']}; }}

    QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QStatusBar {{ background: {t['surface']}; border-top: 1px solid {t['border']}; }}
    QStatusBar QLabel {{ color: {t['muted']}; font-size: 12px; padding: 0 8px; }}
    """
