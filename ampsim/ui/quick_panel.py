"""Atalhos rápidos: painel de efeitos/volumes/navegação para qualquer teclado MIDI.

O teclado físico só toca as notas; cada controle da tela pode ser ligado a qualquer knob,
fader ou botão do controlador com o botão direito -> "Mapear controle físico…", que abre
um medidor ao vivo mostrando o que está chegando do aparelho.
"""
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu,
    QProgressBar, QPushButton, QSizePolicy, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..dsp.params import Param
from ..instruments import BUTTON_FUNCS, DELAY_DIVS, KNOB_FUNCS
from .widgets import Knob, PianoWidget

# (função, rótulo, faixa, padrão, unidade)
KNOB_GROUPS = (
    ("Efeitos das teclas", (
        ("Reverb", "Reverb", 0, 100, "%"), ("Chorus", "Chorus", 0, 100, "%"),
        ("Shimmer", "Shimmer", 0, 100, "%"), ("Rotação (intensidade)", "Rotação", 0, 100, "%"),
        ("Drive", "Drive", 0, 100, "%"), ("Delay (mix)", "Delay", 0, 100, "%"),
        ("Tempo do delay", "Tempo delay", 80, 1200, "ms"), ("Repetições do delay", "Repetições", 0, 100, "%"),
    )),
    ("Toque", (
        ("Ataque", "Ataque", 0, 100, "%"), ("Release", "Release", 0, 100, "%"),
        ("Brilho", "Brilho", 0, 100, "%"), ("Sensibilidade ao toque", "Toque", 0, 100, "%"),
    )),
    ("Volumes", (
        ("Volume teclas", "Teclas", 0, 100, "%"), ("Volume camada 2", "Camada 2", 0, 100, "%"),
        ("Volume bateria", "Bateria", 0, 100, "%"), ("Volume pad contínuo", "Pad contínuo", 0, 100, "%"),
        ("Master", "Master", 0, 100, "%"),
    )),
)
TOGGLES = (("Rotação lenta/rápida", "Rot. rápida"), ("Rotação liga/desliga", "Rotação"),
           ("Delay liga/desliga", "Delay"), ("Drive liga/desliga", "Drive"),
           ("Sustain (segurar)", "Sustain"))
ACTIONS = (("Timbre anterior", "◀ Timbre"), ("Próximo timbre", "Timbre ▶"), ("Oitava −", "Oitava −"),
           ("Oitava +", "Oitava +"), ("Liga/desliga camada 2", "Camada 2"), ("Tap tempo (BPM)", "Tap"),
           ("Parar pad contínuo", "Parar pad"), ("Pânico (soltar notas)", "Pânico"))


def key_text(k):
    if not k:
        return "não mapeado"
    kind, ch, num = k
    return f"{'CC' if kind == 'cc' else 'Nota'} {num} · canal {ch + 1}"


class MidiLearnDialog(QDialog):
    """Medidor ao vivo do controlador: mostra o que você está girando/apertando e mapeia."""

    def __init__(self, inst, bridge, func, parent=None):
        super().__init__(parent)
        self.inst = inst
        self.func = func
        self.choice = None
        self.setWindowTitle(f"Mapear: {func}")
        self.resize(460, 420)
        lay = QVBoxLayout(self)
        want = "gire o knob ou mova o fader" if func in KNOB_FUNCS else "aperte o botão ou pad"
        t = QLabel(f"<b>{func}</b><br>No seu controlador, {want} que quer usar.<br>"
                   "O último controle movido fica selecionado; clique em outro da lista se preferir.")
        t.setWordWrap(True)
        lay.addWidget(t)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Controle físico", "Valor", ""])
        self.tree.setColumnWidth(0, 200)
        self.tree.setColumnWidth(1, 150)
        self.tree.setRootIsDecorated(False)
        self.tree.itemClicked.connect(lambda *_: setattr(self, "_manual", True))
        lay.addWidget(self.tree, 1)
        self.current = QLabel(f"Atual: {key_text(inst.free_map.get(func))}")
        self.current.setObjectName("small")
        lay.addWidget(self.current)
        buttons = QDialogButtonBox()
        self.ok = buttons.addButton("Usar este controle", QDialogButtonBox.AcceptRole)
        rm = buttons.addButton("Remover mapeamento", QDialogButtonBox.ResetRole)
        buttons.addButton(QDialogButtonBox.Cancel)
        self.ok.setEnabled(False)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        rm.clicked.connect(self._remove)
        lay.addWidget(buttons)
        self._rows = {}
        self._manual = False
        self._bridge = bridge
        bridge.monitor.connect(self._activity)
        inst.capture = True
        self._fade = QTimer(self)
        self._fade.timeout.connect(self._decay)
        self._fade.start(80)

    def _activity(self, kind, ch, num, val):
        key = (kind, ch, num)
        it = self._rows.get(key)
        if it is None:
            it = QTreeWidgetItem([key_text(list(key)), "", ""])
            bar = QProgressBar()
            bar.setRange(0, 127)
            bar.setTextVisible(False)
            bar.setFixedHeight(12)
            self.tree.addTopLevelItem(it)
            self.tree.setItemWidget(it, 1, bar)
            self._rows[key] = it
            it.setData(0, Qt.UserRole, list(key))
        self.tree.itemWidget(it, 1).setValue(val if kind == "cc" else (127 if val > 0 else 0))
        it.setText(2, str(val))
        it.setData(0, Qt.UserRole + 1, time.monotonic())
        if not self._manual:
            self.tree.setCurrentItem(it)
        self.ok.setEnabled(True)

    def _decay(self):
        now = time.monotonic()
        for it in self._rows.values():
            age = now - (it.data(0, Qt.UserRole + 1) or 0)
            f = it.font(0)
            f.setBold(age < 0.6)
            it.setFont(0, f)

    def _accept(self):
        it = self.tree.currentItem()
        if it is not None:
            self.choice = it.data(0, Qt.UserRole)
            self.accept()

    def _remove(self):
        self.choice = []
        self.accept()

    def done(self, r):
        self.inst.capture = False
        try:
            self._bridge.monitor.disconnect(self._activity)
        except (RuntimeError, TypeError):
            pass
        super().done(r)


class _Mapped(QWidget):
    """Controle + etiqueta com o mapeamento físico; botão direito abre o mapeamento."""

    def __init__(self, panel, func, inner):
        super().__init__()
        self.panel = panel
        self.func = func
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(inner, 0, Qt.AlignHCenter)
        self.tag = QLabel("")
        self.tag.setAlignment(Qt.AlignCenter)
        self.tag.setFixedHeight(13)
        lay.addWidget(self.tag)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        inner.setContextMenuPolicy(Qt.CustomContextMenu)
        inner.customContextMenuRequested.connect(self._menu)

    def _menu(self, _pos):
        m = QMenu(self)
        m.addSection(self.func)
        a = m.addAction("Mapear controle físico…")
        a.triggered.connect(lambda: self.panel.learn(self.func))
        b = m.addAction("Remover mapeamento")
        b.setEnabled(self.func in self.panel.inst.free_map)
        b.triggered.connect(lambda: self.panel.unmap(self.func))
        m.exec(self.cursor().pos())

    def refresh(self):
        k = self.panel.inst.free_map.get(self.func)
        short = (f"{'CC' if k[0] == 'cc' else 'N'}{k[2]}" if k else "·")
        self.tag.setText("⇄ " + short if k else short)
        self.tag.setStyleSheet("color: #7fd1a0; font-size: 7.5pt;" if k else "color: #555b66; font-size: 7.5pt;")
        tip = (f"{self.func}\nMapeado em: {key_text(k)}" if k
               else f"{self.func}\nBotão direito: mapear controle físico")
        self.setToolTip(tip)


class QuickPanel(QWidget):
    def __init__(self, engine, bridge, accent):
        super().__init__()
        self.engine = engine
        self.inst = engine.instruments
        self.bridge = bridge
        self._updating = False
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        lcd_box = QHBoxLayout()
        lcd_box.setSpacing(0)
        self.lcd = QLabel("")
        self.lcd.setStyleSheet("background: #0b0f0d; color: #ff5a4f; font: bold 15pt 'Consolas';"
                               "border-top-left-radius: 6px; border-bottom-left-radius: 6px; padding: 3px 12px;")
        self.lcd2 = QLabel("")
        self.lcd2.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lcd2.setStyleSheet("background: #0b0f0d; color: #ffb0a8; font: 10pt 'Consolas';"
                                "border-top-right-radius: 6px; border-bottom-right-radius: 6px; padding: 3px 12px;")
        lcd_box.addWidget(self.lcd, 1)
        lcd_box.addWidget(self.lcd2)
        root.addLayout(lcd_box)

        self.items = {}
        self.knobs = {}
        groups = QHBoxLayout()
        groups.setSpacing(6)
        for title, knobs in KNOB_GROUPS:
            box = QFrame()
            box.setObjectName("effect")
            g = QGridLayout(box)
            g.setContentsMargins(8, 4, 8, 4)
            g.setSpacing(2)
            g.setAlignment(Qt.AlignTop)
            lab = QLabel(title)
            lab.setObjectName("fxtitle")
            g.addWidget(lab, 0, 0, 1, 4)
            for j, (func, label, lo, hi, unit) in enumerate(knobs):
                k = Knob(Param(func, label, lo, hi, lo, unit), accent)
                k.valueChanged.connect(lambda v, f=func: self._knob(f, v))
                w = _Mapped(self, func, k)
                self.items[func] = w
                self.knobs[func] = k
                g.addWidget(w, 1 + j // 4, j % 4)
            if title == "Efeitos das teclas":
                row = QHBoxLayout()
                row.addWidget(QLabel("Delay no tempo:"))
                self.delay_div = QComboBox()
                self.delay_div.setFocusPolicy(Qt.NoFocus)
                self.delay_div.addItems(DELAY_DIVS)
                self.delay_div.activated.connect(self._delay_div)
                row.addWidget(self.delay_div)
                row.addStretch(1)
                g.addLayout(row, 3, 0, 1, 4)
            groups.addWidget(box)
        root.addLayout(groups)

        buttons = QFrame()
        buttons.setObjectName("effect")
        bl = QHBoxLayout(buttons)
        bl.setContentsMargins(8, 4, 8, 4)
        self.toggles = {}
        for func, label in TOGGLES + ACTIONS:
            b = QPushButton(label)
            b.setFocusPolicy(Qt.NoFocus)
            b.setMinimumHeight(28)
            b.setMinimumWidth(72)
            if (func, label) in TOGGLES:
                b.setCheckable(True)
                b.setObjectName("seg")
                self.toggles[func] = b
            b.clicked.connect(lambda _, f=func: self._button(f))
            w = _Mapped(self, func, b)
            self.items[func] = w
            bl.addWidget(w)
        root.addWidget(buttons)

        self.piano = PianoWidget(36, 96)
        self.piano.setMinimumHeight(70)
        self.piano.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.piano.noteOn.connect(lambda n, v: self.inst.key_on(n, v))
        self.piano.noteOff.connect(lambda n: self.inst.key_off(n))
        root.addWidget(self.piano, 1)
        bridge.control.connect(self._from_midi)

    # ------------------------------------------------------------------ valores
    def _to_midi(self, func, v):
        p = self.knobs[func].p
        return round((v - p.lo) / (p.hi - p.lo) * 127)

    def _knob(self, func, v):
        if self._updating:
            return
        self.inst.apply_knob_func(func, self._to_midi(func, v))
        self.refresh_text()

    def _button(self, func):
        self.inst.do_button(func)
        self.refresh()

    def _delay_div(self, i):
        self.inst.fx["delay_div"] = i
        self.inst.fx["delay_on"] = True
        self.inst.apply_fx()
        self.refresh()

    def _from_midi(self, func, val):
        k = self.knobs.get(func)
        if k is not None:
            p = k.p
            k.setValue(p.lo + (p.hi - p.lo) * val / 127)
        self.refresh()

    def current(self, func):
        """Valor atual de cada função, na escala do knob."""
        i, lv, fx = self.inst, self.inst.levels, self.inst.fx
        pct127 = {"Reverb": lv["reverb"], "Chorus": lv["chorus"], "Ataque": lv["attack"],
                  "Release": lv["release"], "Brilho": lv["bright"]}
        if func in pct127:
            return pct127[func] / 1.27
        return {"Shimmer": lv["shimmer"], "Rotação (intensidade)": fx["rot_mix"], "Drive": fx["drive"],
                "Delay (mix)": fx["delay_mix"], "Tempo do delay": fx["delay_ms"],
                "Repetições do delay": fx["delay_fb"], "Sensibilidade ao toque": lv["touch"],
                "Volume teclas": lv["keys"], "Volume camada 2": i.keys["vol2"] / 1.27,
                "Volume bateria": lv["drums"], "Volume pad contínuo": lv["pad"],
                "Master": min(100.0, (self.engine.master / 2.0) ** 0.5 * 100)}.get(func, 0)

    # ------------------------------------------------------------------ mapeamento
    def learn(self, func):
        dlg = MidiLearnDialog(self.inst, self.bridge, func, self)
        if dlg.exec() and dlg.choice is not None:
            if dlg.choice:
                for f, k in list(self.inst.free_map.items()):     # um controle físico, uma função
                    if k == dlg.choice:
                        del self.inst.free_map[f]
                self.inst.free_map[func] = dlg.choice
            else:
                self.inst.free_map.pop(func, None)
        self.refresh()

    def unmap(self, func):
        self.inst.free_map.pop(func, None)
        self.refresh()

    # ------------------------------------------------------------------ tela
    def refresh_text(self):
        i = self.inst
        flags = []
        if i.transpose:
            flags.append(f"oitava {i.transpose:+d}")
        if i.sustain:
            flags.append("sustain")
        if i.fx["rot_on"]:
            flags.append("rotação " + ("rápida" if i.fx["rot_fast"] else "lenta"))
        if i.fx["delay_on"]:
            flags.append("delay")
        if i.fx["drive_on"]:
            flags.append("drive")
        self.lcd.setText(i.display_text())
        self.lcd2.setText(f"BPM {i.bpm}   " + "  ·  ".join(flags))

    def refresh(self):
        self._updating = True
        try:
            for func, k in self.knobs.items():
                k.setValue(self.current(func))
            fx = self.inst.fx
            state = {"Rotação lenta/rápida": fx["rot_fast"], "Rotação liga/desliga": fx["rot_on"],
                     "Delay liga/desliga": fx["delay_on"], "Drive liga/desliga": fx["drive_on"],
                     "Sustain (segurar)": self.inst.sustain}
            for func, b in self.toggles.items():
                b.setChecked(bool(state.get(func)))
            self.delay_div.setCurrentIndex(fx.get("delay_div", 0))
        finally:
            self._updating = False
        for w in self.items.values():
            w.refresh()
        self.refresh_text()

    def show_key(self, note, on):
        self.piano.set_active(note, on)


assert all(f in KNOB_FUNCS for _, ks in KNOB_GROUPS for f, *_ in ks)
assert all(f in BUTTON_FUNCS for f, _ in TOGGLES + ACTIONS)
