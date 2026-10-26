"""Teclas de atalho: padrão de fábrica, troca pelo usuário (Configurações → Teclas de atalho).

Os atalhos valem com a janela principal em foco. Só combinações com Ctrl/Alt, F1-F12 e Esc:
as letras sozinhas continuam tocando notas no teclado do PC.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QGridLayout, QKeySequenceEdit, QLabel, QMessageBox, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

# (id, nome, padrão)
ACTIONS = (
    ("mute_all", "Mute geral (tudo sem som)", "Alt+Space"),
    ("mute_l1", "Mute da L1", "Alt+1"),
    ("mute_l2", "Mute da L2", "Alt+2"),
    ("mute_l3", "Mute da L3", "Alt+3"),
    ("mute_l4", "Mute da L4", "Alt+4"),
    ("mute_pad", "Mute do pad contínuo", "Alt+P"),
    ("mute_drums", "Mute dos pads (bateria)", "Alt+B"),
    ("preset_next", "Próximo preset", "Ctrl+Right"),
    ("preset_prev", "Preset anterior", "Ctrl+Left"),
    ("song_next", "Setlist: próxima música", "Ctrl+PgDown"),
    ("song_prev", "Setlist: música anterior", "Ctrl+PgUp"),
    ("tab_guitar", "Aba Guitarra", "F1"),
    ("tab_bass", "Aba Baixo", "F2"),
    ("tab_pads", "Aba Pad/Piano", "F3"),
    ("panic", "Pânico (solta as notas e para o pad)", "Esc"),
    ("rec", "Gravador: REC / STOP", "Ctrl+R"),
    ("tap", "Tap tempo (BPM)", "Ctrl+T"),
    ("click", "Metrônomo liga/desliga", "Ctrl+M"),
    ("stop_pad", "Parar o pad contínuo", "Ctrl+Space"),
)
DEFAULTS = {a: k for a, _, k in ACTIONS}
NAMES = {a: n for a, n, _ in ACTIONS}


def clean_keys(d):
    """Atalhos vindos do arquivo de sessão: só ações conhecidas e textos de tecla."""
    out = dict(DEFAULTS)
    if isinstance(d, dict):
        for a, k in d.items():
            if a in DEFAULTS and isinstance(k, str):
                out[a] = QKeySequence(k).toString() if k else ""
    return out


def conflicts(keys):
    """{tecla: [ações]} das teclas usadas por mais de uma ação."""
    seen = {}
    for a, k in keys.items():
        if k:
            seen.setdefault(k, []).append(a)
    return {k: v for k, v in seen.items() if len(v) > 1}


class Shortcuts:
    """Cria os QShortcut da janela e chama win.shortcut_action(id)."""

    def __init__(self, win, keys=None):
        self.win = win
        self.keys = clean_keys(keys)
        self._items = {}
        self.apply()

    def apply(self):
        for sc in self._items.values():
            sc.setEnabled(False)
            sc.deleteLater()
        self._items = {}
        for a, k in self.keys.items():
            if not k:
                continue
            sc = QShortcut(QKeySequence(k), self.win)
            sc.setContext(Qt.WindowShortcut)
            sc.setAutoRepeat(False)
            sc.activated.connect(lambda a=a: self.win.shortcut_action(a))
            self._items[a] = sc

    def set_keys(self, keys):
        self.keys = clean_keys(keys)
        self.apply()

    def text(self, action):
        k = self.keys.get(action, "")
        return QKeySequence(k).toString(QKeySequence.NativeText) if k else ""


class ShortcutsDialog(QDialog):
    def __init__(self, shortcuts, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Teclas de atalho")
        self.resize(520, 560)
        self.shortcuts = shortcuts
        lay = QVBoxLayout(self)
        tip = QLabel("Clique no campo e aperte a combinação nova. Use Ctrl ou Alt (as letras sozinhas tocam "
                     "notas no teclado do PC). “Limpar” deixa a ação sem atalho.")
        tip.setWordWrap(True)
        tip.setObjectName("small")
        lay.addWidget(tip)
        body = QWidget()
        grid = QGridLayout(body)
        grid.setHorizontalSpacing(8)
        self.edits = {}
        for row, (a, name, _) in enumerate(ACTIONS):
            grid.addWidget(QLabel(name), row, 0)
            e = QKeySequenceEdit(QKeySequence(shortcuts.keys.get(a, "")))
            e.setMaximumSequenceLength(1)
            self.edits[a] = e
            grid.addWidget(e, row, 1)
            clear = QPushButton("Limpar")
            clear.setFocusPolicy(Qt.NoFocus)
            clear.clicked.connect(lambda _, e=e: e.clear())
            grid.addWidget(clear, row, 2)
        scroll = QScrollArea()
        scroll.setWidget(body)
        scroll.setWidgetResizable(True)
        lay.addWidget(scroll, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults)
        buttons.button(QDialogButtonBox.RestoreDefaults).setText("Restaurar padrão")
        buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self.restore)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def keys(self):
        return {a: e.keySequence().toString() for a, e in self.edits.items()}

    def restore(self):
        for a, e in self.edits.items():
            e.setKeySequence(QKeySequence(DEFAULTS[a]))

    def accept(self):
        dup = conflicts(self.keys())
        if dup:
            k, acts = next(iter(dup.items()))
            QMessageBox.warning(self, "Teclas de atalho",
                                f"“{k}” está em mais de uma ação: " + " e ".join(NAMES[a] for a in acts) + ".")
            return
        self.shortcuts.set_keys(self.keys())
        super().accept()
