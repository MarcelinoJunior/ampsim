"""Aba Teclas & Pads: controlador na tela, timbres, kit dos pads e mapeamento do controlador."""
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QFont, QStandardItemModel
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QListWidget, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from ..instruments import (
    BUTTON_FUNCS, BUTTONS, CATEGORIES, DRUM_NAMES, KITS, KNOB_COUNT, KNOB_FUNCS, PAD_COUNT, READY,
    SOUNDS, note_name,
)
from .controller import ControllerWidget, pad_label

SPLIT_NOTES = list(range(36, 73))


class InstrumentBridge(QObject):
    """Recebe avisos das threads de MIDI/áudio e entrega na thread da interface."""
    pad = Signal(int, int)
    key = Signal(int, bool)
    knob = Signal(int, int)
    changed = Signal()
    learn = Signal()


def _combo(items=(), width=None):
    c = QComboBox()
    c.setFocusPolicy(Qt.NoFocus)
    c.addItems(list(items))
    if width:
        c.setFixedWidth(width)
    return c


def _sound_combo():
    c = _combo()
    model = c.model()
    for cat in CATEGORIES:
        c.addItem(f"──  {cat}  ──")
        if isinstance(model, QStandardItemModel):
            model.item(c.count() - 1).setEnabled(False)
        for s in SOUNDS:
            if s.cat == cat:
                c.addItem(s.name, s.name)
    c.setMaxVisibleItems(28)
    return c


class KeysView(QWidget):
    def __init__(self, engine, accent):
        super().__init__()
        self.engine = engine
        self.inst = engine.instruments
        self._updating = False
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(6)
        self.ctrl = ControllerWidget()
        top.addWidget(self.ctrl, 1)
        top.addWidget(self._build_sounds())
        root.addLayout(top, 1)
        root.addWidget(self._build_mapping())

        c = self.ctrl
        c.padPressed.connect(lambda i, v: self.inst.pad_hit(i, v))
        c.keyOn.connect(lambda n, v: self.inst.key_on(n, v))
        c.keyOff.connect(lambda n: self.inst.key_off(n))
        c.knobMoved.connect(lambda i, v: self.inst.set_knob(i, v))
        c.buttonPressed.connect(lambda i: self.inst.button(i))

    # ------------------------------------------------------------------ painel de timbres
    def _build_sounds(self):
        box = QFrame()
        box.setObjectName("effect")
        box.setFixedWidth(330)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(10, 6, 10, 8)
        lay.setSpacing(4)
        t = QLabel("Timbres prontos (louvor)")
        t.setObjectName("fxtitle")
        lay.addWidget(t)
        self.ready_list = QListWidget()
        self.ready_list.setFocusPolicy(Qt.NoFocus)
        f = QFont(self.ready_list.font())
        f.setPointSizeF(10)
        self.ready_list.setFont(f)
        self.ready_list.addItems(list(READY))
        self.ready_list.itemClicked.connect(lambda it: self.inst.set_ready(it.text()))
        lay.addWidget(self.ready_list, 1)

        g = QGridLayout()
        g.setHorizontalSpacing(6)
        g.setVerticalSpacing(3)
        g.addWidget(QLabel("Teclas:"), 0, 0)
        self.sound1 = _sound_combo()
        self.sound1.activated.connect(lambda _: self._sound_changed(1, self.sound1))
        g.addWidget(self.sound1, 0, 1, 1, 2)
        self.layer_on = QCheckBox("Camada 2:")
        self.layer_on.setFocusPolicy(Qt.NoFocus)
        self.layer_on.toggled.connect(self._layer_toggled)
        g.addWidget(self.layer_on, 1, 0)
        self.sound2 = _sound_combo()
        self.sound2.activated.connect(lambda _: self._sound_changed(2, self.sound2))
        g.addWidget(self.sound2, 1, 1, 1, 2)
        g.addWidget(QLabel("Modo:"), 2, 0)
        self.mode2 = _combo(("Sobreposta", "Mão esquerda"))
        self.mode2.setToolTip("Sobreposta: os dois timbres juntos em todas as teclas.\n"
                              "Mão esquerda: camada 2 só abaixo da nota de divisão (ex.: baixo).")
        self.mode2.activated.connect(self._mode_changed)
        g.addWidget(self.mode2, 2, 1)
        self.split = _combo([f"abaixo de {note_name(n)}" for n in SPLIT_NOTES], width=110)
        self.split.activated.connect(self._split_changed)
        g.addWidget(self.split, 2, 2)
        g.addWidget(QLabel("Kit dos pads:"), 3, 0)
        self.kit = _combo([k[0] for k in KITS])
        self.kit.activated.connect(lambda _: self.inst.set_kit(self.kit.currentText()))
        g.addWidget(self.kit, 3, 1, 1, 2)
        g.setColumnStretch(1, 1)
        lay.addLayout(g)
        self.sound_status = QLabel("")
        self.sound_status.setObjectName("small")
        self.sound_status.setWordWrap(True)
        lay.addWidget(self.sound_status)
        return box

    def _sound_changed(self, slot, combo):
        name = combo.currentData()
        if name:
            self.inst.set_sound(slot, name)

    def _layer_toggled(self, on):
        if self._updating:
            return
        self.inst.keys["layer2_on"] = on
        if on and not self.inst.keys["sound2"]:
            self.inst.keys["sound2"] = "Pad Quente"
        self.inst.ready = ""
        self.inst.apply_all()
        self.refresh()

    def _mode_changed(self, i):
        self.inst.keys["mode2"] = "split" if i == 1 else "layer"
        self.inst.ready = ""
        self.inst.all_off()
        self.refresh()

    def _split_changed(self, i):
        self.inst.keys["split"] = SPLIT_NOTES[i]
        self.inst.ready = ""
        self.inst.all_off()
        self.refresh()

    # ------------------------------------------------------------------ mapeamento
    def _build_mapping(self):
        box = QFrame()
        box.setObjectName("effect")
        box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        g = QGridLayout(box)
        g.setContentsMargins(10, 6, 10, 6)
        g.setHorizontalSpacing(4)
        g.setVerticalSpacing(3)
        drum_items = [f"{name} ({n})" for n, name in sorted(DRUM_NAMES.items())]
        self._drum_notes = sorted(DRUM_NAMES)
        self.pad_combos, self.knob_combos, self.button_combos = [], [], []
        for row, (label, count, items, store) in enumerate((
                ("Pads", PAD_COUNT, drum_items, self.pad_combos),
                ("Knobs", KNOB_COUNT, KNOB_FUNCS, self.knob_combos),
                ("Botões", len(BUTTONS), BUTTON_FUNCS, self.button_combos))):
            lab = QLabel(label + ":")
            lab.setObjectName("fxtitle")
            g.addWidget(lab, row, 0)
            for i in range(count):
                c = _combo(items)
                c.setMinimumWidth(96)
                prefix = {"Pads": f"Pad {i + 1}", "Knobs": f"Knob {i + 1}", "Botões": BUTTONS[i]}[label]
                c.setToolTip(prefix)
                c.activated.connect(lambda idx, kind=label, i=i: self._mapping_changed(kind, i, idx))
                store.append(c)
                g.addWidget(c, row, i + 1)
        side = QVBoxLayout()
        self.learn_btn = QPushButton("Mapear meu controlador…")
        self.learn_btn.setObjectName("power")
        self.learn_btn.setFocusPolicy(Qt.NoFocus)
        self.learn_btn.setToolTip("Assistente: toque cada pad, gire cada knob e aperte cada botão\n"
                                  "quando o AmpSim pedir. Assim ele aprende o que o seu controlador envia.")
        self.learn_btn.clicked.connect(self._learn_clicked)
        side.addWidget(self.learn_btn)
        row = QHBoxLayout()
        self.skip_btn = QPushButton("Pular")
        self.skip_btn.setFocusPolicy(Qt.NoFocus)
        self.skip_btn.clicked.connect(self.inst.skip_learning_step)
        row.addWidget(self.skip_btn)
        self.stop_btn = QPushButton("Parar")
        self.stop_btn.setFocusPolicy(Qt.NoFocus)
        self.stop_btn.clicked.connect(self.inst.stop_learning)
        row.addWidget(self.stop_btn)
        side.addLayout(row)
        self.learn_label = QLabel("")
        self.learn_label.setWordWrap(True)
        self.learn_label.setStyleSheet("color: #ffd166; font-weight: 600;")
        side.addWidget(self.learn_label)
        g.addLayout(side, 0, PAD_COUNT + 1, 3, 1)
        return box

    def _mapping_changed(self, kind, i, idx):
        if kind == "Pads":
            self.inst.pad_notes[i] = self._drum_notes[idx]
        elif kind == "Knobs":
            self.inst.knob_funcs[i] = KNOB_FUNCS[idx]
        else:
            self.inst.button_funcs[i] = BUTTON_FUNCS[idx]
        self.refresh()

    def _learn_clicked(self):
        if self.engine.instruments.learn_steps:
            return
        self.inst.start_learning()

    def on_learn(self):
        steps = self.inst.learn_steps
        self.ctrl.learn_target = steps[0] if steps else None
        self.skip_btn.setVisible(bool(steps))
        self.stop_btn.setVisible(bool(steps))
        self.learn_label.setText(self.inst.learning_prompt() or self._mapping_summary())
        self.ctrl.update()

    def _mapping_summary(self):
        m = self.inst.mapping
        knobs = sum(1 for k in m["knobs"] if k)
        btns = sum(1 for b in m["buttons"] if b)
        pads = ", ".join(str(p[1]) for p in m["pads"][:2])
        return f"Pads: notas {pads}… · knobs mapeados: {knobs}/8 · botões: {btns}/8"

    # ------------------------------------------------------------------ atualização
    def refresh(self):
        inst = self.inst
        k = inst.keys
        self._updating = True
        try:
            items = self.ready_list.findItems(inst.ready, Qt.MatchExactly) if inst.ready else []
            if items:
                self.ready_list.setCurrentItem(items[0])
            else:
                self.ready_list.clearSelection()
            for combo, key in ((self.sound1, "sound1"), (self.sound2, "sound2")):
                i = combo.findData(k[key]) if k[key] else -1
                if i >= 0:
                    combo.setCurrentIndex(i)
            has2 = bool(k["sound2"]) and k["layer2_on"]
            self.layer_on.setChecked(has2)
            for w in (self.sound2, self.mode2, self.split):
                w.setEnabled(has2)
            self.mode2.setCurrentIndex(1 if k["mode2"] == "split" else 0)
            self.split.setVisible(k["mode2"] == "split")
            if k["split"] in SPLIT_NOTES:
                self.split.setCurrentIndex(SPLIT_NOTES.index(k["split"]))
            self.kit.setCurrentText(inst.kit)
            for i, c in enumerate(self.pad_combos):
                note = inst.pad_notes[i]
                if note in self._drum_notes:
                    c.setCurrentIndex(self._drum_notes.index(note))
            for i, c in enumerate(self.knob_combos):
                c.setCurrentText(inst.knob_funcs[i])
            for i, c in enumerate(self.button_combos):
                c.setCurrentText(inst.button_funcs[i])
        finally:
            self._updating = False
        self.sound_status.setText(inst.error or "")
        c = self.ctrl
        c.display = (inst.display_text(), f"Kit: {inst.kit}")
        c.pad_labels = [pad_label(n) for n in inst.pad_notes]
        c.knob_labels = list(inst.knob_funcs)
        c.button_labels = list(inst.button_funcs)
        self.on_learn()
        c.update()
