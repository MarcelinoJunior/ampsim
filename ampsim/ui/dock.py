"""Barra inferior com abas: Pads, Mixer, MIDI / Controlador e Configurações.

Pode ser recolhida (fica só a fileira de abas) para sobrar tela nas abas de guitarra/baixo.
"""
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSlider,
    QStackedWidget, QVBoxLayout, QWidget,
)

from ..instruments import (
    BUTTON_FUNCS, BUTTONS, CONT_PAD_SOUNDS, KNOB_COUNT, KNOB_FUNCS, PAD_B_CHOICES, PAD_COUNT, PAD_PRESETS,
    note_name,
)
from ..dsp.params import TRACK_PARAMS
from .funcs import FUNC_RANGES, func_value, set_func
from .icons import icon
from .theme import C
from .widgets import Meter, ToggleSwitch

TABS = (("Pads", "pads"), ("Mixer", "mixer"), ("MIDI / Controlador", "midi"), ("Configurações", "gear"))
DOCK_H = 196
VOL_RANGE = next((p.lo, p.hi) for p in TRACK_PARAMS if p.key == "volume")


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

    # ------------------------------------------------------------------ Mixer
    def _build_mixer(self):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.setSpacing(8)
        self.strips = []
        chans = (("Guitarra", ("track", "guitar")), ("Baixo", ("track", "bass")),
                 ("Teclas", ("func", "Volume teclas")), ("Camada 2", ("func", "Volume camada 2")),
                 ("Bateria", ("func", "Volume bateria")), ("Pad contínuo", ("func", "Volume pad contínuo")),
                 ("Sala bateria", ("func", "Reverb da bateria")), ("Trilha Pad/Piano", ("track", "pads")),
                 ("Master", ("func", "Master")))
        for label, target in chans:
            box = QFrame()
            box.setObjectName("card")
            box.setFixedWidth(118 if label != "Master" else 130)
            bl = QGridLayout(box)
            bl.setContentsMargins(8, 6, 8, 6)
            bl.setSpacing(2)
            t = QLabel(label)
            t.setAlignment(Qt.AlignCenter)
            bl.addWidget(t, 0, 0, 1, 2)
            s = QSlider(Qt.Vertical)
            s.setFocusPolicy(Qt.NoFocus)
            s.setRange(0, 100)
            s.setMinimumHeight(86)
            s.valueChanged.connect(lambda v, tg=target: self._mix(tg, v))
            bl.addWidget(s, 1, 0, Qt.AlignHCenter)
            m = Meter()
            m.setMinimumHeight(86)
            bl.addWidget(m, 1, 1, Qt.AlignHCenter)
            val = QLabel("")
            val.setObjectName("small")
            val.setAlignment(Qt.AlignCenter)
            bl.addWidget(val, 2, 0, 1, 2)
            self.strips.append((target, s, val, m))
            lay.addWidget(box)
        lay.addStretch(1)
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
            self.win.refresh_sounds()
        self._strip_text()

    def _strip_text(self):
        for (kind, arg), s, val, _m in self.strips:
            if kind == "track":
                val.setText(f"{self.engine.tracks[arg].values['track']['volume']:+.0f} dB")
            else:
                val.setText(f"{s.value()}%")

    def update_meters(self, peaks):
        """peaks: {"guitar": p, "bass": p, "pads": p, "master": p}"""
        if self.collapsed or self.stack.currentIndex() != 1:
            return
        for (kind, arg), _s, _v, m in self.strips:
            if kind == "track":
                m.push(peaks.get(arg, 0.0))
            elif arg == "Master":
                m.push(peaks.get("master", 0.0))
            else:
                m.push(peaks.get("pads", 0.0))

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
                c.setMinimumWidth(100)
                c.setMaximumWidth(170)
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
        return w

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
        about.clicked.connect(lambda: self.win.file_menu.about())
        row.addWidget(about)
        row.addStretch(1)
        col.addLayout(row)
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
                b.setText(f"{_short(inst.pad_sounds[i].split(' — ')[0], 14)}\n{note}")
                b.setToolTip(f"Pad {i + 1}: {inst.pad_sounds[i]}\nClique: tocar · botão direito: trocar o som")
            for (kind, arg), s, _val, _m in self.strips:
                if kind == "track":
                    lo, hi = VOL_RANGE
                    db = self.engine.tracks[arg].values["track"]["volume"]
                    s.setValue(round((db - lo) / (hi - lo) * 100))
                else:
                    _, lo, hi, _ = FUNC_RANGES[arg]
                    s.setValue(round((func_value(self.engine, arg) - lo) / (hi - lo) * 100))
            for i, c in enumerate(self.padb_combos):
                c.setCurrentText(inst.pad_keys[i])
            for i, c in enumerate(self.knob_combos):
                c.setCurrentText(inst.knob_funcs[i])
            for i, c in enumerate(self.button_combos):
                c.setCurrentText(inst.button_funcs[i])
            self.use_amp.setChecked(bool(self.engine.tracks["pads"].values["track"].get("use_amp", False)))
            self.power_btn.setText("Desligar áudio" if self.engine.running else "Ligar áudio")
        finally:
            self._updating = False
        self._strip_text()
        self.on_learn()


assert all(f in FUNC_RANGES for f in KNOB_FUNCS if f not in ("Nenhuma", "BPM"))
