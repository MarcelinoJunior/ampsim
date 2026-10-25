STYLE = """
QWidget { background: #16181d; color: #d8dae0; font-family: 'Segoe UI'; font-size: 9pt; }
QFrame#topbar, QFrame#kbdbar, QFrame#trackhead { background: #1d2026; border: 1px solid #2c3038; border-radius: 6px; }
QFrame#effect { background: #22252c; border: 1px solid #30343d; border-radius: 8px; }
QFrame#effect QWidget, QFrame#topbar QWidget, QFrame#kbdbar QWidget, QFrame#trackhead QWidget { background: transparent; }
QFrame#amppanel { background: transparent; border: none; }
QFrame#amppanel QWidget { background: transparent; }
QFrame#amppanel QComboBox { background: rgba(20, 20, 22, 210); border: 1px solid rgba(0, 0, 0, 160); color: #f0f0f0; }
QLabel#apptitle { font-size: 15pt; font-weight: 600; color: #f0f0f0; }
QLabel#fxtitle { font-size: 10pt; font-weight: 600; }
QLabel#small { color: #8a8f99; font-size: 8pt; }
QLabel#status { color: #b6bac3; }
QPushButton { background: #2c3038; border: 1px solid #3a3f49; border-radius: 4px; padding: 4px 10px; }
QPushButton:hover { background: #353a44; }
QPushButton#power:checked { background: #2f6b3f; border-color: #3d8a52; }
QPushButton#quit { background: #5a2a2d; border-color: #7a3a3e; padding: 6px 14px; font-weight: 600; }
QPushButton#quit:hover { background: #7a3238; }
QComboBox { background: #2c3038; border: 1px solid #3a3f49; border-radius: 4px; padding: 2px 6px; }
QComboBox QAbstractItemView { background: #2c3038; selection-background-color: #47507a; }
QTabWidget::pane { border: none; }
QTabBar::tab { background: #1d2026; padding: 6px 22px; border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px; font-size: 10pt; }
QTabBar::tab:selected { background: #2c3038; color: #ffffff; }
QScrollArea { border: none; }
QCheckBox::indicator { width: 14px; height: 14px; }
"""
