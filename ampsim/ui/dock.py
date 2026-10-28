"""Barra inferior com abas: Pads, Mixer, MIDI / Controlador e Configurações.

Pode ser recolhida (fica só a fileira de abas) para sobrar tela nas abas de guitarra/baixo.
"""
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QListWidget, QMenu, QPushButton, QScrollArea,
    QSizePolicy, QStackedWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..instruments import (
    BUTTON_FUNCS, BUTTONS, CONT_PAD_SOUNDS, KNOB_COUNT, KNOB_FUNCS, PAD_B_CHOICES, PAD_COUNT, PAD_FOLLOW,
    PAD_PRESETS, PITCH_FUNCS, note_name,
)
from ..dsp.params import TRACK_PARAMS
from .funcs import FUNC_RANGES, func_value, set_func
from .icons import icon
from .midi_learn import key_text
from .recorder import pad_label
from .theme import C
from .deskfader import DeskFader, level_from_gr, level_from_peak
from .widgets import Meter, ToggleSwitch

TABS = (("Pads", "pads"), ("Faders / Pads", "mixer"), ("MIDI / Controlador", "midi"), ("Configurações", "gear"))
DOCK_H = 192                     # altura padrão da barra aberta
DOCK_MIN = 150                   # mínima (tela baixa, 1366x768): abaixo de DOCK_H a aba rola por dentro
MAX_H = 16777215
VOL_RANGE = next((p.lo, p.hi) for p in TRACK_PARAMS if p.key == "volume")
MUTE_ON = (f"QPushButton {{ background: {C['red']}; border: 1px solid #ff8a96; color: white; "
           "font-weight: 800; font-size: 8pt; border-radius: 5px; padding: 0; }")
MUTE_OFF = (f"QPushButton {{ background: {C['card']}; border: 1px solid {C['border2']}; color: {C['dim']}; "
            f"font-weight: 700; font-size: 8pt; border-radius: 5px; padding: 0; }}"
            f"QPushButton:hover {{ border-color: {C['red']}; color: #ff9aa5; }}")
# faders da aba Faders / Pads: (rótulo, tipo, função ou trilha, camada, tem mute de emergência)
STRIPS = (("L1", "func", "Volume camada 1", 1, True), ("L2", "func", "Volume camada 2", 2, True),
          ("L3", "func", "Volume camada 3", 3, True), ("L4", "func", "Volume camada 4", 4, True),
          ("Pad\ncontínuo", "func", "Volume pad contínuo", None, True),
          ("Pads", "func", "Volume bateria", None, True),
          ("Rotação", "func", "Rotação (intensidade)", None, False),
          ("Veloc.\nrotação", "func", "Rotação (velocidade)", None, False),
          ("Reverb", "func", "Reverb", None, False), ("Drive", "func", "Drive", None, False),
          ("Delay", "func", "Delay (mix)", None, False),
          ("Vocal", "track", "vocal", None, True),           # volume e mute da trilha Vocal (microfone)
          ("Master", "func", "Master", None, False), ("Comp.", "func", "Compressor", None, False))
STRIP_W = 42                     # largura de cada fader (14 faders + pads + gravador cabem em 1536 px)
# Compressor: 0 com o cursor em cima, 100 embaixo (a compressão "corta" os picos de cima para baixo)
INVERTED = ("Compressor",)


def _grow_tile(b, w, h):
    """Botão de pad com largura fixa e altura que cresce com a barra (mínimo h)."""
    b.setFixedWidth(w)
    b.setMinimumHeight(h)
    b.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)


def _title(text):
    t = QLabel(text)
    t.setObjectName("section")
    return t


def _combo(items=(), width=None):
    c = QComboBox()
    c.setFocusPolicy(Qt.NoFocus)
    c.addItems(list(items))
    if width:
        c.setFixedWidth(width)
    return c


def _vsep():
    s = QFrame()
    s.setObjectName("sep")
    return s


def _short(text, n):
    return text if len(text) <= n else text[: n - 1] + "…"


class _FreeLabel(QLabel):
    """Texto que quebra linha sem pedir altura ao layout (some o que não couber; a dica tem o texto todo)."""

    def hasHeightForWidth(self):
        return False

    def minimumSizeHint(self):
        return QSize(40, 0)

    def resizeEvent(self, e):
        """Mostra só as frases (linhas) que cabem inteiras: nada de linha cortada no meio."""
        super().resizeEvent(e)
        full = self.toolTip() or self.text()
        lines = full.split("\n")
        shown = ""
        for k in range(len(lines), 0, -1):
            cand = "\n".join(lines[:k])
            self.setText(cand)
            if QLabel.heightForWidth(self, self.width()) <= self.height():
                shown = cand
                break
        if self.text() != shown:
            self.setText(shown)


class BottomDock(QFrame):
    collapsedChanged = Signal(bool)

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.engine = win.engine
        self.inst = win.engine.instruments
        self.setObjectName("dock")
        self._updating = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 2, 10, 2)
        lay.setSpacing(4)
        bar = QHBoxLayout()
        bar.setSpacing(4)
        self.tab_buttons = []
        for i, (text, ic) in enumerate(TABS):
            b = QPushButton(" " + text)
            b.setObjectName("tab")
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.setIcon(icon(ic, C["dim"], 18, active="#ffffff"))
            b.setIconSize(QSize(18, 18))
            b.clicked.connect(lambda _, i=i: self.show_tab(i))
            self.tab_buttons.append(b)
            bar.addWidget(b)
        bar.addStretch(1)
        self.collapse_btn = QPushButton()
        self.collapse_btn.setObjectName("flat")
        self.collapse_btn.setFocusPolicy(Qt.NoFocus)
        self.collapse_btn.setFixedSize(34, 30)
        self.collapse_btn.clicked.connect(lambda: self.set_collapsed(not self.collapsed))
        bar.addWidget(self.collapse_btn)
        lay.addLayout(bar)
        self.stack = QStackedWidget()
        self.pages = []
        for page in (self._build_pads(), self._build_mixer(), self._build_midi(), self._build_settings()):
            sc = QScrollArea()
            sc.setFrameShape(QFrame.NoFrame)
            sc.setWidgetResizable(True)
            sc.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)     # só se a barra ficar apertada
            sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            sc.setWidget(page)
            self.pages.append(page)
            self.stack.addWidget(sc)
        self.stack.currentChanged.connect(lambda *_: self._fit_height())
        lay.addWidget(self.stack)
        self.faders_detached = False
        self.last_height = DOCK_H
        self.hold_height = 0                   # mínimo provisório ao expandir (já abre na altura escolhida)
        self.collapsed = False
        self.set_collapsed(False)
        self.show_tab(0)

    # ------------------------------------------------------------------ abas
    def show_tab(self, i):
        if self.collapsed:
            self.set_collapsed(False)
        self.stack.setCurrentIndex(i)
        for j, b in enumerate(self.tab_buttons):
            b.setChecked(j == i)
        self.refresh()

    def set_collapsed(self, on):
        keep = self.last_height                 # a altura escolhida antes de recolher
        self.collapsed = on
        self.stack.setVisible(not on)
        self.collapse_btn.setIcon(icon("up" if on else "down", C["dim"], 16))
        self.collapse_btn.setToolTip("Mostrar" if on else "Recolher")
        if on:
            for b in self.tab_buttons:
                b.setChecked(False)
        else:
            for j, b in enumerate(self.tab_buttons):
                b.setChecked(j == self.stack.currentIndex())
        panels = getattr(self.win, "panels", None)
        if panels is not None:
            panels.release_floor()              # o mínimo extra do centro é refeito depois (collapsedChanged)
        self._fit_height()
        self.last_height = keep                 # (o _fit_height pode ter redimensionado já)
        self.collapsedChanged.emit(on)

    def _fit_height(self):
        """Recolhida: 48 px fixos. Aberta: no mínimo DOCK_MIN (mais a rolagem de lado na janela estreita)
        e sem máximo: o divisor da janela aumenta a barra (faders mais altos, pads maiores)."""
        if self.collapsed:
            self.setFixedHeight(48)
            return
        sc = self.stack.currentWidget()
        extra = 0
        if sc is not None and sc.isVisible() and sc.widget().minimumSizeHint().width() > sc.viewport().width() + 1:
            extra = sc.horizontalScrollBar().sizeHint().height()
        self.setMinimumHeight(max(DOCK_MIN + extra, self.hold_height))
        self.setMaximumHeight(MAX_H)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if not self.collapsed:
            self._fit_height()
            if self.isVisible():
                self.last_height = self.height()      # para voltar a esta altura ao expandir

    # ------------------------------------------------------------------ Faders em subjanela própria
    def detach_faders(self):
        """Tira os faders da aba Faders / Pads (para a subjanela "Faders"). -> o widget dos faders."""
        if not self.faders_detached:
            self.mixer_lay.removeWidget(self.faders_box)
            self.mixer_lay.removeWidget(self.faders_sep)
            self.faders_sep.hide()
            self.faders_detached = True
        return self.faders_box

    def attach_faders(self):
        """Devolve os faders para a aba Faders / Pads."""
        if self.faders_detached:
            self.mixer_lay.insertWidget(0, self.faders_box)
            self.mixer_lay.insertWidget(1, self.faders_sep)
            self.faders_sep.show()
            self.faders_box.show()
            self.faders_detached = False

    # ------------------------------------------------------------------ Pads
    def _build_pads(self):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.setSpacing(14)

        col = QVBoxLayout()
        col.setSpacing(4)
        head = QHBoxLayout()
        head.addWidget(_title("Pads Contínuos"))
        head.addStretch(1)
        self.follow = _combo(PAD_FOLLOW)
        self.follow.setToolTip("Tom do pad contínuo: fixo (o botão escolhido) ou seguindo o acorde que você toca\n"
                               "na mão esquerda (abaixo do ponto de divisão do teclado). “No tempo”: a troca\n"
                               "espera a próxima batida do BPM. Só troca com o pad tocando.")
        self.follow.activated.connect(lambda i: self._pad_follow(PAD_FOLLOW[i]))
        head.addWidget(self.follow)
        eq = QPushButton(" EQ e ambiente")
        eq.setIcon(icon("eq", C["text"], 14))
        eq.setFocusPolicy(Qt.NoFocus)
        eq.setToolTip("Equalizador e ambiente do pad contínuo (cortar graves/agudos, reverb, shimmer, fades)")
        eq.clicked.connect(lambda: self.win.open_pad_eq())
        head.addWidget(eq)
        col.addLayout(head)
        grid = QGridLayout()
        grid.setSpacing(4)
        self.cont_tiles = []
        for i, name in enumerate(CONT_PAD_SOUNDS):
            b = QPushButton(f"Pad {i + 1}\n{name.replace('Pad ', '')}")
            b.setObjectName("tile")
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)
            _grow_tile(b, 84, 34)
            b.setToolTip(f"Timbre do pad contínuo: {name}")
            b.clicked.connect(lambda _, n=name: self._cont_sound(n))
            self.cont_tiles.append(b)
            grid.addWidget(b, i // 5, i % 5)
        col.addLayout(grid)
        lay.addLayout(col)
        lay.addWidget(_vsep())

        col = QVBoxLayout()
        col.setSpacing(4)
        head = QHBoxLayout()
        head.addWidget(_title("Pads de Bateria"))
        head.addStretch(1)
        self.pad_preset = _combo(list(PAD_PRESETS) + ["(personalizado)"], 190)
        self.pad_preset.setToolTip("Conjunto de sons dos 8 pads")
        self.pad_preset.activated.connect(self._pad_preset)
        head.addWidget(self.pad_preset)
        col.addLayout(head)
        grid = QGridLayout()
        grid.setSpacing(4)
        self.drum_tiles = []
        for i in range(PAD_COUNT):
            b = QPushButton("")
            b.setObjectName("tile")
            b.setFocusPolicy(Qt.NoFocus)
            _grow_tile(b, 98, 34)
            b.pressed.connect(lambda i=i: self.inst.pad_hit(i, 110))
            b.setContextMenuPolicy(Qt.CustomContextMenu)
            b.customContextMenuRequested.connect(lambda _, i=i: self.win.choose_pad_sound(i))
            self.drum_tiles.append(b)
            grid.addWidget(b, i // 4, i % 4)
        col.addLayout(grid)
        lay.addLayout(col)
        lay.addWidget(_vsep())

        col = QVBoxLayout()
        col.setSpacing(4)
        col.addWidget(_title("Mapeamento de Controlador"))
        card = QPushButton()
        card.setFocusPolicy(Qt.NoFocus)
        card.setMinimumHeight(46)
        cl = QHBoxLayout(card)
        ci = QLabel()
        ci.setPixmap(icon("midi", C["text"], 22).pixmap(22, 22))
        cl.addWidget(ci)
        cl.addWidget(QLabel("Configurar MIDI / Controlador"), 1)
        ar = QLabel()
        ar.setPixmap(icon("right", C["dim"], 14).pixmap(14, 14))
        cl.addWidget(ar)
        card.clicked.connect(lambda: self.show_tab(2))
        col.addWidget(card)
        self.map_hint = _FreeLabel("Atribua pads, knobs e botões do seu teclado às funções do AmpSim.\n"
                               "Botão direito em qualquer knob ou botão da tela: mapear controle físico.")
        self.map_hint.setObjectName("small")
        self.map_hint.setWordWrap(True)
        # a dica não pede altura (barra baixa em 1344x702: sem rolagem); com espaço ela aparece inteira
        self.map_hint.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Ignored)
        self.map_hint.setToolTip(self.map_hint.text())
        col.addWidget(self.map_hint, 1)
        col.addStretch(1)
        lay.addLayout(col, 1)
        return w

    def _pad_follow(self, mode):
        self.inst.set_pad_follow(mode)
        self.win.refresh_sounds()

    def _cont_sound(self, name):
        self.inst.set_cont_sound(name)
        self.refresh()

    def _pad_preset(self, i):
        names = list(PAD_PRESETS)
        if i < len(names):
            self.inst.set_pad_preset(names[i])
        self.refresh()

    # ------------------------------------------------------------------ Faders / Pads
    def _build_mixer(self):
        """Faders (com mute de emergência), os 8 pads para tocar e o gravador."""
        from .recorder import RecorderPanel

        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.setSpacing(10)
        self.mixer_lay = lay
        # os faders ficam num widget próprio: dá para levá-los para a subjanela "Faders" (outro monitor)
        self.faders_box = QWidget()
        col = QVBoxLayout(self.faders_box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        # (sem o título "Faders": a aba já se chama Faders / Pads e o trilho ganha altura para o cursor andar)
        row = QHBoxLayout()
        row.setSpacing(2)
        self.strips = []
        self.vol_faders = []
        self.mute_buttons = {}
        for label, kind, arg, layer, mutable in STRIPS:
            box = QVBoxLayout()
            box.setSpacing(1)
            name = QLabel(label)
            name.setObjectName("small")
            name.setAlignment(Qt.AlignCenter)
            name.setFixedSize(STRIP_W, 26)
            sl = QHBoxLayout()
            sl.setSpacing(2)
            sl.addStretch(1)
            # fader de mesa; o Master acende com o nível da saída e o Compressor com a redução (dentro do trilho)
            s = DeskFader(inverted=arg in INVERTED,
                          meter="level" if arg in ("Master", "vocal") else "gr" if arg == "Compressor" else None)
            s.valueChanged.connect(lambda v, tg=(kind, arg): self._mix(tg, v))
            sl.addWidget(s)
            m = None
            if kind == "track" and arg != "vocal":
                m = Meter()
                m.setMinimumHeight(48)
                sl.addWidget(m)
            sl.addStretch(1)
            val = QLabel("")
            val.setObjectName("small")
            val.setAlignment(Qt.AlignCenter)
            val.setFixedWidth(STRIP_W)
            box.addWidget(name)
            box.addLayout(sl, 1)
            box.addWidget(val)
            if mutable:
                mute = QPushButton("M")
                mute.setCheckable(True)
                mute.setFocusPolicy(Qt.NoFocus)
                mute.setFixedSize(STRIP_W - 2, 20)
                mute.setStyleSheet(MUTE_OFF)
                mute.setToolTip("Mute de emergência: silencia sem mexer no fader (clique de novo para voltar)"
                                + ("\nAtalho: Alt+V" if arg == "vocal" else ""))
                mute.clicked.connect(lambda on, f=arg: self._mute(f, on))
                box.addWidget(mute, 0, Qt.AlignHCenter)
                self.mute_buttons[arg] = mute
                self.vol_faders.append((arg, layer, s, val, name))
            elif arg == "Master":
                # plugins VST3 no Master (cadeia FX): no lugar do espaço vazio (a altura não muda); vai
                # junto com os faders para a subjanela "Faders"
                from .plugin_slot import FxButton
                fx = FxButton(lambda: getattr(self.engine, "master_chain", None),
                              lambda: self.win.open_master_plugin())
                fx.setFixedSize(STRIP_W - 2, 20)
                box.addWidget(fx, 0, Qt.AlignHCenter)
                self.master_fx = fx
            else:
                spacer = QLabel("")
                spacer.setFixedHeight(20)
                box.addWidget(spacer)
            row.addLayout(box)
            self.strips.append(((kind, arg), s, val, m, name, layer))
        col.addLayout(row, 1)
        lay.addWidget(self.faders_box)
        self.faders_sep = _vsep()
        lay.addWidget(self.faders_sep)

        col = QVBoxLayout()
        col.setSpacing(4)
        col.addWidget(_title("Pads"))
        grid = QGridLayout()
        grid.setSpacing(5)
        self.mix_pad_tiles = []
        for i in range(PAD_COUNT):
            b = QPushButton("")
            b.setObjectName("tile")
            b.setFocusPolicy(Qt.NoFocus)
            _grow_tile(b, 94, 46)
            b.pressed.connect(lambda i=i: self.inst.pad_hit(i, 110))
            b.setContextMenuPolicy(Qt.CustomContextMenu)
            b.customContextMenuRequested.connect(lambda _, i=i: self.win.choose_pad_sound(i))
            self.mix_pad_tiles.append(b)
            grid.addWidget(b, i // 4, i % 4)
        col.addLayout(grid, 1)
        lay.addLayout(col)
        lay.addWidget(_vsep())

        col = QVBoxLayout()
        col.setSpacing(4)
        col.addWidget(_title("Gravador"))
        self.recorder = RecorderPanel(self.win)
        col.addWidget(self.recorder, 1)
        lay.addLayout(col, 1)
        return w

    def _mix(self, target, v):
        if self._updating:
            return
        kind, arg = target
        if kind == "track":
            lo, hi = VOL_RANGE
            db = lo + (hi - lo) * v / 100
            self.engine.tracks[arg].set_param("track", "volume", db)
            self.win.refresh_track(arg)
        else:
            _, lo, hi, _ = FUNC_RANGES[arg]
            set_func(self.engine, arg, lo + (hi - lo) * v / 100)
            self.win.pad_view.refresh_values()      # a barra Volume do painel da direita acompanha
        self.refresh_levels()

    def _mute(self, func, on):
        if func == "vocal":                         # mute da trilha Vocal (com rampa, sem estalo)
            self.engine.tracks["vocal"].set_switch("mute", on)
            self.win.refresh_track("vocal")
            self.refresh_levels()
            return
        self.inst.set_mute(func, on)
        self.refresh_levels()
        self.win.pad_view.refresh_values()          # o painel da direita também avisa "MUDO"

    def _sync_strips(self):
        """Valor, camada existente e mute de cada fader (chamado com _updating ligado)."""
        count = self.inst.layer_count()
        for (kind, arg), s, val, _m, name, layer in self.strips:
            ok = layer is None or layer <= count
            s.setEnabled(ok)
            name.setEnabled(ok)
            if kind == "track":
                lo, hi = VOL_RANGE
                tv = self.engine.tracks[arg].values["track"]
                db = tv["volume"]
                s.setValue(round((db - lo) / (hi - lo) * 100))
                mute = self.mute_buttons.get(arg)
                muted = bool(tv.get("mute", False))
                off = not tv.get("on", True)
                if mute is not None:
                    mute.setChecked(muted)
                    mute.setText("MUDO" if muted else "M")
                    mute.setStyleSheet(MUTE_ON if muted else MUTE_OFF)
                s.set_muted(muted or off)
                if muted or off:
                    val.setText("SEM SOM" if muted else "deslig.")
                    val.setStyleSheet(f"color: {C['red']}; font-weight: 800; font-size: 7pt;" if muted else "")
                    name.setStyleSheet(f"color: {C['red']}; font-weight: 700;" if muted else "")
                else:
                    val.setText(f"{db:+.0f} dB")
                    val.setStyleSheet("")
                    name.setStyleSheet("")
                s.setToolTip("Vocal (microfone)" + (" — MUDO" if muted else " — trilha desligada (liga na aba Vocal)"
                                                    if off else ""))
                continue
            _, lo, hi, _ = FUNC_RANGES[arg]
            v = round((func_value(self.engine, arg) - lo) / (hi - lo) * 100) if ok else 0
            s.setValue(v)
            muted = arg in self.inst.mutes
            mute = self.mute_buttons.get(arg)
            if mute is not None:
                mute.setChecked(muted)
                mute.setText("MUDO" if muted else "M")
                mute.setStyleSheet(MUTE_ON if muted else MUTE_OFF)
            s.set_muted(muted)
            if muted:                                   # fader lá em cima e sem som: deixa bem claro
                val.setText("SEM SOM")
                val.setStyleSheet(f"color: {C['red']}; font-weight: 800; font-size: 7pt;")
                name.setStyleSheet(f"color: {C['red']}; font-weight: 700;")
            else:
                # Compressor em 0: desligado (como "desligado" na tela remota)
                val.setText(("desl." if arg == "Compressor" and v == 0 else f"{v}%") if ok else "—")
                val.setStyleSheet("")
                name.setStyleSheet("")
            s.setToolTip(arg + (" — MUDO (mute de emergência ligado)" if muted else "") if ok
                         else f"{arg}: adicione a camada {layer} no painel da direita (+)")

    def refresh_levels(self):
        """Só os faders: um knob, a barra do painel ou um fader mexeu em algum volume."""
        self._updating = True
        try:
            self._sync_strips()
        finally:
            self._updating = False

    def sync_master_fx(self):
        """Botão FX do Master: verde com plugin ligado, vermelho com erro (o botão também se atualiza
        sozinho a cada 0,4 s)."""
        if hasattr(self, "master_fx"):
            self.master_fx.sync()

    def update_meters(self, peaks):
        """peaks: {"guitar": p, "bass": p, "pads": p, "master": p}"""
        if (self.collapsed or self.stack.currentIndex() != 1) and not self.faders_detached:
            return
        for (kind, arg), s, _v, m, _n, _l in self.strips:
            if arg == "Master":
                s.set_meter(level_from_peak(peaks.get("master", 0.0)))
            elif arg == "vocal":
                s.set_meter(level_from_peak(peaks.get("vocal", 0.0)))
            elif arg == "Compressor":
                s.set_meter(level_from_gr(peaks.get("comp_gr", 0.0)))
            elif m is not None:
                m.push(peaks.get(arg if kind == "track" else "master", 0.0))

    # ------------------------------------------------------------------ MIDI / Controlador
    def _build_midi(self):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.setSpacing(14)
        col = QVBoxLayout()
        col.setSpacing(5)
        row = QHBoxLayout()
        row.addWidget(_title("Entrada MIDI"))
        self.midi_combo = _combo()
        self.midi_combo.setMinimumWidth(140)
        row.addWidget(self.midi_combo, 1)
        self.rescan = QPushButton()
        self.rescan.setIcon(icon("refresh", C["text"], 15))
        self.rescan.setToolTip("Procurar dispositivos MIDI")
        self.rescan.setFocusPolicy(Qt.NoFocus)
        self.rescan.setFixedWidth(34)
        row.addWidget(self.rescan)
        col.addLayout(row)
        row = QHBoxLayout()
        self.learn_btn = QPushButton("Mapear meu controlador…")
        self.learn_btn.setObjectName("primary")
        self.learn_btn.setFocusPolicy(Qt.NoFocus)
        self.learn_btn.clicked.connect(lambda: None if self.inst.learn_steps else self.inst.start_learning())
        row.addWidget(self.learn_btn, 1)
        self.skip_btn = QPushButton("Pular")
        self.skip_btn.clicked.connect(self.inst.skip_learning_step)
        self.stop_btn = QPushButton("Parar")
        self.stop_btn.clicked.connect(self.inst.stop_learning)
        for b in (self.skip_btn, self.stop_btn):
            b.setFocusPolicy(Qt.NoFocus)
            row.addWidget(b)
        col.addLayout(row)
        only = QHBoxLayout()
        for text, what, tip in (("Só os knobs", ("knobs",), "Gire cada knob quando pedir (o da tela pisca)"),
                                ("Só os pads", ("pads", "pads_b"), "Toque cada pad quando pedir (bancos A e B)"),
                                ("Só os botões", ("buttons",), "Aperte cada botão quando pedir (PLAY, STOP…)")):
            b = QPushButton(text)
            b.setFocusPolicy(Qt.NoFocus)
            b.setToolTip(tip)
            b.clicked.connect(lambda *_, w=what: None if self.inst.learn_steps else self.inst.start_learning(w))
            only.addWidget(b)
        col.addLayout(only)
        # última linha: a função do pitch; durante o assistente, o que tocar no controlador
        row = QHBoxLayout()
        self.pitch_label = QLabel("Pitch do controlador:")
        row.addWidget(self.pitch_label)
        self.pitch_combo = _combo(PITCH_FUNCS)
        self.pitch_combo.setToolTip("O que a alavanca/faixa de pitch do controlador faz:\n"
                                    "tom das teclas, velocidade da rotação (até 4× mais rápida ou ¼) ou\n"
                                    "tempo do delay (o dobro ou a metade). Solta no centro: volta ao normal.\n"
                                    "Também dá para escolher com o botão direito no pitch do desenho.")
        self.pitch_combo.activated.connect(lambda i: self.inst.set_pitch_func(PITCH_FUNCS[i]))
        row.addWidget(self.pitch_combo, 1)
        self.learn_label = QLabel("")
        self.learn_label.setStyleSheet(f"color: {C['yellow']}; font-weight: 600;")
        row.addWidget(self.learn_label, 1)
        col.addLayout(row)
        col.addStretch(1)
        lay.addLayout(col)
        lay.addWidget(_vsep())

        g = QGridLayout()
        g.setHorizontalSpacing(4)
        g.setVerticalSpacing(4)
        self.padb_combos, self.knob_combos, self.button_combos = [], [], []
        rows = (("Pads B (tom)", self.padb_combos, PAD_COUNT, PAD_B_CHOICES),
                ("Knobs", self.knob_combos, KNOB_COUNT, KNOB_FUNCS),
                ("Botões", self.button_combos, len(BUTTONS), BUTTON_FUNCS))
        for r, (label, store, n, choices) in enumerate(rows):
            lab = QLabel(label)
            lab.setObjectName("small")
            g.addWidget(lab, r, 0)
            for i in range(n):
                c = _combo(choices)
                c.setMinimumWidth(78)
                c.setMaximumWidth(150)
                c.setStyleSheet("QComboBox { font-size: 8.5pt; padding: 2px 3px; }")   # cabe mais do nome
                if label.startswith("Pads"):
                    c.setToolTip(f"Pad {i + 1} do banco B: tom do pad contínuo")
                    c.activated.connect(lambda idx, i=i: self.inst.set_pad_key(i, PAD_B_CHOICES[idx]))
                elif label == "Knobs":
                    c.setToolTip(f"Knob {i + 1}")
                    c.activated.connect(lambda idx, i=i: self._knob_func(i, KNOB_FUNCS[idx]))
                    c.setContextMenuPolicy(Qt.CustomContextMenu)
                    c.customContextMenuRequested.connect(lambda _, i=i, c=c: self._physical_menu("knob", i, c))
                else:
                    c.setToolTip(f"Botão {BUTTONS[i]}")
                    c.activated.connect(lambda idx, i=i: self._button_func(i, BUTTON_FUNCS[idx]))
                    c.setContextMenuPolicy(Qt.CustomContextMenu)
                    c.customContextMenuRequested.connect(lambda _, i=i, c=c: self._physical_menu("button", i, c))
                store.append(c)
                g.addWidget(c, r, i + 1)
        lay.addLayout(g, 1)
        lay.addWidget(_vsep())

        # última coluna: o monitor MIDI ou a lista de mapeamentos das abas e plugins (mesmo lugar, duas vistas)
        col = QVBoxLayout()
        col.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(4)
        self.view_monitor = QPushButton("Monitor")
        self.view_maps = QPushButton("Mapeamentos")
        for i, b in enumerate((self.view_monitor, self.view_maps)):
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.setStyleSheet(f"QPushButton {{ padding: 2px 6px; font-size: 8.5pt; border-radius: 5px; }}"
                            f"QPushButton:checked {{ background: {C['accent2']}; border-color: {C['accent']}; "
                            "color: white; }")
            b.clicked.connect(lambda _, i=i: self.show_midi_view(i))
            head.addWidget(b)
        self.view_maps.setToolTip("Controles do teclado ligados a Guitarra, Baixo, Vocal, plugins e atalhos do "
                                  "Pad/Piano (botão direito num knob ou botão dessas telas: mapear)")
        head.addStretch(1)
        copy = QPushButton()
        copy.setIcon(icon("copy", C["text"], 14))
        copy.setFixedSize(28, 24)
        copy.setFocusPolicy(Qt.NoFocus)
        copy.setToolTip("Copiar o registro (para pedir ajuda)")
        copy.clicked.connect(lambda *_: QGuiApplication.clipboard().setText("\n".join(self.midi_log)))
        head.addWidget(copy)
        self.copy_btn = copy
        self.rm_map_btn = QPushButton()
        self.rm_map_btn.setIcon(icon("close", C["text"], 13))
        self.rm_map_btn.setFixedSize(28, 24)
        self.rm_map_btn.setFocusPolicy(Qt.NoFocus)
        self.rm_map_btn.setToolTip("Remover o mapeamento escolhido")
        self.rm_map_btn.clicked.connect(lambda *_: self.remove_selected_map())
        head.addWidget(self.rm_map_btn)
        col.addLayout(head)
        self.midi_views = QStackedWidget()
        self.monitor = QListWidget()
        self.monitor.setFocusPolicy(Qt.NoFocus)
        self.monitor.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.monitor.setTextElideMode(Qt.ElideMiddle)
        self.monitor.setStyleSheet("QListWidget { font-size: 8.5pt; } QListWidget::item { padding: 1px 4px; }")
        self.monitor.setToolTip("O que chega do teclado MIDI e o que o AmpSim faz com cada mensagem.\n"
                                "Se apertar um botão e nada aparecer, ele não manda MIDI comum.")
        self.monitor.addItem("Mexa no teclado: aparece aqui")
        self.midi_views.addWidget(self.monitor)
        self.map_tree = QTreeWidget()
        self.map_tree.setHeaderHidden(True)
        self.map_tree.setColumnCount(2)
        self.map_tree.setIndentation(10)
        self.map_tree.setFocusPolicy(Qt.NoFocus)
        self.map_tree.setStyleSheet("QTreeWidget { font-size: 8.5pt; } QTreeWidget::item { padding: 0px 2px; }")
        self.map_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.map_tree.customContextMenuRequested.connect(self._map_menu)
        self.map_tree.itemDoubleClicked.connect(lambda it, _c: self._map_item_learn(it))
        self.map_tree.currentItemChanged.connect(lambda *_: self._map_buttons())
        self.midi_views.addWidget(self.map_tree)
        self.midi_views.setFixedWidth(240)
        col.addWidget(self.midi_views, 1)
        lay.addLayout(col)
        self.midi_log = []
        self.show_midi_view(0)
        return w

    # ------------------------------------------------------------------ lista de mapeamentos (abas e plugins)
    def show_midi_view(self, i):
        """0 = monitor MIDI, 1 = mapeamentos agrupados por aba."""
        self.midi_views.setCurrentIndex(i)
        self.view_monitor.setChecked(i == 0)
        self.view_maps.setChecked(i == 1)
        self.copy_btn.setVisible(i == 0)
        self.rm_map_btn.setVisible(i == 1)
        if i == 1:
            self.refresh_map_list()

    def map_rows(self):
        """[(grupo, id, texto, controle físico, ativo)] de todos os mapeamentos livres: atalhos do Pad/Piano
        (free_map) e controles das abas Guitarra/Baixo/Vocal e dos plugins (ctl_map), por aba."""
        from .. import midi_map as MM
        inst = self.inst
        rows = [("Pad/Piano", "free:" + f, f, k, True) for f, k in inst.free_map.items()]
        for tid, e in inst.ctl_map.items():
            info = MM.target_info(tid)
            if info is None:
                continue
            label = e.get("label") or info["label"]
            head = info["group"] + " › "
            text = label[len(head):] if label.startswith(head) else label
            rows.append((info["group"], tid, text, e["key"], inst.ctl.active(tid, e)))
        order = {g: i for i, g in enumerate(MM.GROUPS)}
        rows.sort(key=lambda r: (order.get(r[0], 99), r[2]))
        return rows

    def refresh_map_list(self):
        t = self.map_tree
        cur = t.currentItem()
        keep = cur.data(0, Qt.UserRole) if cur is not None else None
        t.clear()
        rows = self.map_rows()
        groups = {}
        for group, tid, text, key, ok in rows:
            g = groups.get(group)
            if g is None:
                g = QTreeWidgetItem([group, ""])
                f = g.font(0)
                f.setBold(True)
                g.setFont(0, f)
                g.setFlags(g.flags() & ~Qt.ItemIsSelectable)
                t.addTopLevelItem(g)
                groups[group] = g
            it = QTreeWidgetItem([text + ("" if ok else "  (plugin ausente)"), key_text(key).replace(" · canal ", " c")])
            it.setData(0, Qt.UserRole, tid)
            it.setToolTip(0, f"{group} › {text}\n{key_text(key)}" + ("" if ok else
                          "\nO plugin mapeado não está na cadeia: o mapeamento fica inativo")
                          + "\nBotão direito: mapear de novo ou remover")
            if not ok:
                it.setForeground(0, QColor(C["faint"]))
            g.addChild(it)
            if tid == keep:
                t.setCurrentItem(it)
        if not rows:
            it = QTreeWidgetItem(["Nenhum ainda: botão direito num knob, LED ou chave", ""])
            it.setFlags(Qt.NoItemFlags)
            t.addTopLevelItem(it)
            it2 = QTreeWidgetItem(["de Guitarra, Baixo, Vocal ou plugins.", ""])
            it2.setFlags(Qt.NoItemFlags)
            t.addTopLevelItem(it2)
        t.expandAll()
        t.resizeColumnToContents(1)
        t.setColumnWidth(0, max(120, t.viewport().width() - t.columnWidth(1) - 4))
        n = len(rows)
        self.view_maps.setText(f"Mapeamentos ({n})" if n else "Mapeamentos")
        self._map_buttons()

    def _map_buttons(self):
        it = self.map_tree.currentItem()
        self.rm_map_btn.setEnabled(bool(it is not None and it.data(0, Qt.UserRole)))

    def remove_map(self, tid):
        if tid.startswith("free:"):
            self.inst.free_map.pop(tid[5:], None)
            self.win.pad_view.refresh()
        else:
            self.inst.ctl_map.pop(tid, None)
        self.inst.on_learn()
        self.refresh_map_list()

    def remove_selected_map(self):
        it = self.map_tree.currentItem()
        tid = it.data(0, Qt.UserRole) if it is not None else None
        if tid:
            self.remove_map(tid)

    def _map_item_learn(self, it):
        tid = it.data(0, Qt.UserRole) if it is not None else None
        if not tid:
            return
        if tid.startswith("free:"):
            self.win.pad_view.learn(tid[5:])
        else:
            from . import ctl_map_ui
            ctl_map_ui.learn(self.win, tid, self)
        self.refresh_map_list()

    def _map_menu(self, pos):
        it = self.map_tree.itemAt(pos)
        tid = it.data(0, Qt.UserRole) if it is not None else None
        if not tid:
            return
        m = QMenu(self)
        m.addSection(it.text(0))
        m.addAction("Mapear de novo…", lambda: self._map_item_learn(it))
        m.addAction("Remover mapeamento", lambda: self.remove_map(tid))
        m.exec(self.map_tree.viewport().mapToGlobal(pos))

    def log_midi(self, text):
        """Uma linha no monitor (mais nova em cima); guarda as últimas 200 para copiar."""
        import time
        line = time.strftime("%H:%M:%S ") + text
        self.midi_log.append(line)
        del self.midi_log[:-200]
        if self.monitor.count() == 1 and not self.midi_log[:-1]:
            self.monitor.clear()
        self.monitor.insertItem(0, line)
        self.monitor.item(0).setToolTip(line)
        while self.monitor.count() > 40:
            self.monitor.takeItem(self.monitor.count() - 1)

    def _knob_func(self, i, f):
        self.inst.knob_funcs[i] = f
        self.win.refresh_sounds()

    def _button_func(self, i, f):
        self.inst.button_funcs[i] = f
        self.win.refresh_sounds()

    def _physical_menu(self, target, i, widget):
        """Botão direito num knob/botão da aba MIDI (vale também para os que o desenho não mostra)."""
        pv = self.win.pad_view
        cur = pv.physical_key(target, i)
        name = f"Knob {i + 1}" if target == "knob" else f"Botão {BUTTONS[i]}"
        m = QMenu(self)
        m.addSection(f"{name}: {key_text(cur)}")
        m.addAction("Mapear controle físico…", lambda: pv.map_physical(target, i))
        a = m.addAction("Remover mapeamento", lambda: pv.assign_physical(target, i, []))
        a.setEnabled(bool(cur))
        if target == "button":
            pv.latch_action(m, i)
        m.exec(widget.mapToGlobal(widget.rect().bottomLeft()))
        self.refresh()

    def on_learn(self):
        if self.midi_views.currentIndex() == 1:
            self.refresh_map_list()
        else:                                   # só o número no botão da vista
            n = len(self.inst.free_map) + len(self.inst.ctl_map)
            self.view_maps.setText(f"Mapeamentos ({n})" if n else "Mapeamentos")
        steps = self.inst.learn_steps
        learning = bool(steps)
        for w in (self.skip_btn, self.stop_btn, self.learn_label):
            w.setVisible(learning)
        for w in (self.pitch_label, self.pitch_combo):
            w.setVisible(not learning)
        m = self.inst.mapping
        knobs = sum(1 for k in m["knobs"] if k)
        btns = sum(1 for b in m["buttons"] if b)
        pads = sum(1 for k in m["pads"] + m["pads_b"] if k)
        self.learn_label.setText(self.inst.learning_prompt() or "")
        self.learn_btn.setToolTip("Toque cada pad, gire cada knob e aperte cada botão quando o AmpSim pedir.\n"
                                  f"Agora: pads {pads}/16 · knobs {knobs}/8 · "
                                  f"botões {btns}/8")

    # ------------------------------------------------------------------ Configurações
    def _build_settings(self):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.setSpacing(14)

        col = QVBoxLayout()
        col.setSpacing(6)
        col.addWidget(_title("Áudio"))
        self.audio_label = QLabel("")
        self.audio_label.setObjectName("small")
        self.audio_label.setWordWrap(True)
        col.addWidget(self.audio_label)
        row = QHBoxLayout()
        b = QPushButton(" Placa de som e driver…")
        b.setIcon(icon("gear", C["text"], 15))
        b.setFocusPolicy(Qt.NoFocus)
        b.clicked.connect(self.win.open_audio_dialog)
        row.addWidget(b)
        self.power_btn = QPushButton("Ligar áudio")
        self.power_btn.setObjectName("primary")
        self.power_btn.setFocusPolicy(Qt.NoFocus)
        self.power_btn.clicked.connect(lambda: self.win.toggle_power(not self.engine.running))
        row.addWidget(self.power_btn)
        row.addStretch(1)
        col.addLayout(row)
        inst_out = QPushButton(" Usar a saída do teclado (P10 / fones)…")
        inst_out.setIcon(icon("volume", C["text"], 15))
        inst_out.setFocusPolicy(Qt.NoFocus)
        inst_out.setToolTip("Som pela saída do próprio instrumento ligado no USB:\n"
                            "M-VAVE SMK-25, Yamaha PSR-E473 ou Roland VR-730 (se o Windows o vê como placa de som)")
        inst_out.clicked.connect(lambda *_: self.win.use_instrument_output())
        col.addWidget(inst_out, 0, Qt.AlignLeft)
        col.addStretch(1)
        lay.addLayout(col, 1)
        lay.addWidget(_vsep())

        col = QVBoxLayout()
        col.setSpacing(6)
        col.addWidget(_title("Teclado do computador"))
        self.kbd_enable = QCheckBox("Teclado do PC toca as notas")
        self.kbd_enable.setChecked(True)
        self.kbd_enable.setFocusPolicy(Qt.NoFocus)
        col.addWidget(self.kbd_enable)
        self.kbd_label = QLabel("")
        self.kbd_label.setObjectName("small")
        self.kbd_label.setWordWrap(True)
        col.addWidget(self.kbd_label)
        sc = QPushButton(" Teclas de atalho…")
        sc.setIcon(icon("tap", C["text"], 15))
        sc.setFocusPolicy(Qt.NoFocus)
        sc.setToolTip("Alt+Espaço: mute geral · Alt+1-4: mute das camadas · F1-F3: abas · Esc: pânico…\n"
                      "Clique para ver todos e trocar as teclas.")
        sc.clicked.connect(lambda *_: self.win.open_shortcuts())
        col.addWidget(sc, 0, Qt.AlignLeft)
        col.addStretch(1)
        lay.addLayout(col, 1)
        lay.addWidget(_vsep())

        col = QVBoxLayout()
        col.setSpacing(6)
        col.addWidget(_title("Pad/Piano"))
        g = QGridLayout()
        g.setSpacing(6)
        g.addWidget(QLabel("Teclado na tela:"), 0, 0)
        self.device = _combo()
        self.device.setMinimumWidth(230)
        g.addWidget(self.device, 0, 1)
        g.addWidget(QLabel("Teclas pelo amplificador:"), 1, 0)
        self.use_amp = ToggleSwitch()
        self.use_amp.setToolTip("Ligado: as teclas passam pelo amplificador, gabinete e pedais da trilha\n"
                                "Pad/Piano (ex.: timbre de guitarra). Desligado: som limpo.")
        g.addWidget(self.use_amp, 1, 1)
        col.addLayout(g)
        row = QHBoxLayout()
        panic = QPushButton(" Pânico (soltar todas as notas)")
        panic.setObjectName("danger")
        panic.setFocusPolicy(Qt.NoFocus)
        panic.clicked.connect(self.win.panic)
        row.addWidget(panic)
        packs_btn = QPushButton(" Timbres e plugins…")
        packs_btn.setIcon(icon("download", C["text"], 15))
        packs_btn.setFocusPolicy(Qt.NoFocus)
        packs_btn.setToolTip("Downloads: pianos gravados de instrumentos reais (Upright, YDP, Salamander) e "
                             "plugins de efeito grátis (Dragonfly Reverb): baixar ou remover")
        packs_btn.clicked.connect(lambda *_: self.win.open_packs())
        about = QPushButton(" Sobre e licenças")
        about.setIcon(icon("info", C["text"], 15))
        about.setFocusPolicy(Qt.NoFocus)
        about.clicked.connect(lambda *_: self.win.show_about())
        row.addWidget(about)
        row.addStretch(1)
        col.addLayout(row)
        col.addWidget(packs_btn, 0, Qt.AlignLeft)
        col.addStretch(1)
        lay.addLayout(col, 1)
        lay.addWidget(_vsep())

        col = QVBoxLayout()
        col.setSpacing(6)
        col.addWidget(_title("Atualizações"))
        self.auto_update = QCheckBox("Atualizar sozinho ao abrir")
        self.auto_update.setChecked(True)
        self.auto_update.setFocusPolicy(Qt.NoFocus)
        self.auto_update.setToolTip("Ao abrir, o AmpSim confere o GitHub e baixa a versão nova em segundo plano")
        col.addWidget(self.auto_update)
        self.version_label = QLabel("")
        self.version_label.setObjectName("small")
        self.version_label.setWordWrap(True)
        col.addWidget(self.version_label)
        self.check_btn = QPushButton(" Verificar agora")
        self.check_btn.setIcon(icon("refresh", C["text"], 15))
        self.check_btn.setFocusPolicy(Qt.NoFocus)
        self.check_btn.clicked.connect(lambda *_: self.win.check_updates(manual=True))
        col.addWidget(self.check_btn, 0, Qt.AlignLeft)
        col.addStretch(1)
        lay.addLayout(col, 1)
        return w

    # ------------------------------------------------------------------ atualização
    def refresh(self):
        inst = self.inst
        self._updating = True
        try:
            for b, name in zip(self.cont_tiles, CONT_PAD_SOUNDS):
                b.setChecked(inst.cont_sound == name)
            self.pad_preset.setCurrentText(inst.pad_preset or "(personalizado)")
            pads = inst.mapping.get("pads", [])
            for i, b in enumerate(self.drum_tiles):
                note = ""
                try:
                    note = note_name(int(pads[i][1]))
                except (IndexError, TypeError, ValueError):
                    pass
                b.setText(f"{_short(pad_label(inst.pad_sounds[i]), 14)}\n{note}")
                b.setToolTip(f"Pad {i + 1}: {inst.pad_sounds[i]}\nClique: tocar · botão direito: trocar o som")
                t = self.mix_pad_tiles[i]
                t.setText(f"Pad {i + 1}\n{_short(pad_label(inst.pad_sounds[i]), 15)}")
                t.setToolTip(b.toolTip())
            self._sync_strips()
            self.pitch_combo.setCurrentText(inst.pitch_func)
            self.follow.setCurrentText(inst.pad_follow)
            for i, c in enumerate(self.padb_combos):
                c.setCurrentText(inst.pad_keys[i])
            pv = self.win.pad_view
            for i, c in enumerate(self.knob_combos):
                c.setCurrentText(inst.knob_funcs[i])
                c.setToolTip(f"Knob {i + 1}: {inst.knob_funcs[i]}\nControle físico: "
                             f"{key_text(pv.physical_key('knob', i))}\nBotão direito: mapear ou remover")
            for i, c in enumerate(self.button_combos):
                c.setCurrentText(inst.button_funcs[i])
                c.setToolTip(f"Botão {BUTTONS[i]}: {inst.button_funcs[i]}\nControle físico: "
                             f"{key_text(pv.physical_key('button', i))}\nBotão direito: mapear ou remover")
            self.use_amp.setChecked(bool(self.engine.tracks["pads"].values["track"].get("use_amp", False)))
            from .pad_piano import SIMPLE, is_simple
            self.device.setCurrentText(SIMPLE if is_simple(inst.device) else inst.device)
            self.power_btn.setText("Desligar áudio" if self.engine.running else "Ligar áudio")
        finally:
            self._updating = False
        self.recorder._sources()
        self.on_learn()


assert all(f in FUNC_RANGES for f in KNOB_FUNCS if f not in ("Nenhuma", "BPM"))
