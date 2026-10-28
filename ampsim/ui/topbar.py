"""Barra superior: logo, abas grandes, estado do áudio, preset da aba com ‹ ›, Arquivo e menu."""
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from .icons import icon, pixmap
from ..version import version_text
from .theme import ACCENT, C

NAV = (("guitar", "Guitarra", "guitar"), ("bass", "Baixo", "bass"), ("pads", "Pad/Piano", "keys"),
       ("vocal", "Vocal", "mic"))


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
    presetChosen = Signal()          # escolheu um preset na lista da barra (depois de a aba carregá-lo)

    def __init__(self):
        super().__init__()
        self.setObjectName("topbar")
        self.setFixedHeight(66)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 12, 8)
        lay.setSpacing(7)

        logo = QLabel()
        logo.setPixmap(pixmap("logo", ACCENT, 34))
        lay.addWidget(logo)
        # nome e versão: somem na janela estreita (a versão continua em ☰ → Sobre)
        self.names_box = QWidget()
        names = QVBoxLayout(self.names_box)
        names.setContentsMargins(0, 0, 0, 0)
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
        lay.addWidget(self.names_box)
        lay.addSpacing(6)

        self.nav = []
        self._nav_icons = []
        for i, (_key, text, ic) in enumerate(NAV):
            b = QPushButton(text)
            b.setObjectName("nav")
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)
            self._nav_icons.append(icon(ic, C["text"], 22))
            b.setIcon(self._nav_icons[-1])
            b.setIconSize(QSize(22, 22))
            b.setMinimumHeight(48)          # largura mínima = a do texto já com o estilo (nada de "Pad/Pianc")
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
        self.power.setMinimumSize(136, 46)
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
        self.info.setMinimumSize(146, 46)
        self.info.setCursor(Qt.PointingHandCursor)
        self.info.clicked.connect(lambda *_: self.audioSettings.emit())
        lay.addWidget(self.info)
        # saúde do áudio: falhas no último minuto (ui/health.py); clique abre o histórico
        self.health_btn = QPushButton("")
        self.health_btn.setFocusPolicy(Qt.NoFocus)
        self.health_btn.setCursor(Qt.PointingHandCursor)
        self.health_btn.setFixedWidth(84)
        self.health_btn.setVisible(False)
        lay.addWidget(self.health_btn)
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
        self.preset_stack.setFixedWidth(190)
        self.preset_stack.widgetAdded.connect(self._watch_preset_combo)
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
        # tela remota (ampsim/web): celular/tablet na mesma rede como segunda tela
        self.web_btn = QPushButton(" Webserver")
        self.web_btn.setFocusPolicy(Qt.NoFocus)
        self.web_btn.setCursor(Qt.PointingHandCursor)
        self.web_btn.setMinimumHeight(38)
        self.web_btn.setIconSize(QSize(16, 16))
        self.web_btn.setStyleSheet("padding: 4px 8px;")
        self.set_web(False)
        lay.addWidget(self.web_btn)
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

    # ------------------------------------------------------------------ janela estreita (ex. 1366 px)
    # Três jeitos, do mais largo para o mais estreito: completo; abas sem ícone (o resto igual: cabe em
    # 1536 px com as 4 abas); compacto (sem o nome/versão, Webserver/Arquivo só com o ícone, abas com ícone).
    FULL, NO_NAV_ICONS, COMPACT = 0, 1, 2

    def _set_mode(self, mode):
        self._mode = mode
        self._compact = mode == self.COMPACT
        self.names_box.setVisible(not self._compact)
        self.web_btn.setText("" if self._compact else " Webserver")
        self.file_btn.setText("" if self._compact else " Arquivo")
        for b, ic in zip(self.nav, self._nav_icons):
            b.setIcon(QIcon() if mode == self.NO_NAV_ICONS else ic)
        self._fit_nav()

    def _set_compact(self, on):
        """Estreita: sem o nome/versão e Webserver/Arquivo só com o ícone (dica no mouse)."""
        self._set_mode(self.COMPACT if on else self.FULL)

    def _fit_nav(self):
        """Largura das abas com o texto em negrito (a aba marcada fica em negrito: sem "Pad/Pianc")."""
        for b in self.nav:
            b.ensurePolished()
            f = QFont(b.font())
            f.setWeight(QFont.DemiBold)
            text_w = QFontMetrics(f).horizontalAdvance(b.text())
            ic = b.iconSize().width() + 8 if not b.icon().isNull() else 0
            b.setMinimumWidth(text_w + ic + 26)

    def _measure(self):
        if getattr(self, "_min_full", None):
            return
        widths = {}
        for mode in (self.COMPACT, self.NO_NAV_ICONS, self.FULL):
            self._set_mode(mode)
            widths[mode] = self.layout().minimumSize().width()
        self._min_compact, self._min_mid, self._min_full = (widths[self.COMPACT], widths[self.NO_NAV_ICONS],
                                                            widths[self.FULL])

    def minimumSizeHint(self):
        self._measure()
        return QSize(self._min_compact, self.height() or 66)

    def resizeEvent(self, e):
        self._measure()
        w = e.size().width()
        want = self.FULL if w >= self._min_full else self.NO_NAV_ICONS if w >= self._min_mid else self.COMPACT
        if want != getattr(self, "_mode", None):
            self._set_mode(want)
        super().resizeEvent(e)

    def _watch_preset_combo(self, i):
        """Lista de presets de uma aba entrou na barra: escolher nela também move o destaque do Banco de
        presets (como ◀ ▶ e a tela remota). Roda depois do carregamento feito pela própria aba."""
        combo = self.preset_stack.widget(i)
        if hasattr(combo, "activated"):
            combo.activated.connect(lambda *_: QTimer.singleShot(0, self._preset_chosen))

    def _preset_chosen(self):
        self.presetChosen.emit()
        win = self.window()
        sync = getattr(win, "_sync_bank", None)       # janela principal: o Banco mostra o preset escolhido
        if callable(sync):
            sync()

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

    def set_web(self, on, clients=0, url=""):
        self.web_btn.setIcon(icon("globe", C["green"] if on else C["dim"], 16))
        # largura fixa (a barra é justa em 1536 px): quantos aparelhos fica no ícone/dica
        self.web_btn.setText("" if getattr(self, "_compact", False) else " Webserver")
        self.web_btn.setProperty("clients", clients if on else 0)
        self.web_btn.setToolTip((f"Tela remota ligada em {url}\n{clients} aparelho(s) conectado(s)\n" if on else
                                 "Tela remota desligada\n") + "Clique para configurar")

    def set_menu(self, file_menu, main_menu: QMenu):
        self.file_btn.setMenu(file_menu)
        self.menu_btn.setMenu(main_menu)
