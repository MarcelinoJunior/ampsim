"""Controles dos plugins VST3 (o motor está em audio/vst.py: PluginChain e PluginSlot).

API para usar numa parte nova do AmpSim (ex.: uma trilha nova):
 - FxButton(get_chain, open_fn, parent=None, small=False): botão "FX" que acende (verde = algum plugin
   ligado, vermelho = erro ou plugin não encontrado, amarelo = carregando) e chama open_fn() ao clicar.
 - FxLine(get_chain, open_fn, label="Plugins"): linha "Plugins: Dragonfly Room Reverb ✓   [FX]".
 - FxChainWindow(get_chain, title, on_downloads=None, parent=None, note_fn=None): janela não modal com a
   cadeia (até 4 plugins em série): escolher plugin, liga/desliga, Mix, ⚙ painel do plugin, ↑ ↓ ordem,
   ✕ remover e "+ Adicionar plugin". A janela principal guarda uma por cadeia (MainWindow.open_fx).
 - PluginSlotWidget(get_slot, ...): os controles de um plugin (uma linha da janela).
Com chain_id ("L1"…"L4", "master", "guitar", "bass", "vocal"), a chave e o Mix têm o botão direito "Mapear
controle físico…" e o botão "Parâmetros" lista os parâmetros internos do plugin para mapear (midi_map.py).
get_chain/get_slot são funções (a cadeia de uma camada muda quando uma camada é removida).
O painel do plugin abre numa janela própria e o AmpSim continua usável (ver audio/vst.py).
"""
import os

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QSlider, QVBoxLayout, QWidget,
)

from ..audio import vst
from .icons import icon
from .theme import C
from .widgets import ToggleSwitch

NONE, BROWSE, DOWNLOADS, RETRY = "", "\x00procurar", "\x00downloads", "\x00tentar"
STATE_COLOR = {"on": "green", "err": "red", "loading": "yellow", "off": "dim"}


class _Bridge(QObject):
    changed = Signal()               # algo mudou (pode vir da thread dos plugins)
    closed = Signal(str)             # o painel do plugin fechou


# ------------------------------------------------------------------ botão FX
class FxButton(QPushButton):
    """Botão "FX" de uma cadeia: a cor diz se há plugin ligado (verde), erro (vermelho) ou nada (cinza)."""

    def __init__(self, get_chain, open_fn, parent=None, small=False):
        super().__init__("FX", parent)
        self.get_chain = get_chain
        self.small = small
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.PointingHandCursor)
        if small:
            self.setFixedSize(32, 19)       # etiqueta no canto do botão LAYER (cabe sem mudar a altura dele)
        self.clicked.connect(lambda *_: open_fn())
        self._state = None
        self.timer = QTimer(self)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self.sync)
        self.timer.start()
        self.sync()

    def sync(self):
        chain = self.get_chain()
        text, st = chain.summary() if chain is not None else ("Nenhum plugin", "off")
        key = (text, st)
        if key == self._state:
            return
        self._state = key
        color = C[STATE_COLOR[st]]
        border = color if st != "off" else C["border2"]
        size = "7.5pt" if self.small else "8pt"
        self.setStyleSheet(f"QPushButton {{ background: {C['card']}; border: 1px solid {border}; color: {color}; "
                           f"font-weight: 800; font-size: {size}; border-radius: 5px; padding: 0px 4px; }}"
                           f"QPushButton:hover {{ border-color: {C['accent']}; }}")
        self.setToolTip("Plugins (FX): " + text + "\nClique para escolher plugins VST3 (reverb, delay, EQ…)")

    @property
    def state(self):
        return self._state[1] if self._state else "off"


class FxLine(QWidget):
    """Linha "Plugins: … [FX]" (painel Instrumento / Layer, trilhas)."""

    def __init__(self, get_chain, open_fn, label="Plugins", parent=None):
        super().__init__(parent)
        self.get_chain = get_chain
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.label = QLabel(label)
        lay.addWidget(self.label)
        self.summary = QLabel("")
        self.summary.setObjectName("small")
        self.summary.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)   # não alarga o painel
        lay.addWidget(self.summary, 1)
        self.button = FxButton(get_chain, open_fn, self)
        self.button.setFixedSize(40, 22)
        lay.addWidget(self.button)
        self.button.timer.timeout.connect(self.sync)
        self.sync()

    def sync(self):
        chain = self.get_chain()
        text, st = chain.summary() if chain is not None else ("Nenhum plugin", "off")
        self.summary.setToolTip(text)
        fm = self.summary.fontMetrics()
        self.summary.setText(fm.elidedText(text, Qt.ElideRight, max(40, self.summary.width())))
        self.summary.setStyleSheet(f"color: {C[STATE_COLOR[st]]};")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.sync()


# ------------------------------------------------------------------ um plugin
class PluginSlotWidget(QWidget):
    """Controles de um plugin: [liga] título [lista] [⚙] (+ botões extras) / Mix / aviso.
    get_slot() -> PluginSlot. on_downloads(): abre a tela de downloads (opcional)."""

    def __init__(self, get_slot, title="Plugin", on_downloads=None, parent=None, chain_id=None, index=0):
        super().__init__(parent)
        self.get_slot = get_slot
        self.on_downloads = on_downloads
        self.chain_id = chain_id
        self.index = index
        self._updating = False
        self.bridge = _Bridge(self)          # filho do widget: some com ele (sem ciclo pelo C++)
        self.bridge.closed.connect(self._editor_closed)
        g = QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(4)
        self.switch = ToggleSwitch()
        self.switch.setToolTip("Liga/desliga o plugin")
        self.switch.clicked.connect(self._toggle)
        g.addWidget(self.switch, 0, 0)
        self.title = QLabel(title)
        g.addWidget(self.title, 0, 1)
        self.combo = QComboBox()
        self.combo.setFocusPolicy(Qt.NoFocus)
        self.combo.activated.connect(self._chosen)
        self.combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.combo.setMinimumContentsLength(10)
        self.top = QHBoxLayout()
        self.top.setSpacing(4)
        self.top.addWidget(self.combo, 1)
        self.editor_btn = QPushButton()
        self.editor_btn.setIcon(icon("gear", C["text"], 14))
        self.editor_btn.setFixedSize(30, 26)
        self.editor_btn.setCheckable(True)
        self.editor_btn.setFocusPolicy(Qt.NoFocus)
        self.editor_btn.clicked.connect(self._editor)
        self.top.addWidget(self.editor_btn)
        self.params_btn = None
        if chain_id:
            self.params_btn = QPushButton()
            self.params_btn.setIcon(icon("midi", C["text"], 14))
            self.params_btn.setObjectName("fx_params")
            self.params_btn.setFixedSize(30, 26)
            self.params_btn.setFocusPolicy(Qt.NoFocus)
            self.params_btn.setToolTip("Parâmetros do plugin: mapear um knob do controlador num parâmetro interno")
            self.params_btn.clicked.connect(self._params)
            self.top.addWidget(self.params_btn)
        g.addLayout(self.top, 0, 2)
        self.mix_row = QWidget()
        mrow = QHBoxLayout(self.mix_row)
        mrow.setContentsMargins(0, 0, 0, 0)
        mrow.setSpacing(4)
        self.mix = QSlider(Qt.Horizontal)
        self.mix.setRange(0, 100)
        self.mix.setFocusPolicy(Qt.NoFocus)
        self.mix.setToolTip("Seco/molhado: 0 = sem o plugin, 100 = só o que sai do plugin")
        self.mix.valueChanged.connect(self._mix)
        mrow.addWidget(self.mix, 1)
        self.mix_lab = QLabel("")
        self.mix_lab.setObjectName("small")
        self.mix_lab.setFixedWidth(36)
        mrow.addWidget(self.mix_lab)
        g.addWidget(QLabel("Mix"), 1, 1)
        g.addWidget(self.mix_row, 1, 2)
        self.status = QLabel("")
        self.status.setObjectName("small")
        self.status.setWordWrap(True)
        g.addWidget(self.status, 2, 0, 1, 3)
        g.setColumnStretch(2, 1)
        if chain_id:
            from .ctl_map_ui import install
            install(self.switch, f"fx/{chain_id}/{index + 1}/on")
            install(self.mix, f"fx/{chain_id}/{index + 1}/mix")
        self.fill()
        self.refresh()

    def add_tool(self, w):
        """Botão extra na linha de cima (↑ ↓ ✕ da janela da cadeia)."""
        self.top.addWidget(w)

    # ------------------------------------------------------------------ lista
    def fill(self):
        """Recarrega a lista de plugins (depois de baixar/instalar um)."""
        slot = self.get_slot()
        cur = slot.path if slot is not None else ""
        self._updating = True
        try:
            c = self.combo
            c.clear()
            c.addItem("Escolha um plugin…" if not cur else "Nenhum plugin", NONE)
            paths = vst.find_plugins()
            bad = 0
            for p in paths:
                why, now = vst.bad_info(p)
                c.addItem(vst.display_name(p) + ((" (não abre)" if now else " (não abriu da última vez)")
                                                 if why else ""), p)
                if why:
                    bad += 1
                    c.setItemData(c.count() - 1, why + "\nEscolha para tentar abrir de novo.", Qt.ToolTipRole)
            if cur and all(os.path.normcase(cur) != os.path.normcase(p) for p in paths):
                gone = "" if os.path.exists(cur) else " (não encontrado)"
                c.addItem(vst.display_name(cur) + gone, cur)
            c.insertSeparator(c.count())
            if bad:                         # tira as marcas "(não abre)": cada um é testado de novo ao escolher
                c.addItem("Tentar de novo os que não abriram", RETRY)
            c.addItem("Procurar arquivo…", BROWSE)
            if self.on_downloads is not None:
                c.addItem("Baixar plugins grátis…", DOWNLOADS)
        finally:
            self._updating = False

    # ------------------------------------------------------------------ ações
    def _chosen(self, _i):
        if self._updating:
            return
        data = self.combo.currentData()
        slot = self.get_slot()
        if slot is None:
            return
        trust = False
        if data == RETRY:
            vst.forget_bad()
            self.fill()
            self.refresh()
            return
        if data == DOWNLOADS:
            self.refresh()
            self.on_downloads()
            return
        if data == BROWSE:
            start = vst.user_vst3_dir() if os.path.isdir(vst.user_vst3_dir()) else vst.SYSTEM_VST3_DIR
            path, _ = QFileDialog.getOpenFileName(self, "Escolher plugin VST3", start, "Plugins VST3 (*.vst3)")
            if not path:
                self.refresh()
                return
            data = vst.bundle_of(os.path.normpath(path))
            trust = True                    # lembrado só se abrir (PluginSlot.load)
        if data == slot.path and (slot.inst is not None or slot.loading):
            self.refresh()
            return
        slot.on = bool(data)                # escolheu um plugin: já liga
        slot.load(data, trust=trust)
        self.fill()
        self.refresh()

    def _toggle(self):
        slot = self.get_slot()
        if slot is not None and not self._updating:
            slot.set_on(self.switch.isChecked())
            self.refresh()

    def _mix(self, v):
        self.mix_lab.setText(f"{v}%")
        slot = self.get_slot()
        if slot is not None and not self._updating:
            slot.set_mix(v)

    def _editor(self):
        slot = self.get_slot()
        if slot is None:
            return
        if slot.editor_open:
            vst.host().close_editor()
            return
        if slot.show_editor(on_closed=self.bridge.closed.emit):
            self.status.setText("Painel do plugin aberto numa janela própria: o AmpSim continua funcionando. "
                                "Trocar de plugin fecha o painel.")
            self.status.setStyleSheet(f"color: {C['dim']};")
            QTimer.singleShot(300, self.refresh)

    def _params(self):
        from .ctl_map_ui import PluginParamsDialog, find_win
        win = find_win(self)
        if win is None or self.get_slot() is None:
            return
        PluginParamsDialog(win, self.chain_id, self.index, self.window()).exec()

    def _editor_closed(self, err):
        self.refresh()
        if err:
            self.status.setText(f"Não deu para abrir o painel do plugin: {err}")
            self.status.setStyleSheet(f"color: {C['red']};")

    # ------------------------------------------------------------------ estado
    def refresh(self):
        slot = self.get_slot()
        if slot is None:
            self.setEnabled(False)
            return
        self.setEnabled(True)
        failed = bool(slot.load_error or slot.missing)
        self._updating = True
        try:
            i = self.combo.findData(slot.path)
            if i < 0:
                self.fill()
                i = self.combo.findData(slot.path)
            self.combo.setCurrentIndex(max(i, 0))
            # plugin que não abriu: a chave fica desligada e inativa (não dá a impressão de que está tocando)
            self.switch.setChecked(bool(slot.on and slot.path) and not failed)
            self.switch.setEnabled(bool(slot.path) and not failed)
            v = int(round(slot.mix * 100))
            self.mix.setValue(v)
            self.mix_lab.setText(f"{v}%")
            self.mix.setEnabled(bool(slot.path) and not failed)
        finally:
            self._updating = False
        self.editor_btn.setEnabled(slot.inst is not None and not slot.loading)
        if self.params_btn is not None:
            self.params_btn.setEnabled(slot.inst is not None and not slot.loading)
        self.editor_btn.setChecked(slot.editor_open)
        self.editor_btn.setToolTip(("Fechar" if slot.editor_open else "Abrir") + " o painel do plugin "
                                   "(janela própria; o AmpSim continua funcionando)")
        text = slot.status()
        if slot.editor_open:
            text += " · painel aberto numa janela própria"
        color = C["dim"]
        if slot.load_error or slot.run_error:
            color = C["red"]
        elif slot.missing or slot.loading:
            color = C["yellow"]
        elif slot.ok and slot.on:
            color = C["green"]
        self.status.setText(text if slot.path else "Escolha um efeito VST3 na lista.")
        self.status.setStyleSheet(f"color: {color};")
        self.status.setToolTip(slot.load_detail or "")


# ------------------------------------------------------------------ janela da cadeia
class FxChainWindow(QDialog):
    """Janela (não modal) "Plugins — …": a cadeia FX de uma camada, do Master ou de uma trilha."""

    def __init__(self, get_chain, title, on_downloads=None, parent=None, note_fn=None, intro="", chain_id=None):
        super().__init__(parent)
        self.get_chain = get_chain
        self.chain_id = chain_id            # para o mapeamento MIDI (midi_map.py): "L1", "master", "guitar"…
        self.on_downloads = on_downloads
        self.note_fn = note_fn
        self._chain = None
        self._shown = None
        self.rows = []
        self.setWindowTitle(title)
        self.setModal(False)
        self.resize(540, 470)
        self.bridge = _Bridge(self)          # filho do widget: some com ele (sem ciclo pelo C++)
        self.bridge.changed.connect(self._sync)
        lay = QVBoxLayout(self)
        self.intro = QLabel(intro or "Plugins em série, de cima para baixo (até 4). O painel de cada plugin "
                            "(⚙) abre numa janela própria.")
        self.intro.setWordWrap(True)
        self.intro.setObjectName("small")
        self.intro.setStyleSheet(f"color: {C['dim']};")
        lay.addWidget(self.intro)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setObjectName("small")
        self.note.setStyleSheet(f"color: {C['yellow']};")
        lay.addWidget(self.note)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        self.rows_lay = QVBoxLayout(body)
        self.rows_lay.setContentsMargins(0, 0, 4, 0)
        self.rows_lay.setSpacing(6)
        self.rows_lay.addStretch(1)
        scroll.setWidget(body)
        lay.addWidget(scroll, 1)
        bottom = QHBoxLayout()
        self.add_btn = QPushButton(" Adicionar plugin")
        self.add_btn.setIcon(icon("add", C["text"], 14))
        self.add_btn.setObjectName("primary")
        self.add_btn.setFocusPolicy(Qt.NoFocus)
        # cheia (4 de 4): bem apagado, não só um azul mais claro
        self.add_btn.setStyleSheet(f"QPushButton#primary:disabled {{ background: {C['card']}; color: {C['faint']}; "
                                   f"border: 1px dashed {C['border2']}; font-weight: 400; }}")
        self.add_btn.clicked.connect(self.add_slot)
        bottom.addWidget(self.add_btn)
        bottom.addStretch(1)
        self.count_lab = QLabel("")
        self.count_lab.setObjectName("small")
        bottom.addWidget(self.count_lab)
        lay.addLayout(bottom)
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self._poll)
        self.timer.start()
        self.bind()

    # ------------------------------------------------------------------ cadeia mostrada
    def bind(self):
        chain = self.get_chain()
        if chain is not self._chain:
            if self._chain is not None:
                self._chain.remove_listener(self.bridge.changed.emit)
            self._chain = chain
            if chain is not None:
                chain.add_listener(self.bridge.changed.emit)
            self._shown = None
        self._sync()

    def _sync(self):
        chain = self._chain
        slots = tuple(chain.slots) if chain is not None else ()
        if slots != self._shown:
            self._rebuild(slots)
        for r in self.rows:
            r.refresh()
        n = len(slots)
        self.add_btn.setEnabled(chain is not None and n < vst.MAX_CHAIN)
        self.count_lab.setText(f"{n} de {vst.MAX_CHAIN} plugins")
        note = self.note_fn() if self.note_fn else ""
        self.note.setText(note)
        self.note.setVisible(bool(note))

    def _poll(self):
        if self.get_chain() is not self._chain:
            self.bind()
        elif self.isVisible():
            for r in self.rows:
                r.refresh()

    def _rebuild(self, slots):
        for r in self.rows:
            r.parentWidget().deleteLater()
        self.rows = []
        for i, slot in enumerate(slots):
            card = QFrame()
            card.setObjectName("card")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(10, 8, 10, 8)
            w = PluginSlotWidget(lambda s=slot: s, f"{i + 1}.", self.on_downloads, card, chain_id=self.chain_id,
                                 index=i)
            for ic, tip, fn, ok in (("up", "Subir (vem antes na cadeia)", lambda _=0, i=i: self.move(i, -1), i > 0),
                                    ("down", "Descer (vem depois na cadeia)", lambda _=0, i=i: self.move(i, 1),
                                     i < len(slots) - 1),
                                    ("close", "Remover este plugin", lambda _=0, i=i: self.remove(i), True)):
                b = QPushButton()
                b.setIcon(icon(ic, C["text"], 13))
                b.setObjectName("fx_" + ic)
                b.setFixedSize(28, 26)
                b.setFocusPolicy(Qt.NoFocus)
                b.setToolTip(tip)
                b.setEnabled(ok)
                b.clicked.connect(fn)
                w.add_tool(b)
            cl.addWidget(w)
            self.rows_lay.insertWidget(self.rows_lay.count() - 1, card)
            self.rows.append(w)
        self._shown = slots

    # ------------------------------------------------------------------ ações
    def add_slot(self):
        if self._chain is not None and self._chain.add() is not None:
            self._sync()

    def move(self, i, delta):
        if self._chain is not None:
            self._chain.move(i, delta)
            self._sync()

    def remove(self, i):
        if self._chain is not None:
            self._chain.remove(i)
            self._sync()

    def refresh_lists(self):
        """Plugins instalados/removidos: recarrega as listas."""
        for r in self.rows:
            r.fill()
            r.refresh()
