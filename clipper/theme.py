"""Shared dark/orange visual language based on the original Clipper UI."""

ACCENT = '#ff7300'
ACCENT_HOVER = '#ff9000'
BACKGROUND = '#121212'
SURFACE = '#1e1e1e'
SURFACE_RAISED = '#252525'
BORDER = '#3b3b3b'
TEXT = '#eeeeee'
MUTED = '#9a9a9a'

APP_STYLE = f'''
    QWidget {{ background: {BACKGROUND}; color: {TEXT}; font-size: 13px; font-family: 'Segoe UI', 'Noto Sans', 'Helvetica', 'Arial'; }}
    QLabel, QCheckBox, QRadioButton {{ background: transparent; }}
    QLabel[muted="true"] {{ color: {MUTED}; }}
    QLabel[heading="true"] {{ font-size: 21px; font-weight: 700; color: #f5f5f5; }}
    QLabel[subheading="true"] {{ font-size: 15px; font-weight: 600; color: #f5f5f5; }}
    QLineEdit, QTreeWidget, QComboBox, QSpinBox, QDoubleSpinBox {{
        background: {SURFACE}; border: 1px solid #444444; border-radius: 6px;
        padding: 7px 9px; selection-background-color: {ACCENT};
    }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ min-height: 20px; }}
    QLineEdit:focus, QTreeWidget:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
        border-color: {ACCENT};
    }}
    QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
        color: #666666; background: #191919;
    }}
    QComboBox::drop-down {{ border: 0; width: 24px; }}
    QComboBox QAbstractItemView {{
        background: #252525; border: 1px solid #484848; selection-background-color: {ACCENT};
        selection-color: white; padding: 4px; outline: 0;
    }}
    QCheckBox {{ spacing: 9px; min-height: 24px; }}
    QCheckBox::indicator {{
        width: 17px; height: 17px; border: 1px solid #666666; border-radius: 4px; background: {SURFACE};
    }}
    QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
    QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
    QPushButton {{
        background: {SURFACE}; border: 1px solid #444444; border-radius: 6px;
        padding: 7px 13px; min-height: 20px;
    }}
    QPushButton:hover {{ background: {ACCENT}; border-color: {ACCENT_HOVER}; color: white; }}
    QPushButton:pressed {{ background: #d96200; border-color: #d96200; }}
    QPushButton:focus {{ border-color: {ACCENT}; }}
    QPushButton[primary="true"] {{ background: {ACCENT}; border-color: {ACCENT}; color: white; font-weight: bold; }}
    QPushButton[primary="true"]:hover {{ background: {ACCENT_HOVER}; }}
    QPushButton[danger="true"]:enabled {{ background: #dc3545; border-color: #dc3545; color: white; font-weight: bold; }}
    QPushButton[danger="true"]:hover {{ background: #ed4b5b; border-color: #ed4b5b; }}
    QPushButton[record="true"]:enabled {{ background: #28a745; border-color: #28a745; color: white; font-weight: bold; }}
    QPushButton[record="true"]:hover {{ background: #35bd55; border-color: #35bd55; }}
    QPushButton:disabled {{ color: #666666; background: #222222; border-color: #303030; }}
    QToolButton {{ background: transparent; border: 0; border-radius: 5px; padding: 5px; }}
    QToolButton:hover {{ background: #303030; }}
    QTabWidget::pane {{ border: 0; border-top: 1px solid #2a2a2a; top: 0; background: {BACKGROUND}; }}
    QTabBar::tab {{
        background: {SURFACE}; border: 0; border-top-left-radius: 4px; border-top-right-radius: 4px;
        padding: 9px 18px 8px; margin: 0 2px 0 0; color: #aaaaaa;
    }}
    QTabBar::tab:selected {{ background: {ACCENT}; color: white; font-weight: bold; }}
    QTabBar::tab:hover:!selected {{ color: white; background: #333333; }}
    QGroupBox {{
        background: transparent; border: 0; border-radius: 8px; margin-top: 20px;
        padding: 10px 4px 4px; font-weight: bold;
    }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 4px; padding: 0 6px; color: {TEXT}; }}
    QHeaderView::section {{ background: #282828; padding: 6px; border: 0; }}
    QTreeWidget::item {{ padding: 3px; }}
    QTreeWidget::item:selected {{ background: #9b4e23; }}
    QTreeWidget::item:hover {{ background: #2a2a2a; }}
    QTreeWidget::branch {{ background: #202020; }}
    QListWidget {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 6px; padding: 4px; outline: 0; }}
    QListWidget::item {{ padding: 7px; border-radius: 4px; }}
    QListWidget::item:selected {{ background: #814313; color: white; }}
    QListWidget::item:hover {{ background: #303030; }}
    QScrollArea {{ border: 0; background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {ACCENT}; min-height: 28px; border-radius: 4px; }}
    QScrollBar::handle:vertical:hover {{ background: {ACCENT_HOVER}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {ACCENT}; min-width: 28px; border-radius: 4px; }}
    QScrollBar::handle:horizontal:hover {{ background: {ACCENT_HOVER}; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QSplitter::handle {{ background: #2d2d2d; width: 1px; height: 1px; }}
    QMenu {{ background: #252525; border: 1px solid #464646; padding: 5px; }}
    QMenu::item {{ padding: 6px 24px 6px 10px; border-radius: 4px; }}
    QMenu::item:selected {{ background: {ACCENT}; }}
    QMenu::separator {{ height: 1px; background: #414141; margin: 5px 8px; }}
    QSlider::groove:horizontal {{ background: #333333; height: 6px; border-radius: 3px; }}
    QSlider::sub-page:horizontal {{ background: #777777; border-radius: 3px; }}
    QSlider::handle:horizontal {{ background: {ACCENT}; width: 14px; margin: -5px 0; border-radius: 7px; }}
    QToolTip {{ background: #292929; color: white; border: 1px solid #505050; padding: 5px; }}
    QFrame[panel="true"] {{ background: #181818; border: 1px solid #303030; border-radius: 9px; }}
    QStatusBar {{ background: #181818; color: {MUTED}; }}
'''
