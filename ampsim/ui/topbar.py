"""Barra superior: logo, abas grandes, estado do áudio, preset da aba com ‹ ›, Arquivo e menu."""
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from .icons import icon, pixmap
from ..version import version_text
from .theme import ACCENT, C

NAV = (("guitar", "Guitarra", "guitar"), ("bass", "Baixo", "bass"), ("pads", "Pad/Piano", "keys"))


class _Dot(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(12, 12)
        self.color = QColor(C["faint"])

    def set_color(self, c):
        self.color = QColor(c)
        self.update()

    def paintEvent(self, _):
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        qp.setPen(Qt.NoPen)
        glow = QColor(self.color)
        glow.setAlpha(70)
        qp.setBrush(glow)
        qp.drawEllipse(0, 0, 12, 12)
        qp.setBrush(self.color)
        qp.drawEllipse(2, 2, 8, 8)


class TopBar(QFrame):
    pageRequested = Signal(int)
    powerToggled = Signal(bool)
    audioSettings = Signal()
    presetStep = Signal(int)
    presetSave = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("topbar")
        self.setFixedHeight(66)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 8, 14, 8)
        lay.setSpacing(10)

        logo = QLabel()
        logo.setPixmap(pixmap("logo", ACCENT, 34))
        lay.addWidget(logo)
        names = QVBoxLayout()
        names.setSpacing(0)
        trow = QHBoxLayout()
        trow.setSpacing(6)
        t = QLabel("AmpSim")
        t.setObjectName("apptitle")
        trow.addWidget(t)
        self.version_btn = QPushButton(f"v{version_text()}")
        self.version_btn.setObjectName("version")
        self.version_btn.setFocusPolicy(Qt.NoFocus)
        self.version_btn.setCursor(Qt.PointingHandCursor)
        self.version_btn.setToolTip("Sobre o AmpSim: versão, licença, créditos e atualizações")
        trow.addWidget(self.version_btn, 0, Qt.AlignVCenter)
        trow.addStretch(1)
        names.addLayout(trow)
        sub = QLabel("Live Performance")
        sub.setObjectName("appsub")
        names.addWidget(sub)
        lay.addLayout(names)
        lay.addSpacing(18)

        self.nav = []
        for i, (_key, text, ic) in enumerate(NAV):
            b = QPushButton(text)
            b.setObjectName("nav")
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.setIcon(icon(ic, C["text"], 22))
            b.setIconSize(QSize(22, 22))
            b.setMinimumHeight(48)
            b.setMinimumWidth(b.sizeHint().width() + 8)
            b.clicked.connect(lambda _, i=i: self.pageRequested.emit(i))
            self.nav.append(b)
            lay.addWidget(b)
        lay.addStretch(1)

        # estado do áudio: clicar liga/desliga
        self.power = QPushButton()
        self.power.setObjectName("flat")
        self.power.setCheckable(True)
        self.power.setFocusPolicy(Qt.NoFocus)
        self.power.setToolTip("Clique para ligar ou desligar o áudio")
        self.power.setCursor(Qt.PointingHandCursor)
        pl = QHBoxLayout(self.power)
        pl.setContentsMargins(8, 2, 8, 2)
        self.dot = _Dot()
        pl.addWidget(self.dot)
        ptxt = QVBoxLayout()
        ptxt.setSpacing(0)
        self.power_title = QLabel("Áudio")
        self.power_state = QLabel("Desligado")
        self.power_state.setObjectName("small")
        ptxt.addWidget(self.power_title)
        ptxt.addWidget(self.power_state)
        pl.addLayout(ptxt)
        self.power.setMinimumSize(150, 46)
        # sem passar pelo argumento do clicked(): no PySide6 ele pode vir vazio
        self.power.clicked.connect(lambda *_: self.powerToggled.emit(self.power.isChecked()))
        lay.addWidget(self.power)

        self.info = QPushButton()
        self.info.setObjectName("flat")
        self.info.setFocusPolicy(Qt.NoFocus)
        self.info.setToolTip("Placa de som, driver (ASIO/WASAPI), taxa e buffer")
        il = QVBoxLayout(self.info)
        il.setContentsMargins(8, 2, 8, 2)
        il.setSpacing(0)
        self.info1 = QLabel("Sem placa escolhida")
        self.info2 = QLabel("clique para configurar")
        self.info2.setObjectName("small")
        il.addWidget(self.info1)
        il.addWidget(self.info2)
        self.info.setMinimumSize(168, 46)
        self.info.setCursor(Qt.PointingHandCursor)
        self.info.clicked.connect(lambda *_: self.audioSettings.emit())
        lay.addWidget(self.info)
        lay.addWidget(self._sep())

        # preset da aba aberta
        pcol = QVBoxLayout()
        pcol.setSpacing(2)
        plab = QLabel("Preset")
        plab.setObjectName("small")
        pcol.addWidget(plab)
        prow = QHBoxLayout()
        prow.setSpacing(4)
        self.prev_btn = self._icon_btn("left", "Preset anterior", lambda: self.presetStep.emit(-1))
        prow.addWidget(self.prev_btn)
        self.preset_stack = QStackedWidget()
        self.preset_stack.setFixedWidth(226)
        prow.addWidget(self.preset_stack)
        self.next_btn = self._icon_btn("right", "Próximo preset", lambda: self.presetStep.emit(1))
        prow.addWidget(self.next_btn)
        self.save_btn = self._icon_btn("save", "Salvar como preset meu", self.presetSave.emit)
        prow.addWidget(self.save_btn)
        pcol.addLayout(prow)
        lay.addLayout(pcol)
        lay.addWidget(self._sep())

        self.update_btn = QPushButton(" Reiniciar para atualizar")
        self.update_btn.setObjectName("primary")
        self.update_btn.setIcon(icon("refresh", "#ffffff", 16))
        self.update_btn.setFocusPolicy(Qt.NoFocus)
        self.update_btn.setMinimumHeight(38)
        self.update_btn.setVisible(False)
        lay.addWidget(self.update_btn)
        self.file_btn = QPushButton(" Arquivo")
        self.file_btn.setIcon(icon("folder", C["text"], 18))
        self.file_btn.setFocusPolicy(Qt.NoFocus)
        self.file_btn.setToolTip("Salvar e abrir cenas e presets em arquivo, importar e compartilhar")
        self.file_btn.setMinimumHeight(38)
        lay.addWidget(self.file_btn)
        self.menu_btn = QPushButton()
        self.menu_btn.setIcon(icon("menu", C["text"], 18))
        self.menu_btn.setFocusPolicy(Qt.NoFocus)
        self.menu_btn.setFixedSize(40, 38)
        self.menu_btn.setToolTip("Menu")
        lay.addWidget(self.menu_btn)

    def _sep(self):
        s = QFrame()
        s.setObjectName("sep")
        s.setFixedHeight(40)
        return s

    def _icon_btn(self, name, tip, slot):
        b = QPushButton()
        b.setIcon(icon(name, C["text"], 16))
        b.setFixedSize(32, 32)
        b.setFocusPolicy(Qt.NoFocus)
        b.setToolTip(tip)
        b.clicked.connect(slot)
        return b

    # ------------------------------------------------------------------ estado
    def set_page(self, i):
        for j, b in enumerate(self.nav):
            b.setChecked(j == i)
        self.preset_stack.setCurrentIndex(i)

    def set_audio(self, running, line1, line2, error=False):
        self.power.setChecked(running)
        self.dot.set_color(C["green"] if running else (C["red"] if error else C["faint"]))
        self.power_title.setText("Áudio ligado" if running else "Áudio desligado")
        self.power_state.setText("clique para desligar" if running else
                                 ("erro · clique para tentar" if error else "clique para ligar"))
        self.power_state.setObjectName("ok" if running else ("bad" if error else "small"))
        self.power_title.setStyleSheet(f"color: {C['green'] if running else C['text']}; font-weight: 600;")
        self.power_state.setStyleSheet(f"color: {C['red'] if error else C['dim']}; font-size: 8.5pt;")
        self.info1.setText(line1)
        self.info2.setText(line2)

    def set_menu(self, file_menu, main_menu: QMenu):
        self.file_btn.setMenu(file_menu)
        self.menu_btn.setMenu(main_menu)
