"""Mapeamento de controle físico: botão direito em qualquer knob/botão da tela ->
"Mapear controle físico…" abre um medidor ao vivo do que chega do controlador MIDI.
"""
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QMenu, QProgressBar, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..instruments import KNOB_FUNCS
from .theme import C


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
        if kind not in ("cc", "note"):
            return
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


class Mapped(QWidget):
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
        short = (f"{'CC' if k[0] == 'cc' else 'N'}{k[2]}" if k else "")
        self.tag.setText("⇄ " + short if k else short)
        self.tag.setStyleSheet(f"color: {C['green']}; font-size: 7.5pt;" if k else f"color: {C['faint']}; font-size: 7.5pt;")
        tip = (f"{self.func}\nMapeado em: {key_text(k)}" if k
               else f"{self.func}\nBotão direito: mapear controle físico")
        self.setToolTip(tip)
