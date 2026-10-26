"""Barra inferior com abas: Pads, Mixer, MIDI / Controlador e Configurações.

Pode ser recolhida (fica só a fileira de abas) para sobrar tela nas abas de guitarra/baixo.
"""
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QListWidget, QPushButton, QSlider,
    QStackedWidget, QVBoxLayout, QWidget,
)

from ..instruments import (
    BUTTON_FUNCS, BUTTONS, CONT_PAD_SOUNDS, KNOB_COUNT, KNOB_FUNCS, PAD_B_CHOICES, PAD_COUNT, PAD_PRESETS,
    note_name,
)
from ..dsp.params import TRACK_PARAMS
from .funcs import FUNC_RANGES, func_value, set_func
from .icons import icon
from .recorder import pad_label
from .theme import C
from .widgets import Meter, ToggleSwitch

TABS = (("Pads", "pads"), ("Faders / Pads", "mixer"), ("MIDI / Controlador", "midi"), ("Configurações", "gear"))
DOCK_H = 196
VOL_RANGE = next((p.lo, p.hi) for p in TRACK_PARAMS if p.key == "volume")
MUTE_ON = (f"QPushButton {{ background: {C['red']}; border: 1px solid #ff8a96; color: white; "
           "font-weight: 800; font-size: 8pt; border-radius: 5px; padding: 0; }")
MUTE_OFF = (f"QPushButton {{ background: {C['card']}; border: 1px solid {C['border2']}; color: {C['dim']}; "
            f"font-weight: 700; font-size: 8pt; border-radius: 5px; padding: 0; }}"
            f"QPushButton:hover {{ border-color: {C['red']}; color: #ff9aa5; }}")
SLIDER_MUTED = (f"QSlider::groove:vertical {{ background: #5a1e2a; width: 4px; border-radius: 2px; }}"
                f"QSlider::handle:vertical {{ background: {C['red']}; border: 2px solid #ff8a96; height: 14px;"
                " width: 14px; margin: 0 -6px; border-radius: 8px; }"
                "QSlider::add-page:vertical, QSlider::sub-page:vertical { background: #5a1e2a; }")
# faders da aba Faders / Pads: (rótulo, tipo, função ou trilha, camada, tem mute de emergência)
STRIPS = (("L1", "func", "Volume camada 1", 1, True), ("L2", "func", "Volume camada 2", 2, True),
          ("L3", "func", "Volume camada 3", 3, True), ("L4", "func", "Volume camada 4", 4, True),
          ("Pad\ncontínuo", "func", "Volume pad contínuo", None, True), ("Pads", "func", "Volume bateria", None, True),
          ("Teclas\n(todas)", "func", "Volume teclas", None, False), ("Guitarra", "track", "guitar", None, False),
          ("Baixo", "track", "bass", None, False), ("Master", "func", "Master", None, False))


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
        lay.setContentsMargins(10, 6, 10, 8)
        lay.setSpacing(6)
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
        self.stack.addWidget(self._build_pads())
        self.stack.addWidget(self._build_mixer())
        self.stack.addWidget(self._build_midi())
        self.stack.addWidget(self._build_settings())
        lay.addWidget(self.stack)
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
        self.setFixedHeight(48 if on else DOCK_H)
        self.collapsedChanged.emit(on)

    # ------------------------------------------------------------------ Pads
    def _build_pads(self):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.setSpacing(14)

        col = QVBoxLayout()
        col.setSpacing(6)
        head = QHBoxLayout()
        head.addWidget(_title("Pads Contínuos"))
        head.addStretch(1)
        eq = QPushButton(" EQ e ambiente")
        eq.setIcon(icon("eq", C["text"], 14))
        eq.setFocusPolicy(Qt.NoFocus)
        eq.setToolTip("Equalizador e ambiente do pad contínuo (cortar graves/agudos, reverb, shimmer, fades)")
        eq.clicked.connect(lambda: self.win.open_pad_eq())
        head.addWidget(eq)
        col.addLayout(head)
        grid = QGridLayout()
        grid.setSpacing(6)
        self.cont_tiles = []
        for i, name in enumerate(CONT_PAD_SOUNDS):
            b = QPushButton(f"Pad {i + 1}\n{name.replace('Pad ', '')}")
            b.setObjectName("tile")
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.setFixedSize(84, 54)
            b.setToolTip(f"Timbre do pad contínuo: {name}")
            b.clicked.connect(lambda _, n=name: self._cont_sound(n))
            self.cont_tiles.append(b)
            grid.addWidget(b, i // 5, i % 5)
        col.addLayout(grid)
        lay.addLayout(col)
        lay.addWidget(_vsep())

        col = QVBoxLayout()
        col.setSpacing(6)
        head = QHBoxLayout()
        head.addWidget(_title("Pads de Bateria"))
        head.addStretch(1)
        self.pad_preset = _combo(list(PAD_PRESETS) + ["(personalizado)"], 190)
        self.pad_preset.setToolTip("Conjunto de sons dos 8 pads")
        self.pad_preset.activated.connect(self._pad_preset)
        head.addWidget(self.pad_preset)
        col.addLayout(head)
        grid = QGridLayout()
        grid.setSpacing(6)
        self.drum_tiles = []
        for i in range(PAD_COUNT):
            b = QPushButton("")
            b.setObjectName("tile")
            b.setFocusPolicy(Qt.NoFocus)
            b.setFixedSize(98, 54)
            b.pressed.connect(lambda i=i: self.inst.pad_hit(i, 110))
            b.setContextMenuPolicy(Qt.CustomContextMenu)
            b.customContextMenuRequested.connect(lambda _, i=i: self.win.choose_pad_sound(i))
            self.drum_tiles.append(b)
            grid.addWidget(b, i // 4, i % 4)
        col.addLayout(grid)
        lay.addLayout(col)
        lay.addWidget(_vsep())

        col = QVBoxLayout()
        col.setSpacing(6)
        col.addWidget(_title("Mapeamento de Controlador"))
        card = QPushButton()
        card.setFocusPolicy(Qt.NoFocus)
        card.setMinimumHeight(54)
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
        self.map_hint = QLabel("Atribua pads, knobs e botões do seu teclado às funções do AmpSim.\n"
                               "Botão direito em qualquer knob ou botão da tela: mapear controle físico.")
        self.map_hint.setObjectName("small")
        self.map_hint.setWordWrap(True)
        col.addWidget(self.map_hint)
        col.addStretch(1)
        lay.addLayout(col, 1)
        return w

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

        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(_title("Faders"))
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
            name.setFixedSize(56, 26)
            sl = QHBoxLayout()
            sl.setSpacing(2)
            sl.addStretch(1)
            s = QSlider(Qt.Vertical)
            s.setRange(0, 100)
            s.setFocusPolicy(Qt.NoFocus)
            s.setMinimumHeight(48)
            s.valueChanged.connect(lambda v, tg=(kind, arg): self._mix(tg, v))
            sl.addWidget(s)
            m = None
            if kind == "track" or arg == "Master":
                m = Meter()
                m.setMinimumHeight(48)
                sl.addWidget(m)
            sl.addStretch(1)
            val = QLabel("")
            val.setObjectName("small")
            val.setAlignment(Qt.AlignCenter)
            val.setFixedWidth(56)
            box.addWidget(name)
            box.addLayout(sl, 1)
            box.addWidget(val)
            if mutable:
                mute = QPushButton("M")
                mute.setCheckable(True)
                mute.setFocusPolicy(Qt.NoFocus)
                mute.setFixedSize(48, 20)
                mute.setStyleSheet(MUTE_OFF)
                mute.setToolTip("Mute de emergência: silencia sem mexer no fader (clique de novo para voltar)")
                mute.clicked.connect(lambda on, f=arg: self._mute(f, on))
                box.addWidget(mute, 0, Qt.AlignHCenter)
                self.mute_buttons[arg] = mute
                self.vol_faders.append((arg, layer, s, val, name))
            else:
                spacer = QLabel("")
                spacer.setFixedHeight(20)
                box.addWidget(spacer)
            row.addLayout(box)
            self.strips.append(((kind, arg), s, val, m, name, layer))
        col.addLayout(row, 1)
        lay.addLayout(col)
        lay.addWidget(_vsep())

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
            b.setFixedSize(94, 50)
            b.pressed.connect(lambda i=i: self.inst.pad_hit(i, 110))
            b.setContextMenuPolicy(Qt.CustomContextMenu)
            b.customContextMenuRequested.connect(lambda _, i=i: self.win.choose_pad_sound(i))
            self.mix_pad_tiles.append(b)
            grid.addWidget(b, i // 4, i % 4)
        col.addLayout(grid)
        col.addStretch(1)
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
                db = self.engine.tracks[arg].values["track"]["volume"]
                s.setValue(round((db - lo) / (hi - lo) * 100))
                val.setText(f"{db:+.0f} dB")
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
            s.setStyleSheet(SLIDER_MUTED if muted else "")
            if muted:                                   # fader lá em cima e sem som: deixa bem claro
                val.setText("SEM SOM")
                val.setStyleSheet(f"color: {C['red']}; font-weight: 800;")
                name.setStyleSheet(f"color: {C['red']}; font-weight: 700;")
            else:
                val.setText(f"{v}%" if ok else "—")
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

    def update_meters(self, peaks):
        """peaks: {"guitar": p, "bass": p, "pads": p, "master": p}"""
        if self.collapsed or self.stack.currentIndex() != 1:
            return
        for (kind, arg), _s, _v, m, _n, _l in self.strips:
            if m is None:
                continue
            m.push(peaks.get(arg if kind == "track" else "master", 0.0))

    # ------------------------------------------------------------------ MIDI / Controlador
    def _build_midi(self):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.setSpacing(14)
        col = QVBoxLayout()
        col.setSpacing(6)
        col.addWidget(_title("Entrada MIDI"))
        row = QHBoxLayout()
        self.midi_combo = _combo()
        self.midi_combo.setMinimumWidth(220)
        row.addWidget(self.midi_combo, 1)
        self.rescan = QPushButton()
        self.rescan.setIcon(icon("refresh", C["text"], 15))
        self.rescan.setToolTip("Procurar dispositivos MIDI")
        self.rescan.setFocusPolicy(Qt.NoFocus)
        row.addWidget(self.rescan)
        col.addLayout(row)
        self.learn_btn = QPushButton("Mapear meu controlador (assistente)…")
        self.learn_btn.setObjectName("primary")
        self.learn_btn.setFocusPolicy(Qt.NoFocus)
        self.learn_btn.setToolTip("Toque cada pad, gire cada knob e aperte cada botão quando o AmpSim pedir.")
        self.learn_btn.clicked.connect(lambda: None if self.inst.learn_steps else self.inst.start_learning())
        col.addWidget(self.learn_btn)
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
        row = QHBoxLayout()
        self.skip_btn = QPushButton("Pular")
        self.skip_btn.clicked.connect(self.inst.skip_learning_step)
        self.stop_btn = QPushButton("Parar")
        self.stop_btn.clicked.connect(self.inst.stop_learning)
        for b in (self.skip_btn, self.stop_btn):
            b.setFocusPolicy(Qt.NoFocus)
            row.addWidget(b)
        col.addLayout(row)
        self.learn_label = QLabel("")
        self.learn_label.setWordWrap(True)
        self.learn_label.setStyleSheet(f"color: {C['yellow']}; font-weight: 600;")
        col.addWidget(self.learn_label)
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
                c.setMinimumWidth(84)
                c.setMaximumWidth(150)
                if label.startswith("Pads"):
                    c.setToolTip(f"Pad {i + 1} do banco B: tom do pad contínuo")
                    c.activated.connect(lambda idx, i=i: self.inst.set_pad_key(i, PAD_B_CHOICES[idx]))
                elif label == "Knobs":
                    c.setToolTip(f"Knob {i + 1}")
                    c.activated.connect(lambda idx, i=i: self._knob_func(i, KNOB_FUNCS[idx]))
                else:
                    c.setToolTip(f"Botão {BUTTONS[i]}")
                    c.activated.connect(lambda idx, i=i: self._button_func(i, BUTTON_FUNCS[idx]))
                store.append(c)
                g.addWidget(c, r, i + 1)
        lay.addLayout(g, 1)
        lay.addWidget(_vsep())

        col = QVBoxLayout()
        col.setSpacing(4)
        head = QHBoxLayout()
        head.addWidget(_title("Monitor MIDI"), 1)
        copy = QPushButton()
        copy.setIcon(icon("copy", C["text"], 14))
        copy.setFixedSize(28, 24)
        copy.setFocusPolicy(Qt.NoFocus)
        copy.setToolTip("Copiar o registro (para pedir ajuda)")
        copy.clicked.connect(lambda *_: QGuiApplication.clipboard().setText("\n".join(self.midi_log)))
        head.addWidget(copy)
        col.addLayout(head)
        self.monitor = QListWidget()
        self.monitor.setFocusPolicy(Qt.NoFocus)
        self.monitor.setFixedWidth(270)
        self.monitor.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.monitor.setTextElideMode(Qt.ElideMiddle)
        self.monitor.setStyleSheet("QListWidget { font-size: 8.5pt; } QListWidget::item { padding: 1px 4px; }")
        self.monitor.setToolTip("O que chega do teclado MIDI e o que o AmpSim faz com cada mensagem.\n"
                                "Se apertar um botão e nada aparecer, ele não manda MIDI comum.")
        self.monitor.addItem("Mexa no teclado: as mensagens aparecem aqui")
        col.addWidget(self.monitor, 1)
        lay.addLayout(col)
        self.midi_log = []
        return w

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

    def on_learn(self):
        steps = self.inst.learn_steps
        self.skip_btn.setVisible(bool(steps))
        self.stop_btn.setVisible(bool(steps))
        m = self.inst.mapping
        knobs = sum(1 for k in m["knobs"] if k)
        btns = sum(1 for b in m["buttons"] if b)
        self.learn_label.setText(self.inst.learning_prompt() or
                                 f"Pads: nota {m['pads'][0][1]}… · knobs {knobs}/8 · botões {btns}/8")

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
        about = QPushButton(" Sobre e licenças")
        about.setIcon(icon("info", C["text"], 15))
        about.setFocusPolicy(Qt.NoFocus)
        about.clicked.connect(lambda *_: self.win.show_about())
        row.addWidget(about)
        row.addStretch(1)
        col.addLayout(row)
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
            for i, c in enumerate(self.padb_combos):
                c.setCurrentText(inst.pad_keys[i])
            for i, c in enumerate(self.knob_combos):
                c.setCurrentText(inst.knob_funcs[i])
            for i, c in enumerate(self.button_combos):
                c.setCurrentText(inst.button_funcs[i])
            self.use_amp.setChecked(bool(self.engine.tracks["pads"].values["track"].get("use_amp", False)))
            from .pad_piano import SIMPLE, is_simple
            self.device.setCurrentText(SIMPLE if is_simple(inst.device) else inst.device)
            self.power_btn.setText("Desligar áudio" if self.engine.running else "Ligar áudio")
        finally:
            self._updating = False
        self.recorder._sources()
        self.on_learn()


assert all(f in FUNC_RANGES for f in KNOB_FUNCS if f not in ("Nenhuma", "BPM"))
