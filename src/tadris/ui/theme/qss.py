def rgba(hex_color: str, alpha: float) -> str:
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r}, {g}, {b}, {alpha})"


def build_qss(t: dict, chevron: str = "") -> str:
    """chevron: absolute path (forward slashes) of the combo-box arrow for this theme."""
    chalk_dim = rgba(t["chalk"], 0.74)
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
    QComboBox::drop-down {{ border: none; width: 28px; }}
    QComboBox::down-arrow {{ image: url("{chevron}"); width: 14px; height: 14px; }}
    QComboBox QAbstractItemView {{ background: {t['surface']}; border: 1px solid {t['border']};
        selection-background-color: {t['primary_soft']}; selection-color: {t['text']}; }}
    QLineEdit[error="true"] {{ border: 1px solid {t['danger']}; }}
    QLineEdit[money="true"] {{ font-family: "IBM Plex Mono"; qproperty-alignment: AlignRight; }}
    QLabel#fieldLabel {{ font-size: 13px; font-weight: 500; }}

    QTableView {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 10px;
        gridline-color: transparent; font-size: 13px; show-decoration-selected: 1;
        selection-background-color: {t['primary_soft']}; selection-color: {t['text']}; }}
    QTableView::item {{ padding: 0 12px; }}
    QTableView::item:hover {{ background: {t['surface_alt']}; }}
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

    QStatusBar {{ background: {t['surface']}; border-top: 1px solid {t['border']}; }}
    QStatusBar QLabel {{ color: {t['muted']}; font-size: 12px; padding: 0 8px; }}
    """
