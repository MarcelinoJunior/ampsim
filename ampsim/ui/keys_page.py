"""Aba Teclas & Pads: controlador na tela, timbres, pads e mapeamento do controlador."""
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QFont, QStandardItemModel
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMenu, QPushButton, QSizePolicy, QSpinBox, QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..instruments import (
    BUTTON_FUNCS, BUTTONS, CATEGORIES, CONT_PAD_SOUNDS, KNOB_COUNT, KNOB_FUNCS, PAD_B_CHOICES,
    PAD_CATEGORIES, PAD_COUNT, PAD_PRESETS, PAD_SOUNDS, READY, READY_GROUPS, SOUNDS, note_name,
)
from .controller import MODELS, TRADEMARKS, ControllerWidget

SPLIT_NOTES = list(range(36, 73))
QUICK = "Atalhos rápidos (qualquer teclado)"


class InstrumentBridge(QObject):
    """Recebe avisos das threads de MIDI/áudio e entrega na thread da interface."""
    pad = Signal(int, int)
    key = Signal(int, bool)
    knob = Signal(int, int)
    changed = Signal()
    learn = Signal()
    monitor = Signal(str, int, int, int)     # atividade MIDI (diálogo de mapeamento)
    control = Signal(str, int)               # função acionada por controle mapeado


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


class PadSoundDialog(QDialog):
    """Escolha do som de um pad: clique toca a prévia, duplo-clique (ou OK) escolhe."""

    def __init__(self, inst, pad_index, parent=None):
        super().__init__(parent)
        self.inst = inst
        self.setWindowTitle(f"Som do Pad {pad_index + 1}")
        self.resize(430, 560)
        lay = QVBoxLayout(self)
        tip = QLabel("Clique para ouvir · duplo-clique ou OK para escolher")
        tip.setObjectName("small")
        lay.addWidget(tip)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar (ex.: bumbo, caixa, 808, chimbal)…")
        self.search.textChanged.connect(self._filter)
        lay.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        current = inst.pad_sounds[pad_index]
        self._items = []
        for cat in PAD_CATEGORIES:
            top = QTreeWidgetItem([cat])
            top.setFlags(Qt.ItemIsEnabled)
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            self.tree.addTopLevelItem(top)
            for s in PAD_SOUNDS:
                if s.cat != cat:
                    continue
                label = s.name + ("   ✦ worship" if s.kind == "synth" else "")
                it = QTreeWidgetItem([label])
                it.setData(0, Qt.UserRole, s.name)
                top.addChild(it)
                self._items.append(it)
                if s.name == current:
                    self.tree.setCurrentItem(it)
            top.setExpanded(cat in ("Bumbos", "Caixas e palmas") or
                            any(s.name == current and s.cat == cat for s in PAD_SOUNDS))
        self.tree.itemClicked.connect(self._preview)
        self.tree.itemDoubleClicked.connect(lambda it, _: self._accept_item(it))
        lay.addWidget(self.tree, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(lambda: self._accept_item(self.tree.currentItem()))
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.choice = None

    def _filter(self, text):
        text = text.lower().strip()
        for it in self._items:
            it.setHidden(bool(text) and text not in it.text(0).lower())
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            visible = any(not top.child(j).isHidden() for j in range(top.childCount()))
            top.setHidden(not visible)
            top.setExpanded(bool(text) or top.isExpanded())

    def _preview(self, it, _col=0):
        name = it.data(0, Qt.UserRole)
        if name:
            self.inst.preview_pad_sound(name)

    def _accept_item(self, it):
        if it is not None and it.data(0, Qt.UserRole):
            self.choice = it.data(0, Qt.UserRole)
            self.accept()

    def done(self, r):
        self.inst.end_preview()
        super().done(r)


class KeysView(QWidget):
    def __init__(self, engine, accent):
        super().__init__()
        self.engine = engine
        self.inst = engine.instruments
        self.bridge = InstrumentBridge()
        self._updating = False
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(6)
        drawn = QWidget()
        left = QVBoxLayout(drawn)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(0)
        self.ctrl = ControllerWidget()
        self.ctrl.set_model(self.inst.device)
        left.addWidget(self.ctrl, 1)
        tm = QLabel(TRADEMARKS)
        tm.setObjectName("small")
        tm.setAlignment(Qt.AlignCenter)
        left.addWidget(tm)
        from .quick_panel import QuickPanel

        self.quick = QuickPanel(engine, self.bridge, accent)
        self.left_stack = QStackedWidget()
        self.left_stack.addWidget(drawn)
        self.left_stack.addWidget(self.quick)
        top.addWidget(self.left_stack, 1)
        top.addWidget(self._build_sounds())
        root.addLayout(top, 1)
        self.mapping_box = self._build_mapping()
        root.addWidget(self.mapping_box)
        self._show_device()

        c = self.ctrl
        c.padPressed.connect(lambda i, v: self.inst.pad_hit(i, v))
        c.keyOn.connect(lambda n, v: self.inst.key_on(n, v))
        c.keyOff.connect(lambda n: self.inst.key_off(n))
        c.knobMoved.connect(lambda i, v: self.inst.set_knob(i, v))
        c.buttonPressed.connect(lambda i: self.inst.button(i))
        c.contextRequested.connect(self._context)

    # ------------------------------------------------------------------ painel de timbres
    def _build_sounds(self):
        box = QFrame()
        box.setObjectName("effect")
        box.setFixedWidth(330)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(10, 6, 10, 8)
        lay.setSpacing(4)
        dev = QHBoxLayout()
        dev.addWidget(QLabel("Instrumento na tela:"))
        self.device = _combo(list(MODELS) + [QUICK])
        self.device.activated.connect(self._device_changed)
        dev.addWidget(self.device, 1)
        lay.addLayout(dev)
        tempo = QHBoxLayout()
        tempo.addWidget(QLabel("BPM da música:"))
        self.bpm = QSpinBox()
        self.bpm.setRange(40, 220)
        self.bpm.setFocusPolicy(Qt.ClickFocus)
        self.bpm.setToolTip("Andamento usado pelo pulso dos timbres sincronizados (ex.: Baixo Pulsante)")
        self.bpm.valueChanged.connect(lambda v: None if self._updating else self.inst.set_bpm(v))
        self.bpm.editingFinished.connect(self.bpm.clearFocus)
        tempo.addWidget(self.bpm)
        tap = QPushButton("Tap")
        tap.setFocusPolicy(Qt.NoFocus)
        tap.setToolTip("Clique no ritmo da música (3-4 vezes): ajusta o BPM e alinha o pulso no tempo.\n"
                       "Também dá para colocar o Tap num botão do controlador.")
        tap.clicked.connect(self.inst.tap_tempo)
        tempo.addWidget(tap)
        tempo.addStretch(1)
        lay.addLayout(tempo)
        t = QLabel("Timbres prontos")
        t.setObjectName("fxtitle")
        lay.addWidget(t)
        self.ready_list = QListWidget()
        self.ready_list.setFocusPolicy(Qt.NoFocus)
        f = QFont(self.ready_list.font())
        f.setPointSizeF(9.5)
        self.ready_list.setFont(f)
        for group, items in READY_GROUPS:
            head = QListWidgetItem(group.upper())
            head.setFlags(Qt.NoItemFlags)
            hf = QFont(f)
            hf.setBold(True)
            hf.setPointSizeF(8)
            head.setFont(hf)
            self.ready_list.addItem(head)
            for name in items:
                it = QListWidgetItem("   " + name)
                it.setData(Qt.UserRole, name)
                self.ready_list.addItem(it)
        self.ready_list.itemClicked.connect(self._ready_clicked)
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
        g.addWidget(QLabel("Pads (A):"), 3, 0)
        self.pad_preset = _combo(list(PAD_PRESETS) + ["(personalizado)"])
        self.pad_preset.setToolTip("Conjunto de sons dos 8 pads do banco A")
        self.pad_preset.activated.connect(self._pad_preset_changed)
        g.addWidget(self.pad_preset, 3, 1, 1, 2)
        g.addWidget(QLabel("Pad contínuo:"), 4, 0)
        self.cont_sound = _combo(CONT_PAD_SOUNDS)
        self.cont_sound.setToolTip("Timbre dos pads do banco B (pad contínuo no tom escolhido)")
        self.cont_sound.activated.connect(lambda _: self.inst.set_cont_sound(self.cont_sound.currentText()))
        g.addWidget(self.cont_sound, 4, 1, 1, 2)
        g.setColumnStretch(1, 1)
        lay.addLayout(g)
        self.sound_status = QLabel("")
        self.sound_status.setObjectName("small")
        self.sound_status.setWordWrap(True)
        lay.addWidget(self.sound_status)
        return box

    def _device_changed(self, _):
        self.inst.device = self.device.currentText()
        self._show_device()

    def _show_device(self):
        quick = self.inst.device == QUICK
        self.left_stack.setCurrentIndex(1 if quick else 0)
        self.mapping_box.setVisible(not quick)
        if not quick:
            self.ctrl.set_model(self.inst.device)
        else:
            self.quick.refresh()

    def _ready_clicked(self, it):
        name = it.data(Qt.UserRole)
        if name:
            self.inst.set_ready(name)

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

    def _pad_preset_changed(self, i):
        names = list(PAD_PRESETS)
        if i < len(names):
            self.inst.set_pad_preset(names[i])

    # ------------------------------------------------------------------ mapeamento
    def _build_mapping(self):
        box = QFrame()
        box.setObjectName("effect")
        box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        g = QGridLayout(box)
        g.setContentsMargins(10, 5, 10, 5)
        g.setHorizontalSpacing(4)
        g.setVerticalSpacing(2)
        self.pad_buttons, self.padb_combos, self.knob_combos, self.button_combos = [], [], [], []
        rows = (("Pads A", self.pad_buttons), ("Pads B", self.padb_combos),
                ("Knobs", self.knob_combos), ("Botões", self.button_combos))
        for row, (label, store) in enumerate(rows):
            lab = QLabel(label + ":")
            lab.setObjectName("fxtitle")
            g.addWidget(lab, row, 0)
            for i in range(PAD_COUNT if label.startswith("Pads") else
                           (KNOB_COUNT if label == "Knobs" else len(BUTTONS))):
                if label == "Pads A":
                    w = QPushButton("")
                    w.setFocusPolicy(Qt.NoFocus)
                    w.setToolTip(f"Pad {i + 1}: clique para escolher o som")
                    w.clicked.connect(lambda _, i=i: self._choose_pad_sound(i))
                elif label == "Pads B":
                    w = _combo(PAD_B_CHOICES)
                    w.setToolTip(f"Pad {i + 1} do banco B: tom do pad contínuo")
                    w.activated.connect(lambda idx, i=i: self.inst.set_pad_key(i, PAD_B_CHOICES[idx]))
                elif label == "Knobs":
                    w = _combo(KNOB_FUNCS)
                    w.setToolTip(f"Knob {i + 1}")
                    w.activated.connect(lambda idx, i=i: self._set_knob_func(i, KNOB_FUNCS[idx]))
                else:
                    w = _combo(BUTTON_FUNCS)
                    w.setToolTip(BUTTONS[i])
                    w.activated.connect(lambda idx, i=i: self._set_button_func(i, BUTTON_FUNCS[idx]))
                w.setMinimumWidth(96)
                store.append(w)
                g.addWidget(w, row, i + 1)
        side = QVBoxLayout()
        side.setSpacing(2)
        self.learn_btn = QPushButton("Mapear meu controlador…")
        self.learn_btn.setObjectName("power")
        self.learn_btn.setFocusPolicy(Qt.NoFocus)
        self.learn_btn.setToolTip("Assistente: toque cada pad (bancos A e B), gire cada knob e aperte\n"
                                  "cada botão quando o AmpSim pedir. Assim ele aprende o seu controlador.")
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
        g.addLayout(side, 0, PAD_COUNT + 1, 4, 1)
        return box

    def _set_knob_func(self, i, func):
        self.inst.knob_funcs[i] = func
        self.refresh()

    def _set_button_func(self, i, func):
        self.inst.button_funcs[i] = func
        self.refresh()

    def _choose_pad_sound(self, i):
        dlg = PadSoundDialog(self.inst, i, self)
        if dlg.exec() and dlg.choice:
            self.inst.set_pad_sound(i, dlg.choice)
        self.refresh()

    # ------------------------------------------------------------------ botão direito no controlador
    def _context(self, kind, i, pos):
        menu = QMenu(self)
        if kind == "pad" and i < PAD_COUNT:
            self._choose_pad_sound(i)
            return
        if kind == "pad":
            j = i - PAD_COUNT
            menu.addSection(f"Pad {j + 1} (banco B): tom do pad contínuo")
            for key in PAD_B_CHOICES:
                a = menu.addAction(key)
                a.setCheckable(True)
                a.setChecked(self.inst.pad_keys[j] == key)
                a.triggered.connect(lambda _, key=key: self.inst.set_pad_key(j, key))
            menu.addSeparator()
            sub = menu.addMenu("Timbre do pad contínuo")
            for name in CONT_PAD_SOUNDS:
                a = sub.addAction(name)
                a.setCheckable(True)
                a.setChecked(self.inst.cont_sound == name)
                a.triggered.connect(lambda _, n=name: self.inst.set_cont_sound(n))
        elif kind == "knob":
            menu.addSection(f"Knob {i + 1}: função")
            for func in KNOB_FUNCS:
                a = menu.addAction(func)
                a.setCheckable(True)
                a.setChecked(self.inst.knob_funcs[i] == func)
                a.triggered.connect(lambda _, f=func: self._set_knob_func(i, f))
        elif kind == "button":
            menu.addSection(f"Botão {BUTTONS[i]}: função")
            for func in BUTTON_FUNCS:
                a = menu.addAction(func)
                a.setCheckable(True)
                a.setChecked(self.inst.button_funcs[i] == func)
                a.triggered.connect(lambda _, f=func: self._set_button_func(i, f))
        elif kind == "key":
            menu.addSection("Timbre das teclas")
            for group, items in READY_GROUPS:
                sub = menu.addMenu(group)
                for name in items:
                    a = sub.addAction(name)
                    a.triggered.connect(lambda _, n=name: self.inst.set_ready(n))
            menu.addSeparator()
            for cat in CATEGORIES:
                sub = menu.addMenu(cat)
                for s in SOUNDS:
                    if s.cat == cat:
                        a = sub.addAction(s.name)
                        a.triggered.connect(lambda _, n=s.name: self.inst.set_sound(1, n))
        menu.exec(pos)
        self.refresh()

    def _learn_clicked(self):
        if not self.inst.learn_steps:
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
        return (f"Pads A: notas {m['pads'][0][1]}… · B: {m['pads_b'][0][1]}… · "
                f"knobs {knobs}/8 · botões {btns}/8")

    # ------------------------------------------------------------------ atualização
    def refresh(self):
        inst = self.inst
        k = inst.keys
        self._updating = True
        try:
            self.ready_list.clearSelection()
            for row in range(self.ready_list.count()):
                it = self.ready_list.item(row)
                if inst.ready and it.data(Qt.UserRole) == inst.ready:
                    self.ready_list.setCurrentItem(it)
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
            self.pad_preset.setCurrentText(inst.pad_preset or "(personalizado)")
            self.device.setCurrentText(inst.device)
            self.bpm.setValue(inst.bpm)
            self.cont_sound.setCurrentText(inst.cont_sound)
            for i, b in enumerate(self.pad_buttons):
                b.setText(_short(inst.pad_sounds[i], 16))
                b.setToolTip(f"Pad {i + 1}: {inst.pad_sounds[i]}\nClique para trocar o som")
            for i, c in enumerate(self.padb_combos):
                c.setCurrentText(inst.pad_keys[i])
            for i, c in enumerate(self.knob_combos):
                c.setCurrentText(inst.knob_funcs[i])
            for i, c in enumerate(self.button_combos):
                c.setCurrentText(inst.button_funcs[i])
        finally:
            self._updating = False
        self.sound_status.setText(inst.error or "Botão direito no controlador: escolher sons e funções.")
        c = self.ctrl
        c.display = (inst.display_text(), inst.display_line2())
        names = list(READY)
        c.ready_index = names.index(inst.ready) + 1 if inst.ready in names else 0
        c.pad_labels = list(inst.pad_sounds)
        c.pad_keys_b = list(inst.pad_keys)
        c.bank = inst.screen_bank
        c.cont_key = inst.cont_key
        c.knob_labels = list(inst.knob_funcs)
        c.button_labels = list(inst.button_funcs)
        self.on_learn()
        quick = self.inst.device == QUICK
        if (self.left_stack.currentIndex() == 1) != quick or (not quick and c.model_name != self.inst.device):
            self._show_device()                 # instrumento salvo na sessão: atualiza o desenho
        c.update()
        if quick:
            self.quick.refresh()


def _short(text, n):
    return text if len(text) <= n else text[: n - 1] + "…"
