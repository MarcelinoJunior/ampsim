"""Banco de Presets (lateral esquerda): busca e lista de tudo que dá para carregar.

Mostra só o que serve para a aba aberta lá em cima (set_page): Guitarra, Baixo ou Pad/Piano (timbres
prontos e os seus, amp/efeitos das teclas), mais os arquivos .ampsim da pasta Documentos\\AmpSim
desse tipo. O botão direito oferece partes do preset (timbre na L1/L2, só o amp, só os efeitos...).
"""
import json

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFont, QPalette
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout,
)

from .. import storage
from ..instruments import CONT_PAD_SOUNDS, READY, READY_GROUPS
from ..presets import FACTORY
from ..sharing import EXTENSION
from .icons import icon
from .theme import C

ROLE = Qt.UserRole                 # (tipo, nome): ("ready"|"keys_user"|"track"|"file", ...)
TRACK_TITLES = (("guitar", "Guitarra", "guitar"), ("bass", "Baixo", "bass"), ("vocal", "Vocal", "mic"))


class PresetBank(QFrame):
    """Emite activated(kind, data) quando um item é escolhido."""

    activated = Signal(str, object)
    requestSave = Signal()
    requestImport = Signal()
    requestExport = Signal(str, object)
    requestDelete = Signal(str, object)
    requestShareCode = Signal(str, object)
    requestPart = Signal(str, object, str)      # (tipo, nome, parte): ver _menu

    def __init__(self):
        super().__init__()
        self.setObjectName("side")
        # subjanela: a largura acompanha o divisor (padrão 242; mínimo = o que cabe sem cortar nada)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 10)
        lay.setSpacing(8)
        head = QHBoxLayout()
        hi = QLabel()
        hi.setPixmap(icon("folder", C["text"], 18).pixmap(18, 18))
        head.addWidget(hi)
        t = QLabel("Banco de Presets")
        t.setObjectName("h2")
        head.addWidget(t, 1)
        self.head_widgets = (hi, t)           # numa subjanela o título já está na barra dela
        lay.addLayout(head)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar presets…")
        self.search.addAction(icon("search", C["dim"], 16), QLineEdit.TrailingPosition)
        self.search.textChanged.connect(self._filter)
        self.search.setClearButtonEnabled(True)
        lay.addWidget(self.search)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        # sem recuo do Qt: o estilo do Windows pinta a seleção no recuo (blocos azuis à esquerda);
        # o recuo vem de espaços no texto (ver _indent)
        self.tree.setIndentation(0)
        self.tree.setRootIsDecorated(False)
        self.tree.setIconSize(QSize(16, 16))
        self.tree.setFocusPolicy(Qt.NoFocus)
        pal = self.tree.palette()                   # a seleção só pinta o item (não o recuo)
        pal.setColor(QPalette.Highlight, Qt.transparent)
        self.tree.setPalette(pal)
        self.tree.itemClicked.connect(self._clicked)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.tree, 1)

        row = QHBoxLayout()
        row.setSpacing(6)
        for text, ic, tip, sig in (("Salvar", "save", "Salvar o som atual como preset seu", self.requestSave),
                                   ("Importar", "download", "Abrir/importar um arquivo .ampsim recebido",
                                    self.requestImport)):
            b = QPushButton(" " + text)
            b.setIcon(icon(ic, C["text"], 15))
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda *_, s=sig: s.emit())
            b.setMinimumWidth(b.sizeHint().width() + 6)      # "Importar" nunca cortado
            row.addWidget(b)
        lay.addLayout(row)
        self.page = "pads"                       # aba aberta lá em cima: "guitar", "bass" ou "pads"
        self.reload()

    def set_page(self, page):
        if page != self.page:
            self.page = page
            self.reload()

    # ------------------------------------------------------------------ conteúdo
    @staticmethod
    def _indent(parent):
        depth = 0
        while parent is not None:
            depth += 1
            parent = parent.parent()
        return "    " * depth

    def _group(self, text, ic=None, parent=None):
        it = QTreeWidgetItem([self._indent(parent) + text])
        f = QFont(self.tree.font())
        f.setBold(True)
        it.setFont(0, f)
        it.setFlags(Qt.ItemIsEnabled)
        if ic:
            it.setIcon(0, icon(ic, C["text"], 16))
        (parent.addChild if parent else self.tree.addTopLevelItem)(it)
        return it

    def _leaf(self, parent, text, data, ic="file"):
        it = QTreeWidgetItem([self._indent(parent) + text])
        it.setData(0, ROLE, data)
        it.setToolTip(0, text)                   # nome inteiro (a lista corta com "…" se for estreita)
        it.setIcon(0, icon(ic, C["dim"], 15, active="#ffffff"))
        parent.addChild(it)
        return it

    def reload(self):
        expanded = {self.tree.topLevelItem(i).text(0).strip() for i in range(self.tree.topLevelItemCount())
                    if self.tree.topLevelItem(i).isExpanded()}
        self.tree.clear()
        page = self.page
        if page == "pads":
            inst = self._group("Instrumentos (Pad/Piano)", "keys")
            mine = storage.list_user_presets("teclas")
            if mine:
                g = self._group("Meus timbres", parent=inst)
                for n in mine:
                    self._leaf(g, n, ("keys_user", n), "music")
            for group, items in READY_GROUPS:
                g = self._group(group, parent=inst)
                for n in items:
                    self._leaf(g, n, ("ready", n), "music")
        for kind, title, ic in TRACK_TITLES:
            if kind != page:
                continue
            g = self._group(title, ic)
            for n in FACTORY.get(kind, {}):
                self._leaf(g, "★ " + n, ("track", (kind, "factory", n)), ic)
            for n in storage.list_user_presets(kind):
                self._leaf(g, n, ("track", (kind, "user", n)), ic)
        if page == "pads":
            g = self._group("Amp e efeitos das teclas", "pads")
            for n in FACTORY.get("pads", {}):
                self._leaf(g, "★ " + n, ("track", ("pads", "factory", n)), "pads")
            for n in storage.list_user_presets("pads"):
                self._leaf(g, n, ("track", ("pads", "user", n)), "pads")
        files = self._group("Meus arquivos (.ampsim)", "folder")
        d = storage.SHARE_DIR
        found = sorted(d.glob("*" + EXTENSION)) if d.is_dir() else []
        found = [f for f in found[:200] if _file_page(f) in (None, page)]
        for f in found:
            self._leaf(files, f.stem, ("file", str(f)), "file")
        if not found:
            hint = QTreeWidgetItem(["    (salve ou receba arquivos em Documentos\\AmpSim)"])
            hint.setFlags(Qt.NoItemFlags)
            files.addChild(hint)
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            top.setExpanded(top.text(0).strip() in expanded if expanded else i == 0)
        self._filter(self.search.text())

    def select(self, data):
        """Destaca o item atual (sem disparar)."""
        def walk(it):
            for j in range(it.childCount()):
                ch = it.child(j)
                if ch.data(0, ROLE) == data:
                    return ch
                found = walk(ch)
                if found is not None:
                    return found
            return None
        root = self.tree.invisibleRootItem()
        it = walk(root)
        self.tree.setCurrentItem(it) if it is not None else self.tree.clearSelection()

    def _filter(self, text):
        text = text.lower().strip()

        def visit(it):
            if it.data(0, ROLE) is not None:
                show = not text or text in it.text(0).lower()
                it.setHidden(not show)
                return show
            any_child = False
            for j in range(it.childCount()):
                any_child = visit(it.child(j)) or any_child
            if it.childCount():
                it.setHidden(bool(text) and not any_child)
                if text and any_child:
                    it.setExpanded(True)
            return any_child
        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            visit(root.child(i))

    # ------------------------------------------------------------------ ações
    def _clicked(self, it, _col=0):
        data = it.data(0, ROLE)
        if data is None:
            it.setExpanded(not it.isExpanded())
            return
        self.activated.emit(data[0], data[1])

    def _menu(self, pos):
        it = self.tree.itemAt(pos)
        data = it.data(0, ROLE) if it is not None else None
        if data is None:
            return
        m = self.context_menu(*data)
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def context_menu(self, kind, arg):
        """Menu do botão direito num preset (separado para dar para testar)."""
        m = QMenu(self)
        m.addAction(icon("play", C["text"], 14), "Carregar tudo", lambda: self.activated.emit(kind, arg))

        def part(text, p, enabled=True):
            a = m.addAction(text, lambda: self.requestPart.emit(kind, arg, p))
            a.setEnabled(enabled)

        if kind in ("ready", "keys_user"):
            sound = READY[arg]["sound1"] if kind == "ready" else ""
            what = f"Timbre “{sound}”" if sound else "Timbre principal"
            m.addSeparator()
            part(f"{what} na L1", "l1")
            part(f"{what} na L2", "l2")
            part(f"{what} numa camada nova (L3/L4)", "new_layer")
            part("Só os efeitos (rotação, drive, delay) na camada selecionada", "fx")
            if sound in CONT_PAD_SOUNDS:
                part(f"Usar “{sound}” no pad contínuo", "cont")
        elif kind == "track" and arg[0] != "vocal":       # a Vocal não tem amp: o preset é um só
            name = arg[0]
            m.addSeparator()
            part("Só o amplificador e o gabinete", "amp")
            part("Só os pedais de efeito", "fx")
            if name in ("guitar", "bass"):
                part("Carregar no Baixo" if name == "guitar" else "Carregar na Guitarra", "other")
        if kind != "file":
            m.addSeparator()
            m.addAction(icon("upload", C["text"], 14), "Exportar para arquivo…",
                        lambda: self.requestExport.emit(kind, arg))
            m.addAction(icon("share", C["text"], 14), "Copiar código para compartilhar",
                        lambda: self.requestShareCode.emit(kind, arg))
        user = kind in ("keys_user", "file") or (kind == "track" and arg[1] == "user")
        if user:
            m.addSeparator()
            m.addAction(icon("delete", C["text"], 14), "Excluir…", lambda: self.requestDelete.emit(kind, arg))
        return m


def _file_page(path):
    """Aba a que um arquivo .ampsim pertence ("guitar", "bass", "pads", "vocal"); None = cena (vale em
    todas)."""
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.loads(f.read(200_001))
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or doc.get("tipo") != "preset":
        return None
    trilha = doc.get("trilha")
    return "pads" if trilha in ("pads", "teclas") else trilha if trilha in ("guitar", "bass", "vocal") else None
