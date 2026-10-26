"""Aba Pad/Piano: cabeçalho do timbre, pads contínuos, knobs grandes, teclado e o painel
"Instrumento / Layer" à direita. Também abriga o Synth AmpSim e o amp/efeitos das teclas.
"""
from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QIntValidator, QStandardItemModel
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu,
    QPushButton, QScrollArea, QSizePolicy, QSlider, QStackedWidget, QToolButton, QTreeWidget,
    QMessageBox, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..instruments import (
    BUTTON_FUNCS, BUTTONS, CATEGORIES, CONT_PAD_SOUNDS, DELAY_DIVS, KEY_NAMES, KNOB_FUNCS, PAD_B_CHOICES,
    PAD_CATEGORIES,
    PAD_COUNT, PAD_SOUNDS, READY, READY_GROUPS, SOUND_BY_NAME, SOUNDS, note_name,
)
from ..dsp.keysfx import ROT_MULTS, rotation_hz
from ..instruments import DEFAULT_FX, LAYER_ZONES, MAX_LAYERS, PITCH_FUNCS
from .controller import MODELS, TRADEMARKS, ControllerWidget
from .funcs import func_param, func_value, set_func
from .icons import icon
from .midi_learn import Mapped, MidiLearnDialog, key_text
from .theme import ACCENT, C
from .widgets import ArtTile, Knob, PianoWidget, ToggleSwitch

SPLIT_NOTES = list(range(36, 73))
CONT_SHORT = {"Cordas Lentas": "Cordas", "Pad Orquestra": "Orquestra", "Coral": "Coral"}
FLATS = {"C#": "Db", "D#": "Eb", "F#": "Gb", "G#": "Ab", "A#": "Bb"}
SIMPLE = "Teclado simples"
QUICK = "Atalhos rápidos (qualquer teclado)"        # nome antigo, tratado como teclado simples
DEVICES = [SIMPLE] + list(MODELS)
KEY_MODES = ("Um timbre", "Dois juntos (camadas)", "Dividido (esq. | dir.)")
BIG_KNOBS = ("Volume teclas", "Reverb", "Chorus", "Shimmer", "Brilho", "Ataque", "Release", "Master")


def key_mode(k):
    """"single" (um timbre), "layer" (dois juntos) ou "split" (mão esquerda | mão direita)."""
    if not (k["sound2"] and k["layer2_on"]):
        return "single"
    return "split" if k["mode2"] == "split" else "layer"


def is_simple(device):
    return device not in MODELS


class InstrumentBridge(QObject):
    """Recebe avisos das threads de MIDI/áudio e entrega na thread da interface."""
    pad = Signal(int, int)
    key = Signal(int, bool)
    knob = Signal(int, int)
    changed = Signal()
    learn = Signal()
    monitor = Signal(str, int, int, int)     # atividade MIDI (diálogo de mapeamento)
    control = Signal(str, int)               # função acionada por controle mapeado
    unmapped = Signal(int, int)              # canal, CC de um knob ainda não mapeado


def _combo(items=(), width=None):
    c = QComboBox()
    c.setFocusPolicy(Qt.NoFocus)
    c.addItems(list(items))
    if width:
        c.setFixedWidth(width)
    return c


def sound_combo():
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


def _label(text, name=None):
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    return lab


def _short(text, n):
    return text if len(text) <= n else text[: n - 1] + "…"


class BpmBox(QLineEdit):
    """Campo do BPM: digita (40-220) ou gira a roda do mouse. (QSpinBox sem setas some com o
    estilo do app: o Qt deixa o texto com 1 px de largura.)"""

    changed = Signal(int)
    LO, HI = 40, 220

    def __init__(self):
        super().__init__()
        self.setValidator(QIntValidator(1, 999, self))
        self.setAlignment(Qt.AlignCenter)
        self.setFixedSize(58, 30)
        self.setStyleSheet("QLineEdit { padding: 2px 2px; font-weight: 600; }")
        self.setFocusPolicy(Qt.ClickFocus)
        self.editingFinished.connect(self._commit)
        self._value = 100
        self.setText("100")

    def value(self):
        return self._value

    def set_value(self, v):
        self._value = int(v)
        if not self.hasFocus():
            self.setText(str(self._value))

    def _commit(self):
        try:
            v = int(self.text())
        except ValueError:
            v = self._value
        v = max(self.LO, min(self.HI, v))
        self.setText(str(v))
        self.clearFocus()
        if v != self._value:
            self._value = v
            self.changed.emit(v)

    def wheelEvent(self, e):
        step = 1 if e.angleDelta().y() > 0 else -1
        v = max(self.LO, min(self.HI, self._value + step))
        if v != self._value:
            self._value = v
            self.setText(str(v))
            self.changed.emit(v)


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
        from ..audio.sampler import REC_PREFIX, list_recordings
        recs = list_recordings()
        if recs:                                   # gravações do banco (aba Faders / Pads)
            top = QTreeWidgetItem(["Gravações"])
            top.setFlags(Qt.ItemIsEnabled)
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            self.tree.addTopLevelItem(top)
            for name in recs:
                it = QTreeWidgetItem(["● " + name])
                it.setData(0, Qt.UserRole, REC_PREFIX + name)
                top.addChild(it)
                self._items.append(it)
                if REC_PREFIX + name == current:
                    self.tree.setCurrentItem(it)
            top.setExpanded(True)
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
                it = QTreeWidgetItem([s.name + ("   ✦ worship" if s.kind == "synth" else "")])
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


class PadPianoView(QWidget):
    def __init__(self, win, amp_page, synth_panel):
        super().__init__()
        self.win = win
        self.engine = win.engine
        self.inst = win.engine.instruments
        self.bridge = InstrumentBridge()
        self.amp_page = amp_page
        self.synth_panel = synth_panel
        self.layer = 1                       # camada editada no painel da direita
        self.user_preset = ""                # nome do preset "meu" carregado (se houver)
        self._updating = False
        self.mapped = {}                     # função -> controle da tela mapeável no MIDI
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        self.view_buttons = []
        self.views = QStackedWidget()
        play = QWidget()
        pl = QHBoxLayout(play)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(10)
        pl.addWidget(self._build_center(), 1)
        pl.addWidget(self._build_side())
        self.views.addWidget(play)
        for inner in (synth_panel, amp_page):
            page = QWidget()
            vl = QVBoxLayout(page)
            vl.setContentsMargins(0, 0, 0, 0)
            vl.setSpacing(8)
            row = self._view_switch()
            row.addStretch(1)
            vl.addLayout(row)
            if inner is synth_panel:
                sc = QScrollArea()
                sc.setWidgetResizable(True)
                sc.setWidget(synth_panel)
                inner = sc
            vl.addWidget(inner, 1)
            self.views.addWidget(page)
        root.addWidget(self.views, 1)
        self.show_view(0)

        c = self.ctrl
        c.padPressed.connect(lambda i, v: self.inst.pad_hit(i, v))
        c.keyOn.connect(lambda n, v: self.inst.key_on(n, v))
        c.keyOff.connect(lambda n: self.inst.key_off(n))
        c.knobMoved.connect(lambda i, v: self.inst.set_knob(i, v))
        c.buttonPressed.connect(lambda i: self.inst.button(i))
        c.contextRequested.connect(self._context)
        self.bridge.control.connect(lambda *_: self.refresh_values())

    def _view_switch(self):
        """Tocar · Synth AmpSim · Amp e efeitos das teclas (um conjunto de botões por visão)."""
        row = QHBoxLayout()
        row.setSpacing(4)
        for i, (text, ic, tip) in enumerate((
                ("Tocar", "keys", "Teclado, timbres e pads"),
                ("Synth", "music", "Synth AmpSim (pads e baixo pulsante)"),
                ("Amp e efeitos", "eq", "Amplificador e efeitos da trilha das teclas"))):
            b = QPushButton(" " + text)
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.setToolTip(tip)
            b.setIcon(icon(ic, C["dim"], 14, active="#ffffff"))
            b.clicked.connect(lambda _, i=i: self.show_view(i))
            self.view_buttons.append((i, b))
            row.addWidget(b)
        return row

    # ------------------------------------------------------------------ centro
    def _build_center(self):
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(self._build_header(), 1)
        top.addWidget(self._build_cont_grid())
        lay.addLayout(top)

        self.knob_card = QFrame()
        self.knob_card.setObjectName("card")
        kl = QHBoxLayout(self.knob_card)
        kl.setContentsMargins(10, 4, 10, 0)
        kl.setSpacing(0)
        self.big_knobs = {}
        for func in BIG_KNOBS:
            k = Knob(func_param(func), ACCENT, size="big")
            k.valueChanged.connect(lambda v, f=func: self._knob(f, v))
            w = Mapped(self, func, k)
            self.big_knobs[func] = k
            self.mapped[func] = w
            kl.addWidget(w, 1)
        lay.addWidget(self.knob_card)

        kb = QFrame()
        kb.setObjectName("card")
        kbl = QVBoxLayout(kb)
        kbl.setContentsMargins(10, 6, 10, 8)
        kbl.setSpacing(4)
        head = QHBoxLayout()
        head.addLayout(self._view_switch())
        head.addSpacing(8)
        self.kbd_info = _label("", "small")
        head.addWidget(self.kbd_info, 1)
        head.addWidget(_label("Na tela:", "small"))
        self.device = _combo(DEVICES, 190)
        self.device.setToolTip("Teclado simples (como no seu teclado) ou o desenho de um controlador")
        self.device.activated.connect(lambda _: self.set_device(self.device.currentText()))
        head.addWidget(self.device)
        kbl.addLayout(head)
        self.kbd_stack = QStackedWidget()
        self.piano = PianoWidget(36, 96)
        self.piano.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.piano.setMinimumHeight(96)
        self.piano.noteOn.connect(lambda n, v: self.inst.key_on(n, v))
        self.piano.noteOff.connect(lambda n: self.inst.key_off(n))
        self.piano.setContextMenuPolicy(Qt.CustomContextMenu)
        self.piano.customContextMenuRequested.connect(self._piano_menu)
        self.kbd_stack.addWidget(self.piano)
        drawn = QWidget()
        dl = QVBoxLayout(drawn)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(0)
        self.ctrl = ControllerWidget()
        self.ctrl.setMinimumSize(300, 96)
        dl.addWidget(self.ctrl, 1)
        tm = _label("Desenhos em homenagem aos instrumentos originais; marcas e logotipos são dos seus titulares.",
                    "small")
        tm.setToolTip(TRADEMARKS)
        tm.setAlignment(Qt.AlignCenter)
        dl.addWidget(tm)
        self.kbd_stack.addWidget(drawn)
        kbl.addWidget(self.kbd_stack, 1)
        lay.addWidget(kb, 1)
        return box

    def _build_header(self):
        card = QFrame()
        card.setObjectName("card")
        g = QGridLayout(card)
        g.setContentsMargins(12, 8, 12, 8)
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(6)
        self.art = ArtTile(84)
        g.addWidget(self.art, 0, 0, 2, 1, Qt.AlignTop)
        names = QVBoxLayout()
        names.setSpacing(2)
        self.title = _label("", "h1")
        self.subtitle = _label("", "small")
        self.subtitle.setStyleSheet(f"color: {C['dim']}; font-size: 10.5pt;")
        names.addWidget(self.title)
        names.addWidget(self.subtitle)
        names.addStretch(1)
        g.addLayout(names, 0, 1)

        acts = QHBoxLayout()
        acts.setSpacing(6)
        bpm_box = QVBoxLayout()
        bpm_box.setSpacing(0)
        bpm_box.addWidget(_label("BPM", "small"), 0, Qt.AlignHCenter)
        self.bpm = BpmBox()
        self.bpm.setToolTip("Andamento da música (pulso do Baixo Pulsante e delay no tempo).\n"
                            "Digite, use a roda do mouse ou clique TAP no ritmo.")
        self.bpm.changed.connect(lambda v: None if self._updating else self.inst.set_bpm(v))
        bpm_box.addWidget(self.bpm)
        acts.addLayout(bpm_box)
        self.action_buttons = {}
        for func, text, ic, tip in (
                ("Tap tempo (BPM)", "TAP", "tap", "Clique no ritmo (3-4 vezes) para acertar o BPM"),
                ("Sustain (segurar)", "SUST.", "music", "Sustain: segura as notas soltas (como o pedal)"),
                ("Oitava −", "OIT −", "down", "Uma oitava abaixo"),
                ("Oitava +", "OIT +", "up", "Uma oitava acima"),
                ("Pânico (soltar notas)", "PARAR", "stop", "Solta todas as notas e para o pad contínuo")):
            b = QToolButton()
            b.setText(text)
            b.setObjectName("action")
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setIcon(icon(ic, C["text"], 16, active="#ffffff"))
            b.setIconSize(QSize(16, 16))
            b.setFocusPolicy(Qt.NoFocus)
            b.setToolTip(tip + "\nBotão direito: mapear num botão do controlador")
            b.setFixedSize(60, 50)
            b.setCheckable(func == "Sustain (segurar)")
            b.clicked.connect(lambda _, f=func: self._action(f))
            w = Mapped(self, func, b)
            w.tag.setVisible(False)
            self.action_buttons[func] = b
            self.mapped[func] = w
            acts.addWidget(w)
        acts.addStretch(1)
        g.addLayout(acts, 1, 1)

        layers = QHBoxLayout()
        layers.setSpacing(8)
        self.layer_buttons = []
        for i in range(1, MAX_LAYERS + 1):
            b = QPushButton()
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.setMinimumHeight(44)
            b.setMinimumWidth(78)
            b.setIcon(icon("keys", C["text"], 22))
            b.setIconSize(QSize(22, 22))
            b.setStyleSheet("QPushButton { text-align: left; padding: 6px 12px; }")
            b.clicked.connect(lambda _, i=i: self.select_layer(i))
            self.layer_buttons.append(b)
            layers.addWidget(b, 1)
        self.mode = _combo(KEY_MODES)
        self.mode.setToolTip("Um timbre · dois juntos · teclado dividido (mão esquerda | mão direita).\n"
                             "Dica: botão direito numa tecla também divide o teclado ali.")
        self.mode.activated.connect(lambda i: self.set_key_mode(("single", "layer", "split")[i]))
        mcol = QVBoxLayout()
        mcol.setSpacing(4)
        mcol.addWidget(self.mode)
        self.split = _combo([f"divisão em {note_name(n)}" for n in SPLIT_NOTES])
        self.split.setToolTip("A mão direita começa nesta nota")
        self.split.activated.connect(lambda i: self.set_key_mode("split", SPLIT_NOTES[i]))
        mcol.addWidget(self.split)
        layers.addLayout(mcol)
        g.addLayout(layers, 2, 0, 1, 2)
        g.setColumnStretch(1, 1)
        return card

    def _build_cont_grid(self):
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 6, 10, 8)
        lay.setSpacing(5)
        head = QHBoxLayout()
        self.cont_title = _label("Pad contínuo", "section")
        head.addWidget(self.cont_title, 1)
        eq = QPushButton()
        eq.setIcon(icon("eq", C["text"], 15))
        eq.setFixedSize(30, 26)
        eq.setToolTip("EQ e ambiente do pad contínuo")
        eq.setFocusPolicy(Qt.NoFocus)
        eq.clicked.connect(self.open_pad_eq)
        head.addWidget(eq)
        self.stop_btn = QPushButton(" Parar")
        self.stop_btn.setIcon(icon("stop", "#ffffff", 13))
        self.stop_btn.setFocusPolicy(Qt.NoFocus)
        self.stop_btn.setFixedHeight(26)
        self.stop_btn.setToolTip("Para o pad contínuo (com fade)")
        self.stop_btn.setStyleSheet("QPushButton { background: #c62a3a; border: 1px solid #ff5466; color: white;"
                                    " font-weight: 700; border-radius: 7px; padding: 2px 10px; }"
                                    "QPushButton:hover { background: #dd3446; }")
        self.stop_btn.clicked.connect(lambda *_: self.inst.stop_cont_pad())
        head.insertWidget(1, self.stop_btn)
        lay.addLayout(head)
        # os 12 tons como um teclado: naturais embaixo, sustenidos/bemóis em cima, entre eles
        grid = QGridLayout()
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(5)
        self.cont_buttons = {}
        for k, key in enumerate(KEY_NAMES):
            sharp = "#" in key
            if sharp:
                flat = FLATS[key]
                b = QPushButton(f"{key}\n{flat}")
                b.setFixedSize(44, 34)
            else:
                b = QPushButton(key)
                b.setFixedSize(44, 44)
            b.setFocusPolicy(Qt.NoFocus)
            b.setProperty("sharp", sharp)
            b.setToolTip(f"Pad contínuo em {key}" + (f" / {FLATS[key]}" if sharp else "") +
                         "\nClique de novo para parar · botão direito: timbre e EQ")
            b.pressed.connect(lambda key=key: self._cont_key(key))
            b.setContextMenuPolicy(Qt.CustomContextMenu)
            b.customContextMenuRequested.connect(lambda *_: self._cont_menu())
            self.cont_buttons[key] = b
            natural_index = sum(1 for x in KEY_NAMES[:k] if "#" not in x)
            if sharp:                          # fica entre a natural anterior e a seguinte
                grid.addWidget(b, 0, 2 * natural_index - 1, 1, 2, Qt.AlignHCenter)
            else:
                grid.addWidget(b, 1, 2 * natural_index, 1, 2, Qt.AlignHCenter)
        lay.addLayout(grid)
        # timbre do pad contínuo: um botão por timbre (o mesmo das telas Pads e do botão direito)
        sounds = QGridLayout()
        sounds.setHorizontalSpacing(4)
        sounds.setVerticalSpacing(4)
        self.cont_sound_buttons = {}
        for i, name in enumerate(CONT_PAD_SOUNDS):
            b = QPushButton(CONT_SHORT.get(name, name.replace("Pad ", "")))
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.setFixedHeight(22)
            b.setToolTip(f"Timbre do pad contínuo: {name}")
            b.clicked.connect(lambda *_, n=name: self._cont_sound(n))
            self.cont_sound_buttons[name] = b
            sounds.addWidget(b, i // 5, i % 5)
        lay.addLayout(sounds)
        return card

    def _cont_sound(self, name):
        self.inst.set_cont_sound(name)          # se um tom está tocando, troca com fade
        self.win.refresh_sounds()

    def _cont_key(self, key):
        if key == self.inst.cont_key:
            self.inst.stop_cont_pad()
        else:
            self.inst.start_cont_pad(key)
        self.inst.on_change()

    # ------------------------------------------------------------------ painel direito
    def _build_side(self):
        side = QFrame()
        side.setObjectName("side")
        side.setFixedWidth(280)
        outer = QVBoxLayout(side)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        head = QHBoxLayout()
        hi = QLabel()
        hi.setPixmap(icon("keys", C["text"], 18).pixmap(18, 18))
        head.addWidget(hi)
        head.addWidget(_label("Instrumento / Layer", "h2"), 1)
        lay.addLayout(head)

        seg = QHBoxLayout()
        seg.setSpacing(3)
        self.side_layer_buttons = []
        for i in range(1, MAX_LAYERS + 1):
            b = QPushButton(f"L{i}")
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.setToolTip(f"Layer {i}")
            b.clicked.connect(lambda _, i=i: self.select_layer(i))
            self.side_layer_buttons.append(b)
            seg.addWidget(b, 1)
        self.add_layer_btn = QPushButton()
        self.add_layer_btn.setIcon(icon("add", C["text"], 14))
        self.add_layer_btn.setFixedSize(30, 28)
        self.add_layer_btn.setFocusPolicy(Qt.NoFocus)
        self.add_layer_btn.setToolTip("Adicionar camada (até 4)")
        self.add_layer_btn.clicked.connect(lambda *_: self.add_layer())
        seg.addWidget(self.add_layer_btn)
        lay.addLayout(seg)

        card = QFrame()
        card.setObjectName("card")
        cl = QGridLayout(card)
        cl.setContentsMargins(8, 8, 8, 8)
        cl.setHorizontalSpacing(8)
        cl.setVerticalSpacing(4)
        self.layer_art = ArtTile(44)
        cl.addWidget(self.layer_art, 0, 0, 2, 1)
        self.layer_name = _label("", "section")
        self.layer_sub = _label("", "small")
        cl.addWidget(self.layer_name, 0, 1)
        cl.addWidget(self.layer_sub, 1, 1)
        self.layer_on = ToggleSwitch()
        self.layer_on.setToolTip("Liga/desliga esta camada")
        self.layer_on.clicked.connect(lambda *_: self._layer_switch(self.layer_on.isChecked()))
        cl.addWidget(self.layer_on, 0, 2)
        self.remove_layer_btn = QPushButton()
        self.remove_layer_btn.setIcon(icon("delete", C["text"], 13))
        self.remove_layer_btn.setFixedSize(26, 24)
        self.remove_layer_btn.setFocusPolicy(Qt.NoFocus)
        self.remove_layer_btn.setToolTip("Remover esta camada")
        self.remove_layer_btn.clicked.connect(lambda *_: self.remove_layer())
        cl.addWidget(self.remove_layer_btn, 1, 2)
        self.layer_sound = sound_combo()
        self.layer_sound.activated.connect(self._layer_sound)
        cl.addWidget(self.layer_sound, 2, 0, 1, 3)
        cl.setColumnStretch(1, 1)
        lay.addWidget(card)

        row = QHBoxLayout()
        row.addWidget(_label("Volume"))
        self.layer_vol = QSlider(Qt.Horizontal)
        self.layer_vol.setRange(0, 127)
        self.layer_vol.setFocusPolicy(Qt.NoFocus)
        self.layer_vol.valueChanged.connect(self._layer_volume)
        row.addWidget(self.layer_vol, 1)
        self.layer_vol_lab = _label("", "small")
        self.layer_vol_lab.setFixedWidth(40)
        row.addWidget(self.layer_vol_lab)
        lay.addLayout(row)
        row = QHBoxLayout()
        self.oct_label = _label("Oitava")
        row.addWidget(self.oct_label)
        self.layer_oct = _combo(("−2", "−1", "0", "+1", "+2"), 52)
        self.layer_oct.activated.connect(self._layer_octave)
        row.addWidget(self.layer_oct)
        row.addStretch(1)
        self.zone_label = _label("Zona")
        row.addWidget(self.zone_label)
        self.layer_zone = _combo(("Teclado todo", "Mão esquerda", "Mão direita"), 112)
        self.layer_zone.setToolTip("Onde esta camada toca (a divisão é a mesma do modo Dividido)")
        self.layer_zone.activated.connect(lambda i: self._layer_zone(LAYER_ZONES[i]))
        row.addWidget(self.layer_zone)
        lay.addLayout(row)

        self.fx_title = _label("Efeitos da Layer 1", "section")
        lay.addWidget(self.fx_title)
        fx = QGridLayout()
        fx.setHorizontalSpacing(8)
        fx.setVerticalSpacing(5)
        self.fx_switch = {}
        for r, (func, text) in ((0, ("Rotação liga/desliga", "Rotação")), (2, ("Drive liga/desliga", "Drive")),
                                (3, ("Delay liga/desliga", "Delay"))):
            sw = ToggleSwitch()
            sw.clicked.connect(lambda _, f=func: self._action(f))
            w = Mapped(self, func, sw)
            w.tag.setVisible(False)
            self.fx_switch[func] = sw
            self.mapped[func] = w
            fx.addWidget(w, r, 0)
            fx.addWidget(QLabel(text), r, 1)
        self.rot_speed = _combo(("Lenta", "Rápida"))
        self.rot_speed.setToolTip("Lenta/Rápida como num Leslie (acelera e freia aos poucos)")
        self.rot_speed.activated.connect(self._rot_speed)
        fx.addWidget(self.rot_speed, 0, 2)
        fx.addWidget(_label("Veloc.", "small"), 1, 1)
        vrow = QHBoxLayout()
        vrow.setSpacing(4)
        self.rot_rate = QSlider(Qt.Horizontal)
        self.rot_rate.setFocusPolicy(Qt.NoFocus)
        self.rot_rate.setToolTip("Velocidade do modo escolhido (Lenta ou Rápida).\n"
                                 "Com BPM marcado: voltas por tempo da música.")
        self.rot_rate.valueChanged.connect(self._rot_rate)
        vrow.addWidget(self.rot_rate, 1)
        self.rot_rate_lab = _label("", "small")
        self.rot_rate_lab.setFixedWidth(46)
        vrow.addWidget(self.rot_rate_lab)
        self.rot_sync = QCheckBox("BPM")
        self.rot_sync.setFocusPolicy(Qt.NoFocus)
        self.rot_sync.setToolTip("A rotação acompanha o BPM da música")
        self.rot_sync.clicked.connect(lambda *_: self._rot_sync(self.rot_sync.isChecked()))
        vrow.addWidget(self.rot_sync)
        fx.addLayout(vrow, 1, 2)
        self.drive = QSlider(Qt.Horizontal)
        self.drive.setRange(0, 100)
        self.drive.setFocusPolicy(Qt.NoFocus)
        self.drive.valueChanged.connect(lambda v: None if self._updating else (
            set_func(self.engine, "Drive", v), self.refresh_values()))
        fx.addWidget(self.drive, 2, 2)
        self.delay_div = _combo(DELAY_DIVS)
        self.delay_div.activated.connect(self._delay_div)
        fx.addWidget(self.delay_div, 3, 2)
        fx.addWidget(QLabel("Toque"), 4, 1)
        self.touch = QSlider(Qt.Horizontal)
        self.touch.setRange(0, 100)
        self.touch.setFocusPolicy(Qt.NoFocus)
        self.touch.setToolTip("Sensibilidade ao toque (todas as camadas): 0 = notas iguais, 100 = segue a força")
        self.touch.valueChanged.connect(lambda v: None if self._updating else
                                        set_func(self.engine, "Sensibilidade ao toque", v))
        fx.addWidget(self.touch, 4, 2)
        fx.setColumnStretch(2, 1)
        lay.addLayout(fx)
        lay.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll)
        return side

    # ------------------------------------------------------------------ ações
    def show_view(self, i):
        self.views.setCurrentIndex(i)
        for j, b in self.view_buttons:
            b.setChecked(j == i)
        if i == 1:
            self.synth_panel.refresh()
        elif i == 2:
            self.amp_page.refresh()

    def select_layer(self, i):
        """Escolhe a camada editada no painel (e a dos efeitos/controles MIDI)."""
        if i == 2 and key_mode(self.inst.keys) == "single":
            self.layer = 2
            self.inst.fx_layer = 1
            self.set_key_mode("layer")
            return
        self.layer = max(1, min(i, self.inst.layer_count()))
        self.inst.fx_layer = self.layer - 1
        self.refresh()

    def add_layer(self):
        n = self.inst.add_layer()
        if n:
            self.user_preset = ""
            self.select_layer(n)

    def remove_layer(self):
        if self.layer >= 3:
            self.inst.remove_layer(self.layer)
            self.user_preset = ""
            self.select_layer(min(self.layer, self.inst.layer_count()))

    def set_device(self, name):
        self.inst.device = name
        self.win.refresh_sounds()               # também a barra de baixo (Configurações)

    def _knob(self, func, v):
        if self._updating:
            return
        if func == "Master":
            self.win.set_master_pct(v)
        else:
            set_func(self.engine, func, v)

    def _action(self, func):
        self.inst.do_button(func)
        self.refresh()

    def _rot_speed(self, i):
        fx = self.inst.fx
        fx["rot_fast"] = i == 1
        fx["rot_on"] = True
        self.inst.apply_fx()
        self.refresh()

    # velocidade livre: 0,3 a 10 Hz em escala log; no BPM: índice em ROT_MULTS
    def _rot_key(self):
        fx = self.inst.fx
        fast = fx["rot_fast"]
        if fx["rot_sync"]:
            return "rot_fast_mult" if fast else "rot_slow_mult"
        return "rot_fast_hz" if fast else "rot_slow_hz"

    def _rot_rate(self, v):
        if self._updating:
            return
        fx = self.inst.fx
        key = self._rot_key()
        fx[key] = ROT_MULTS[v] if fx["rot_sync"] else round(0.3 * (10 / 0.3) ** (v / 100), 2)
        self.inst.apply_fx()
        self._rot_rate_text()

    def _rot_sync(self, on):
        self.inst.fx["rot_sync"] = bool(on)
        self.inst.apply_fx()
        self.refresh_values()

    def _rot_rate_text(self):
        fx = self.inst.fx
        hz = rotation_hz(fx, self.inst.bpm)
        if fx["rot_sync"]:
            m = fx[self._rot_key()]
            self.rot_rate_lab.setText(f"{m:g}×")
            self.rot_rate_lab.setToolTip(f"{m:g} volta(s) por tempo = {hz:.2f} Hz a {self.inst.bpm} BPM")
        else:
            self.rot_rate_lab.setText(f"{hz:.1f} Hz")
            self.rot_rate_lab.setToolTip("")

    def _delay_div(self, i):
        self.inst.fx["delay_div"] = i
        self.inst.fx["delay_on"] = True
        self.inst.apply_fx()
        self.refresh()

    def _layer_slot(self):
        """Camada do painel (1-4)."""
        return min(self.layer, self.inst.layer_count())

    def _layer_sound(self, _):
        name = self.layer_sound.currentData()
        if not name:
            return
        n = self._layer_slot()
        if n >= 3:
            self.inst.set_extra_layer(n, sound=name)
        else:
            self.inst.set_sound(n, name)
        self.user_preset = ""

    def _layer_volume(self, v):
        if self._updating:
            return
        self.inst.set_layer_volume(self._layer_slot(), v)
        self._layer_vol_text()
        dock = getattr(self.win, "dock", None)
        if dock is not None:
            dock.refresh_levels()                   # faders de volume da aba Configurações

    def _layer_vol_text(self):
        """% do volume, ou MUDO em vermelho quando o mute de emergência da camada está ligado."""
        n = self._layer_slot()
        if self.inst.layer_muted(n):
            self.layer_vol_lab.setText("MUDO")
            self.layer_vol_lab.setStyleSheet(f"color: {C['red']}; font-weight: 800;")
            self.layer_vol_lab.setToolTip("Mute de emergência ligado (aba Configurações → Volumes)")
        else:
            self.layer_vol_lab.setText(f"{round(self.layer_vol.value() / 1.27)}%")
            self.layer_vol_lab.setStyleSheet("")
            self.layer_vol_lab.setToolTip("")

    def _layer_octave(self, i):
        o = i - 2
        n = self._layer_slot()
        self.inst.all_off()
        if n >= 3:
            self.inst.extra_layers[n - 3]["oct"] = o
        elif n == 2:
            self.inst.keys["oct2"] = o
        else:
            self.inst.transpose = 12 * o
        self.inst.on_change()

    def _layer_zone(self, zone):
        n = self._layer_slot()
        if n >= 3:
            self.inst.set_extra_layer(n, zone=zone)

    def _layer_switch(self, on):
        n = self._layer_slot()
        if n == 2:
            self.set_key_mode(("split" if self.inst.keys["mode2"] == "split" else "layer") if on else "single")
            if not on:
                self.layer = 2
                self.inst.fx_layer = 1
                self.refresh()
        elif n >= 3:
            self.inst.set_extra_layer(n, on=bool(on))

    def set_key_mode(self, mode, split=None):
        """Um timbre / dois juntos / dividido; `split` = primeira nota da mão direita."""
        k = self.inst.keys
        k["layer2_on"] = mode != "single"
        if mode != "single":
            k["mode2"] = mode
            if not k["sound2"]:
                k["sound2"] = "Baixo Finger" if mode == "split" else "Pad Quente"
        if split is not None:
            k["split"] = min(max(split, SPLIT_NOTES[0]), SPLIT_NOTES[-1])
        self.inst.ready = ""
        self.user_preset = ""
        self.inst.apply_all()
        self.inst.on_change()
        self.refresh()

    # ------------------------------------------------------------------ menus de botão direito
    def _cont_menu(self, j=None):
        """j = pad B do controlador (tom configurável); sem j = grade de tons da tela."""
        menu = QMenu(self)
        if j is not None:
            menu.addSection(f"Pad {j + 1}: tom do pad contínuo")
            for key in PAD_B_CHOICES:
                a = menu.addAction(key)
                a.setCheckable(True)
                a.setChecked(self.inst.pad_keys[j] == key)
                a.triggered.connect(lambda _, key=key: self.inst.set_pad_key(j, key))
            menu.addSeparator()
        menu.addAction("Equalizador e ambiente do pad contínuo…", self.open_pad_eq)
        sub = menu.addMenu("Timbre do pad contínuo")
        for name in CONT_PAD_SOUNDS:
            a = sub.addAction(name)
            a.setCheckable(True)
            a.setChecked(self.inst.cont_sound == name)
            a.triggered.connect(lambda _, n=name: self.inst.set_cont_sound(n))
        menu.exec(self.cursor().pos())
        self.refresh()

    def _context(self, kind, i, pos):
        """Botão direito no instrumento desenhado."""
        menu = self.context_menu(kind, i)
        if menu is None:
            return
        menu.exec(pos)
        self.win.refresh_sounds()

    # alvo da tela -> (lista no mapeamento, tipos de mensagem aceitos, nome, pedido)
    PHYSICAL = {"knob": ("knobs", ("cc",), "Knob", "gire o knob ou mova o fader"),
                "button": ("buttons", ("note", "cc", "pc"), "Botão", "aperte o botão"),
                "pad": ("pads", ("note",), "Pad", "toque o pad"),
                "pad_b": ("pads_b", ("note",), "Pad do banco B", "aperte PAD-B no teclado e toque o pad")}

    def physical_key(self, target, i):
        """Mapeamento atual no formato [tipo, canal, nº] (para mostrar)."""
        group, kinds, _, _ = self.PHYSICAL[target]
        k = self.inst.mapping[group][i]
        if not k:
            return None
        return list(k) if group == "buttons" else [kinds[0], k[0], k[1]]

    def map_physical(self, target, i):
        """Botão direito → "Mapear controle físico…": medidor ao vivo e liga ao controle da tela."""
        group, kinds, name, want = self.PHYSICAL[target]
        label = BUTTONS[i] if target == "button" else str(i + 1)
        title = f"{name} {label} da tela"
        if target == "knob":
            title += f" ({self.inst.knob_funcs[i]})"
        elif target == "button":
            title += f" ({self.inst.button_funcs[i]})"
        dlg = MidiLearnDialog(self.inst, self.bridge, title, self, kinds=kinds,
                              current=self.physical_key(target, i), want=want)
        if dlg.exec() and dlg.choice is not None:
            self.assign_physical(target, i, dlg.choice)
        self.win.refresh_sounds()

    def assign_physical(self, target, i, key):
        """key = [tipo, canal, nº] ou [] para remover. Um controle físico vale para um lugar só."""
        m = self.inst.mapping
        group, kinds, _, _ = self.PHYSICAL[target]
        if key:
            kind, ch, num = key
            if kind not in kinds:
                return False
            stored = list(key) if group == "buttons" else [ch, num]
            # um controle físico, um lugar: tira dos outros botões/knobs e dos atalhos livres
            # (pads dos bancos A e B podem repetir notas: aí quem decide é o banco da tela)
            for j, k in enumerate(m["buttons"]):
                if k == list(key) and not (group == "buttons" and j == i):
                    m["buttons"][j] = None
            if kind == "cc":
                for j, k in enumerate(m["knobs"]):
                    if k == [ch, num] and not (group == "knobs" and j == i):
                        m["knobs"][j] = None
            for f, k in list(self.inst.free_map.items()):
                if k == list(key):
                    del self.inst.free_map[f]
            m[group][i] = stored
        elif group in ("knobs", "buttons"):
            m[group][i] = None
        self.inst.on_learn()
        return True

    def context_menu(self, kind, i):
        """Menu do botão direito num controle desenhado (separado para dar para testar)."""
        menu = QMenu(self)
        if kind == "pitch":
            menu.addSection("Pitch (alavanca/faixa): função")
            for func in PITCH_FUNCS:
                a = menu.addAction(func)
                a.setCheckable(True)
                a.setChecked(self.inst.pitch_func == func)
                a.triggered.connect(lambda _, f=func: self.inst.set_pitch_func(f))
            return menu
        if kind == "pad":
            bank_b = i >= PAD_COUNT
            j = i - PAD_COUNT if bank_b else i
            target = "pad_b" if bank_b else "pad"
            cur = self.physical_key(target, j)
            menu.addSection(f"Pad {j + 1}" + (" (banco B)" if bank_b else ""))
            menu.addAction(f"Mapear controle físico…   (atual: {key_text(cur)})",
                           lambda: self.map_physical(target, j))
            if bank_b:
                menu.addAction("Tom e timbre do pad contínuo…", lambda: self._cont_menu(j))
            else:
                menu.addAction("Trocar o som deste pad…", lambda: self.win.choose_pad_sound(j))
            return menu
        if kind == "knob":
            menu.addSection(f"Knob {i + 1}")
            menu.addAction(f"Mapear controle físico…   (atual: {key_text(self.physical_key('knob', i))})",
                           lambda: self.map_physical("knob", i))
            menu.addSection("Função")
            for func in KNOB_FUNCS:
                a = menu.addAction(func)
                a.setCheckable(True)
                a.setChecked(self.inst.knob_funcs[i] == func)
                a.triggered.connect(lambda _, f=func: self.inst.knob_funcs.__setitem__(i, f))
        elif kind == "button":
            menu.addSection(f"Botão {BUTTONS[i]}")
            menu.addAction(f"Mapear controle físico…   (atual: {key_text(self.physical_key('button', i))})",
                           lambda: self.map_physical("button", i))
            menu.addSection("Função")
            for func in BUTTON_FUNCS:
                a = menu.addAction(func)
                a.setCheckable(True)
                a.setChecked(self.inst.button_funcs[i] == func)
                a.triggered.connect(lambda _, f=func: self.inst.button_funcs.__setitem__(i, f))
        elif kind == "key":
            self._key_menu(menu, i)
        else:
            return None
        return menu

    def _piano_menu(self, pos):
        note, _ = self.piano._note_at(pos)
        if note is None:
            return
        menu = QMenu(self)
        self._key_menu(menu, note)
        menu.exec(self.piano.mapToGlobal(pos))
        self.win.refresh_sounds()

    def _sound_menu(self, menu, slot, current):
        for cat in CATEGORIES:
            sub = menu.addMenu(cat)
            for s in SOUNDS:
                if s.cat == cat:
                    a = sub.addAction(s.name)
                    a.setCheckable(True)
                    a.setChecked(s.name == current)
                    a.triggered.connect(lambda _, n=s.name: self.inst.set_sound(slot, n))

    def _key_menu(self, menu, note):
        """Botão direito numa tecla: timbre da zona (mão esquerda/direita) e divisão do teclado."""
        k = self.inst.keys
        mode = key_mode(k)
        left = mode == "split" and note < k["split"]
        if mode == "split":
            zone = (f"Mão esquerda (abaixo de {note_name(k['split'])})" if left
                    else f"Mão direita (de {note_name(k['split'])} para cima)")
            slot = 2 if left else 1
        else:
            zone, slot = ("Timbre 1" if mode == "layer" else "Timbre do teclado"), 1
        current = k["sound2" if slot == 2 else "sound1"]
        menu.addSection(f"{zone}: {current}")
        self._sound_menu(menu, slot, current)
        if mode == "layer":
            self._sound_menu(menu.addMenu(f"Timbre 2 (junto): {k['sound2']}"), 2, k["sound2"])
        menu.addSection("Teclado")
        cut = min(max(note + (0 if left else 1), SPLIT_NOTES[0]), SPLIT_NOTES[-1])
        menu.addAction(f"Dividir aqui: mão esquerda até {note_name(cut - 1)}",
                       lambda: self.set_key_mode("split", cut))
        if mode != "single":
            menu.addAction("Um timbre só (desfazer divisão/camada)", lambda: self.set_key_mode("single"))
        if mode != "layer":
            menu.addAction("Dois timbres juntos (camadas)", lambda: self.set_key_mode("layer"))
        sub = menu.addMenu("Timbres prontos")
        for group, items in READY_GROUPS:
            sg = sub.addMenu(group)
            for name in items:
                a = sg.addAction(name)
                a.triggered.connect(lambda _, n=name: self.load_ready(n))

    def open_pad_eq(self):
        from .analyzer import PadEqDialog

        PadEqDialog(self.inst, ACCENT, self).exec()
        self.win.refresh_sounds()

    # ------------------------------------------------------------------ mapeamento físico (_Mapped)
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

    # ------------------------------------------------------------------ presets (barra superior)
    def send_sound(self, sound, fx, part):
        """Parte de um preset do banco: timbre na L1, na L2, numa camada nova, só os efeitos na
        camada selecionada ou o timbre no pad contínuo."""
        inst = self.inst
        if part == "l1":
            inst.set_sound(1, sound)
            self.select_layer(1)
        elif part == "l2":
            inst.set_sound(2, sound)
            if key_mode(inst.keys) == "single":
                self.set_key_mode("layer")
            self.select_layer(2)
        elif part == "new_layer":
            n = inst.add_layer(sound)
            if n is None:
                QMessageBox.information(self, "Camadas", "Já tem 4 camadas: remova uma para adicionar outra.")
                return
            self.select_layer(n)
        elif part == "fx":
            n = self._layer_slot()
            inst.layer_fx[n - 1] = dict(DEFAULT_FX)
            inst.layer_fx[n - 1].update({k: v for k, v in fx.items() if k in DEFAULT_FX})
            inst.ready = ""
            inst.apply_fx()
            inst.on_change()
        elif part == "cont":
            inst.set_cont_sound(sound)
        self.user_preset = ""
        self.refresh()

    def load_ready(self, name):
        self.user_preset = ""
        self.inst.set_ready(name)

    def show_key(self, note, on):
        self.piano.set_active(note, on)
        self.ctrl.set_key(note, on)

    def update_meters(self):
        return self.amp_page.update_meters()

    # ------------------------------------------------------------------ atualização
    def refresh_values(self):
        """Só os valores (knobs, chaves): chamado também quando um controle MIDI mexe em algo."""
        inst, fx = self.inst, self.inst.fx
        self._updating = True
        try:
            for func, k in self.big_knobs.items():
                k.setValue(func_value(self.engine, func))
            self.fx_switch["Rotação liga/desliga"].setChecked(fx["rot_on"])
            self.fx_switch["Drive liga/desliga"].setChecked(fx["drive_on"])
            self.fx_switch["Delay liga/desliga"].setChecked(fx["delay_on"])
            self.rot_speed.setCurrentIndex(1 if fx["rot_fast"] else 0)
            self.rot_sync.setChecked(bool(fx["rot_sync"]))
            if fx["rot_sync"]:
                self.rot_rate.setRange(0, len(ROT_MULTS) - 1)
                m = fx[self._rot_key()]
                self.rot_rate.setValue(min(range(len(ROT_MULTS)), key=lambda q: abs(ROT_MULTS[q] - m)))
            else:
                import math
                self.rot_rate.setRange(0, 100)
                hz = max(0.3, min(10.0, fx[self._rot_key()]))
                self.rot_rate.setValue(round(100 * math.log(hz / 0.3) / math.log(10 / 0.3)))
            self.drive.setValue(int(fx["drive"]))
            self.delay_div.setCurrentIndex(int(fx.get("delay_div", 0)))
            self.touch.setValue(int(inst.levels["touch"]))
            self.action_buttons["Sustain (segurar)"].setChecked(inst.sustain)
            self.bpm.set_value(inst.bpm)
            vol = inst.layer_volume(self._layer_slot())       # um knob pode ter mexido no volume
            if vol is not None and vol != self.layer_vol.value():
                self.layer_vol.setValue(int(vol))
            self._layer_vol_text()
        finally:
            self._updating = False
        self._rot_rate_text()
        for w in self.mapped.values():
            w.refresh()

    def refresh(self):
        inst = self.inst
        k = inst.keys
        mode = key_mode(k)
        self.title.setText(_short(self.user_preset or inst.ready or "Timbre personalizado", 34))
        sub = k["sound1"]
        if mode == "layer":
            sub = f"{k['sound1']} + {k['sound2']}"
        elif mode == "split":
            sub = f"{k['sound2']} (esq.) | {k['sound1']} (dir.)"
        self.subtitle.setText(sub)
        count = inst.layer_count()
        self.layer = max(1, min(self.layer, count))
        inst.fx_layer = self.layer - 1
        names = [("LAYER 1", k["sound1"]), ("LAYER 2", k["sound2"] if mode != "single" else "desligado")]
        if mode == "split":
            names = [("MÃO DIREITA", k["sound1"]), ("MÃO ESQUERDA", k["sound2"])]
        for n, lay in enumerate(inst.extra_layers, start=3):
            zone = {"left": " (esq.)", "right": " (dir.)"}.get(lay["zone"], "")
            names.append((f"LAYER {n}{zone}", lay["sound"] if lay["on"] else "desligado"))
        width = 20 if count <= 2 else 13
        for i, b in enumerate(self.layer_buttons):
            b.setVisible(i < count)
            b.setIcon(icon("keys", C["text"], 22) if count <= 2 else QIcon())   # 4 camadas: espaço p/ o nome
            if i < count:
                b.setText(f"{names[i][0]}\n{_short(names[i][1], width)}")
                b.setChecked(self.layer == i + 1)
        for i, b in enumerate(self.side_layer_buttons):
            b.setVisible(i < count)
            b.setChecked(self.layer == i + 1)
            if i < count:
                b.setToolTip(f"{names[i][0].title()}: {names[i][1]}")
        self.add_layer_btn.setEnabled(count < MAX_LAYERS)
        self.mode.setCurrentIndex(("single", "layer", "split").index(mode))
        self.split.setVisible(mode == "split")
        if k["split"] in SPLIT_NOTES:
            self.split.setCurrentIndex(SPLIT_NOTES.index(k["split"]))

        n = self.layer
        if n >= 3:
            lay = inst.extra_layers[n - 3]
            sname, vol, octv, on = lay["sound"], lay["vol"], lay["oct"], lay["on"]
        elif n == 2:
            sname, vol, octv, on = k["sound2"], k["vol2"], k.get("oct2", 0), mode != "single"
        else:
            sname, vol, octv, on = k["sound1"], k["vol1"], inst.transpose // 12, True
        snd = SOUND_BY_NAME.get(sname or "")
        where = {"split": "mão direita" if n == 1 else ("mão esquerda" if n == 2 else ""),
                 }.get(mode, "") if n <= 2 else {"all": "teclado todo", "left": "mão esquerda",
                                                 "right": "mão direita"}[inst.extra_layers[n - 3]["zone"]]
        self.layer_name.setText(_short(sname or "—", 22))
        self.layer_sub.setText(" · ".join(x for x in ((snd.cat if snd else ""), where) if x))
        self.layer_art.set_kind(snd.cat if snd else "Pianos", sname or "")
        self.art.set_kind(snd.cat if snd else "Pianos", sname or "")   # foto da camada selecionada
        i = self.layer_sound.findData(sname)
        if i >= 0:
            self.layer_sound.setCurrentIndex(i)
        self.layer_on.setVisible(n >= 2)
        self.remove_layer_btn.setVisible(n >= 3)
        self.zone_label.setVisible(n >= 3)
        self.layer_zone.setVisible(n >= 3)
        self._updating = True
        try:
            self.layer_on.setChecked(bool(on))
            self.layer_vol.setValue(int(vol))
            self._layer_vol_text()
            self.layer_oct.setCurrentIndex(max(0, min(4, octv + 2)))
            if n >= 3:
                self.layer_zone.setCurrentIndex(LAYER_ZONES.index(inst.extra_layers[n - 3]["zone"]))
        finally:
            self._updating = False
        self.oct_label.setText("Oitava" if n >= 2 else "Oitava (teclado)")
        self.fx_title.setText(f"Efeitos da Layer {n}" + ("" if on else " (desligada)"))

        self.cont_title.setText("Pad contínuo")
        for name, b in self.cont_sound_buttons.items():
            b.setChecked(name == inst.cont_sound)
        for key, b in self.cont_buttons.items():
            on = key == inst.cont_key
            sharp = b.property("sharp")
            if on:
                bg, bottom, bd = "#2f7cf6", "#1a4fb0", "#8fbaff"
            elif sharp:
                bg, bottom, bd = "#0f1d36", "#08101f", "#2a4677"
            else:
                bg, bottom, bd = "#17305a", "#0f2142", "#2d5aa6"
            size = "9pt" if sharp else "17pt"
            b.setStyleSheet(f"QPushButton {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, "
                            f"stop:0 {bg}, stop:1 {bottom}); border: 1px solid {bd}; color: white;"
                            f" font-size: {size}; font-weight: 700; border-radius: 8px; padding: 0; }}"
                            f"QPushButton:hover {{ border: 2px solid #8fbaff; }}")
        self.stop_btn.setEnabled(inst.cont_key is not None)

        simple = is_simple(inst.device)
        self.device.setCurrentText(SIMPLE if simple else inst.device)
        self.kbd_stack.setCurrentIndex(0 if simple else 1)
        self.knob_card.setVisible(simple)
        self.piano.split_note = k["split"] if mode == "split" else None
        self.piano.zone_names = (k["sound2"], k["sound1"]) if mode == "split" else ("", "")
        self.piano.update()
        flags = []
        if inst.transpose:
            flags.append(f"oitava {inst.transpose // 12:+d}")
        if inst.sustain:
            flags.append("sustain")
        self.kbd_info.setText("   " + " · ".join(flags) + ("   ·   " if flags else "   ") +
                              "botão direito numa tecla: trocar timbre ou dividir")
        if not simple:
            c = self.ctrl
            if c.model_name != inst.device:
                c.set_model(inst.device)
            c.display = (inst.display_text(), inst.display_line2())
            names = list(READY)
            c.ready_index = names.index(inst.ready) + 1 if inst.ready in names else 0
            c.pad_labels = list(inst.pad_sounds)
            c.pad_keys_b = list(inst.pad_keys)
            c.bank = inst.screen_bank
            c.cont_key = inst.cont_key
            c.knob_labels = list(inst.knob_funcs)
            c.button_labels = list(inst.button_funcs)
            c.split_note = k["split"] if mode == "split" else None
            c.zone_names = (k["sound2"], k["sound1"]) if mode == "split" else ("", k["sound1"])
            steps = inst.learn_steps
            c.learn_target = steps[0] if steps else None
            c.update()
        self.refresh_values()
