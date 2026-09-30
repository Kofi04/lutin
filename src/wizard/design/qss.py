"""The Qt stylesheet, generated from the tokens.

One function, one string. It replaces the hand-written sheet that used to be
copied into four modules, and it is the only place allowed to know what a
QPushButton looks like.

Object names used as hooks (`#hint`, `#title`, `#danger`) are kept few and
semantic, for the same reason the tokens are.
"""

from __future__ import annotations

from .tokens import Theme


def stylesheet(theme: Theme) -> str:
    p = theme.palette
    s = theme.spacing
    r = theme.radius
    t = theme.type

    return f"""
* {{
    font-family: {t.family};
    font-size: {t.body}px;
}}

QWidget#panel, QDialog {{
    background: {p.surface};
    color: {p.text};
}}

QLabel {{
    color: {p.text};
    background: transparent;
}}
QLabel#hint, QLabel#caption {{
    color: {p.text_muted};
    font-size: {t.caption}px;
}}
QLabel#faint {{ color: {p.text_faint}; font-size: {t.caption}px; }}
QLabel#title {{
    color: {p.text};
    font-family: {t.family_display};
    font-size: {t.title}px;
    font-weight: 600;
}}
QLabel#display {{
    font-family: {t.family_display};
    font-size: {t.display}px;
    font-weight: 600;
}}
QLabel#danger {{ color: {p.danger}; }}
QLabel#success {{ color: {p.success}; }}
QLabel#warning {{ color: {p.warning}; }}

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox {{
    background: {p.field};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: {r.md}px;
    padding: {s.sm}px {s.md}px;
    selection-background-color: {p.accent};
    selection-color: {p.on_accent};
}}
QLineEdit:hover, QPlainTextEdit:hover, QTextEdit:hover {{
    border-color: {p.border_strong};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {p.focus};
}}
QLineEdit#search {{
    font-size: {t.body_large}px;
    padding: {s.md}px {s.lg}px;
    border-radius: {r.lg}px;
}}

QPushButton {{
    background: {p.surface_raised};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: {r.md}px;
    padding: {s.sm}px {s.lg}px;
    min-height: 20px;
}}
QPushButton:hover {{ background: {p.accent_soft}; border-color: {p.border_strong}; }}
QPushButton:pressed {{ background: {p.field}; }}
QPushButton:focus {{ border-color: {p.focus}; }}
QPushButton:disabled {{ color: {p.text_faint}; background: {p.surface}; }}
QPushButton:default, QPushButton#primary {{
    background: {p.accent};
    border-color: {p.accent};
    color: {p.on_accent};
    font-weight: 600;
}}
QPushButton:default:hover, QPushButton#primary:hover {{
    background: {p.accent_hover};
    border-color: {p.accent_hover};
}}
QPushButton#danger {{ color: {p.danger}; }}
QPushButton#danger:hover {{ background: {p.danger}; color: #FFFFFF; }}
QPushButton#quiet {{
    background: transparent;
    border-color: transparent;
    color: {p.text_muted};
}}
QPushButton#quiet:hover {{ background: {p.accent_soft}; color: {p.text}; }}

QListWidget, QTreeWidget, QTableWidget {{
    background: {p.field};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: {r.md}px;
    outline: none;
    padding: {s.xs}px;
}}
QListWidget::item, QTreeWidget::item {{
    padding: {s.sm}px {s.md}px;
    border-radius: {r.sm}px;
}}
QListWidget::item:hover, QTreeWidget::item:hover {{ background: {p.accent_soft}; }}
QListWidget::item:selected, QTreeWidget::item:selected {{
    background: {p.accent};
    color: {p.on_accent};
}}

QTabBar::tab {{
    background: transparent;
    color: {p.text_muted};
    padding: {s.sm}px {s.lg}px;
    border: none;
}}
QTabBar::tab:hover {{ color: {p.text}; }}
QTabBar::tab:selected {{
    color: {p.text};
    border-bottom: 2px solid {p.accent};
}}
QTabWidget::pane {{ border: none; }}

QCheckBox, QRadioButton {{ color: {p.text}; spacing: {s.sm}px; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {p.border_strong};
    border-radius: {r.sm}px;
    background: {p.field};
}}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {p.accent};
    border-color: {p.accent};
}}

QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {p.border_strong};
    border-radius: 5px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: {p.text_faint}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{
    background: {p.border_strong}; border-radius: 5px; min-width: 28px;
}}

QMenu {{
    background: {p.surface_raised};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: {r.md}px;
    padding: {s.xs}px;
}}
QMenu::item {{ padding: {s.sm}px {s.lg}px; border-radius: {r.sm}px; }}
QMenu::item:selected {{ background: {p.accent}; color: {p.on_accent}; }}
QMenu::item:disabled {{ color: {p.text_faint}; }}
QMenu::separator {{ height: 1px; background: {p.border}; margin: {s.xs}px 0; }}

QToolTip {{
    background: {p.surface_raised};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: {r.sm}px;
    padding: {s.xs}px {s.sm}px;
}}

QFrame#card {{
    background: {p.surface_raised};
    border: 1px solid {p.border};
    border-radius: {r.lg}px;
}}
QFrame#separator {{ background: {p.border}; max-height: 1px; border: none; }}
"""
