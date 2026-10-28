"""Tema visual: azul-marinho escuro com destaque azul (padrão "Live Performance").

As cores ficam em C para os widgets desenhados à mão usarem as mesmas do estilo Qt.
"""
from PySide6.QtGui import QColor

C = dict(
    bg="#0a111d",            # fundo da janela
    panel="#0f1828",         # painéis (barra superior, laterais, dock)
    card="#132036",          # cartões dentro dos painéis
    card2="#182842",         # cartão em destaque / hover
    border="#1e2d46",
    border2="#2a3d5e",
    accent="#2f7cf6",        # azul principal
    accent2="#1f5fd1",
    accent_soft="#1a3a6e",
    text="#e6edf8",
    dim="#8796ae",
    faint="#5b6a83",
    green="#2fd67b",
    red="#e5394a",
    yellow="#f2c94c",
)
ACCENT = C["accent"]


def qc(name):
    return QColor(C[name])


STYLE = """
QWidget {{ color: {text}; font-family: 'Segoe UI'; font-size: 9.5pt; }}
QMainWindow, QDialog, QMessageBox, QInputDialog, QFileDialog {{ background: {bg}; }}
/* subjanela solta (janela própria, ex. Faders): fundo escuro como a janela principal */
QDockWidget, QDockWidget > QWidget {{ background: {bg}; }}
QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }}
QToolTip {{ background: {card2}; color: {text}; border: 1px solid {border2}; padding: 4px 6px; }}

/* painéis e cartões */
QFrame#topbar {{ background: {panel}; border-bottom: 1px solid {border}; }}
QFrame#side, QFrame#dock, QFrame#center {{ background: {panel}; border: 1px solid {border}; border-radius: 10px; }}
QFrame#card, QFrame#effect {{ background: {card}; border: 1px solid {border}; border-radius: 10px; }}
QFrame#amppanel {{ background: transparent; border: none; }}
QFrame#sep {{ background: {border}; max-width: 1px; min-width: 1px; }}
QWidget#ampface QWidget {{ background: transparent; }}
QWidget#ampface QComboBox {{ background: rgba(10, 17, 29, 225); border: 1px solid rgba(0, 0, 0, 160);
    color: #f0f0f0; padding: 3px 8px; font-size: 10pt; }}
QWidget#ampface QPushButton {{ background: rgba(10, 17, 29, 210); border: 1px solid rgba(0, 0, 0, 160); }}

/* textos */
QLabel#apptitle {{ font-size: 15pt; font-weight: 700; color: {text}; }}
QLabel#appsub {{ font-size: 9pt; color: {dim}; }}
QLabel#h1 {{ font-size: 14pt; font-weight: 700; }}
QLabel#h2, QLabel#fxtitle {{ font-size: 10.5pt; font-weight: 600; }}
QLabel#section {{ font-size: 10pt; font-weight: 600; color: {text}; }}
QLabel#small {{ color: {dim}; font-size: 8.5pt; }}
QLabel#status {{ color: {dim}; }}
QLabel#ok {{ color: {green}; font-weight: 600; }}
QLabel#warn {{ color: {yellow}; font-weight: 600; }}
QLabel#bad {{ color: {red}; font-weight: 600; }}

/* botões */
QPushButton {{ background: {card2}; border: 1px solid {border2}; border-radius: 7px; padding: 5px 12px; color: {text}; }}
QPushButton:hover {{ background: #20345a; border-color: #3a5687; }}
QPushButton:pressed {{ background: {accent2}; }}
QPushButton:disabled {{ color: {faint}; background: {card}; }}
QPushButton:checked {{ background: {accent2}; border-color: {accent}; color: white; }}
QPushButton#primary {{ background: {accent}; border-color: {accent}; color: white; font-weight: 600; }}
QPushButton#primary:hover {{ background: #3f8bff; }}
QPushButton#danger {{ background: #3a1820; border-color: #6b2632; color: #ff9aa5; }}
QPushButton#danger:hover {{ background: #5a1e2a; }}
QPushButton#flat {{ background: transparent; border: none; padding: 4px 8px; color: {dim}; }}
QPushButton#flat:hover {{ color: {text}; background: {card2}; }}
QPushButton#flat:checked {{ color: white; background: {accent2}; }}
QPushButton#nav {{ background: {card}; border: 1px solid {border2}; border-radius: 9px; padding: 8px 12px;
    font-size: 12pt; color: {text}; text-align: left; }}
QPushButton#nav:hover {{ background: {card2}; }}
QPushButton#nav:checked {{ background: {accent}; border-color: #5b9bff; color: white; font-weight: 600; }}
QPushButton#tile {{ background: {card}; border: 1px solid {border2}; border-radius: 8px; padding: 4px;
    font-size: 8.5pt; color: {dim}; }}
QPushButton#tile:hover {{ background: {card2}; color: {text}; }}
QPushButton#tile:checked {{ background: {accent_soft}; border: 2px solid {accent}; color: white; }}
QPushButton#seg {{ background: {card}; border: 1px solid {border2}; border-radius: 7px; padding: 5px 14px; }}
QPushButton#seg:checked {{ background: {accent}; border-color: {accent}; color: white; font-weight: 600; }}
QPushButton#tab {{ background: transparent; border: none; border-radius: 8px; padding: 6px 18px;
    font-size: 10.5pt; color: {dim}; }}
QPushButton#tab:hover {{ color: {text}; background: {card}; }}
QPushButton#tab:checked {{ background: {accent_soft}; color: white; font-weight: 600; }}
QPushButton#power:checked {{ background: #1d5e3b; border-color: {green}; }}
QPushButton#quit, QPushButton#danger {{ font-weight: 600; }}
QPushButton::menu-indicator {{ width: 0; image: none; }}
QPushButton#chip {{ background: {card}; border: 1px solid {border2}; border-radius: 11px; padding: 0 6px;
    font-size: 8.5pt; color: {dim}; }}
QPushButton#chip:hover {{ color: {text}; border-color: #3a5687; }}
QPushButton#chip:checked {{ background: {accent}; border-color: {accent}; color: white; font-weight: 600; }}
QPushButton#version {{ background: {accent_soft}; border: 1px solid {accent}; border-radius: 8px;
    padding: 0px 7px; font-size: 8pt; font-weight: 600; color: #cfe0ff; }}
QPushButton#version:hover {{ background: {accent}; color: white; }}
QToolButton#action {{ background: {card2}; border: 1px solid {border2}; border-radius: 8px; color: {text};
    font-size: 8pt; font-weight: 600; padding: 4px 2px; }}
QToolButton#action:hover {{ background: #20345a; border-color: #3a5687; }}
QToolButton#action:pressed, QToolButton#action:checked {{ background: {accent}; border-color: #8fbaff; }}

/* listas, árvores, campos */
QLineEdit, QSpinBox {{ background: {card}; border: 1px solid {border2}; border-radius: 7px; padding: 5px 8px;
    selection-background-color: {accent}; }}
QLineEdit:focus, QSpinBox:focus {{ border-color: {accent}; }}
QComboBox {{ background: {card}; border: 1px solid {border2}; border-radius: 7px; padding: 4px 8px; }}
QComboBox:hover {{ border-color: #3a5687; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{ background: {card}; border: 1px solid {border2};
    selection-background-color: {accent}; outline: none; }}
QTreeWidget, QListWidget {{ background: transparent; border: none; outline: none; }}
QTreeWidget::item, QListWidget::item {{ padding: 4px 4px; border-radius: 6px; }}
QTreeWidget::item:hover, QListWidget::item:hover {{ background: {card2}; }}
QTreeWidget::item:selected, QListWidget::item:selected {{ background: {accent}; color: white; }}
QTreeWidget::branch, QTreeWidget::branch:selected, QTreeWidget::branch:hover {{ background: transparent; }}
QTreeView {{ show-decoration-selected: 0; selection-background-color: transparent; }}
QHeaderView::section {{ background: {card2}; color: {dim}; border: none; border-right: 1px solid {border2};
    padding: 4px 6px; font-weight: 600; }}
QHeaderView {{ background: {card2}; }}
QMenu {{ background: {card}; border: 1px solid {border2}; padding: 4px; }}
QMenu::item {{ padding: 5px 22px 5px 12px; border-radius: 5px; }}
QMenu::item:selected {{ background: {accent}; color: white; }}
QMenu::separator {{ height: 1px; background: {border2}; margin: 4px 6px; }}
QMenu::section {{ color: {dim}; padding: 4px 8px; font-weight: 600; }}
QCheckBox {{ spacing: 6px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {border2}; background: {card}; }}
QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; }}
QSlider::groove:horizontal {{ height: 4px; background: {border2}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {accent}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: white; border: 3px solid {accent}; width: 12px; height: 12px;
    margin: -6px 0; border-radius: 8px; }}
QSlider::groove:vertical {{ width: 4px; background: {border2}; border-radius: 2px; }}
QSlider::add-page:vertical {{ background: {accent}; border-radius: 2px; }}
QSlider::handle:vertical {{ background: white; border: 3px solid {accent}; width: 12px; height: 12px;
    margin: 0 -6px; border-radius: 8px; }}
QProgressBar {{ background: {card}; border: 1px solid {border2}; border-radius: 3px; }}
QProgressBar::chunk {{ background: {accent}; }}
QScrollArea {{ border: none; }}
/* barras de rolagem visíveis (trilho marcado, puxador claro) */
QScrollBar:vertical {{ background: {card}; width: 10px; margin: 1px; border-radius: 4px; }}
QScrollBar::handle:vertical {{ background: {faint}; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ background: {card}; height: 10px; margin: 1px; border-radius: 4px; }}
QScrollBar::handle:horizontal {{ background: {faint}; border-radius: 4px; min-width: 30px; }}
QScrollBar::handle:hover {{ background: {dim}; }}
QTabWidget::pane {{ border: 1px solid {border}; border-radius: 8px; background: {panel}; top: -1px; }}
QTabBar::tab {{ background: {card}; color: {dim}; border: 1px solid {border2}; border-bottom: none;
    border-top-left-radius: 7px; border-top-right-radius: 7px; padding: 6px 16px; margin-right: 3px; }}
QTabBar::tab:hover {{ color: {text}; background: {card2}; }}
QTabBar::tab:selected {{ background: {accent}; border-color: {accent}; color: white; font-weight: 600; }}
QTextBrowser, QTextEdit, QPlainTextEdit {{ background: {card}; color: {text}; border: 1px solid {border2};
    border-radius: 7px; selection-background-color: {accent}; }}
QMenuBar {{ background: {panel}; color: {text}; border-bottom: 1px solid {border}; padding: 0 6px; }}
QMenuBar::item {{ background: transparent; padding: 2px 10px; border-radius: 5px; }}
QMenuBar::item:selected, QMenuBar::item:pressed {{ background: {card2}; }}
QWidget#docktitle {{ background: {panel}; border-bottom: 1px solid {border}; }}
QWidget#docktitle QLabel {{ color: {dim}; font-size: 8.5pt; font-weight: 600; }}
QWidget#docktitle QToolButton {{ background: transparent; border: none; border-radius: 4px; padding: 1px; }}
QWidget#docktitle QToolButton:hover {{ background: {card2}; }}
QMainWindow::separator {{ background: {bg}; width: 4px; height: 4px; }}
QMainWindow::separator:hover {{ background: {accent_soft}; }}
""".format(**C)
