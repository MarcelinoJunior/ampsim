"""Setlist (lateral esquerda, acima do Banco de Presets): as músicas do culto em ordem.

Clique numa música = carrega o som dela. "+ Música" guarda o som de agora com um nome. Arraste para
mudar a ordem. ◀ ▶ (ou Ctrl+PgUp / Ctrl+PgDn, ou um botão do controlador) vão para a anterior/próxima.
"""
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFrame, QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem,
    QMenu, QMessageBox, QPushButton, QVBoxLayout,
)

from .. import setlist
from .icons import icon
from .theme import C


def _tool(ic, tip, slot, text=""):
    b = QPushButton(text)
    b.setIcon(icon(ic, C["text"], 14))
    b.setToolTip(tip)
    b.setFocusPolicy(Qt.NoFocus)
    b.setFixedHeight(26)
    if not text:
        b.setFixedWidth(30)
    b.clicked.connect(lambda *_: slot())
    return b


class SetlistPanel(QFrame):
    foldedChanged = Signal(bool)              # recolheu/expandiu (a subjanela encolhe e devolve o espaço)

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setObjectName("side")
        # subjanela: a largura acompanha o divisor (padrão 242; mínimo = o que cabe sem cortar nada)
        self.data = setlist.load()
        self.current = None                  # índice da música carregada (destacada)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        head = QHBoxLayout()
        hi = QLabel()
        hi.setPixmap(icon("music", C["text"], 18).pixmap(18, 18))
        head.addWidget(hi)
        t = QLabel("Setlist")
        t.setObjectName("h2")
        head.addWidget(t, 1)
        self.head_widgets = (hi, t)           # numa subjanela o título já está na barra dela
        self.more = QPushButton()
        self.more.setIcon(icon("menu", C["text"], 14))
        self.more.setToolTip("Novo setlist, renomear, apagar")
        self.more.setFocusPolicy(Qt.NoFocus)
        self.more.setFixedSize(28, 24)
        self.more.clicked.connect(self._lists_menu)
        head.addWidget(self.more)
        self.fold = QPushButton()
        self.fold.setObjectName("flat")
        self.fold.setFocusPolicy(Qt.NoFocus)
        self.fold.setFixedSize(26, 24)
        self.fold.clicked.connect(lambda *_: self.set_folded(not self.data["recolhido"]))
        head.addWidget(self.fold)
        lay.addLayout(head)

        self.body = QFrame()
        bl = QVBoxLayout(self.body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(6)
        self.lists = QComboBox()
        self.lists.setFocusPolicy(Qt.NoFocus)
        self.lists.setToolTip("Setlist (ex.: um por culto)")
        self.lists.activated.connect(lambda _: self.choose_list(self.lists.currentText()))
        bl.addWidget(self.lists)
        self.songs = QListWidget()
        self.songs.setFocusPolicy(Qt.NoFocus)
        self.songs.setDragDropMode(QAbstractItemView.InternalMove)
        self.songs.setDefaultDropAction(Qt.MoveAction)
        self.songs.setIconSize(QSize(14, 14))
        self.songs.setMinimumHeight(90)       # cresce com a subjanela
        self.songs.setWordWrap(True)          # dica e nomes longos quebram a linha em vez de cortar
        self.songs.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.songs.setToolTip("Clique: carregar o som da música · arraste: mudar a ordem · botão direito: mais")
        self.songs.itemClicked.connect(lambda it: self.load_song(self.songs.row(it)))
        self.songs.model().rowsMoved.connect(lambda *_: self._reordered())
        self.songs.setContextMenuPolicy(Qt.CustomContextMenu)
        self.songs.customContextMenuRequested.connect(self._song_menu)
        bl.addWidget(self.songs)
        row = QHBoxLayout()
        row.setSpacing(4)
        row.addWidget(_tool("left", "Música anterior (Ctrl+PgUp)", lambda: self.step(-1)))
        row.addWidget(_tool("right", "Próxima música (Ctrl+PgDn)", lambda: self.step(1)))
        row.addWidget(_tool("add", "Guardar o som de agora como uma música deste setlist", self.add_song,
                            " Música"), 1)
        bl.addLayout(row)
        lay.addWidget(self.body, 100)
        lay.addStretch(1)                     # recolhido: o título fica em cima
        self.refresh()
        self.set_folded(self.data["recolhido"], save=False)

    # ------------------------------------------------------------------ dados
    def songs_list(self):
        return self.data["listas"][self.data["atual"]]

    def _save(self):
        try:
            setlist.save(self.data)
        except OSError as exc:
            QMessageBox.warning(self, "Setlist", f"Não foi possível salvar o setlist:\n{exc}")

    def refresh(self):
        self.lists.blockSignals(True)
        self.lists.clear()
        self.lists.addItems(list(self.data["listas"]))
        self.lists.setCurrentText(self.data["atual"])
        self.lists.blockSignals(False)
        self.songs.blockSignals(True)
        self.songs.clear()
        songs = self.songs_list()
        for i, s in enumerate(songs):
            tom = s["som"].get("pad_tom")
            it = QListWidgetItem(f"{i + 1}. {s['nome']}" + (f"   · {tom}" if tom else ""))
            if i == self.current:
                f = QFont(self.songs.font())
                f.setBold(True)
                it.setFont(f)
                it.setForeground(Qt.white)
                it.setIcon(icon("play", C["accent"], 14))
            self.songs.addItem(it)
        if not songs:
            it = QListWidgetItem("(guarde o som de agora com “+ Música”)")
            it.setFlags(Qt.NoItemFlags)
            self.songs.addItem(it)
        self.songs.blockSignals(False)

    def set_folded(self, on, save=True):
        self.data["recolhido"] = bool(on)
        self.body.setVisible(not on)
        self.fold.setIcon(icon("down" if on else "up", C["dim"], 14))
        self.fold.setToolTip("Mostrar o setlist" if on else "Recolher o setlist")
        self.foldedChanged.emit(bool(on))
        if save:
            self._save()

    # ------------------------------------------------------------------ músicas
    def add_song(self, name=None):
        if name is None:
            n = len(self.songs_list()) + 1
            name, ok = QInputDialog.getText(self, "Nova música", "Nome da música (o som de agora fica guardado nela):",
                                            text=f"Música {n}")
            if not ok or not name.strip():
                return None
        songs = self.songs_list()
        if len(songs) >= setlist.MAX_SONGS:
            return None
        songs.append({"nome": name.strip()[:60], "som": setlist.capture(self.win)})
        self.current = len(songs) - 1
        self._save()
        self.refresh()
        return self.current

    def load_song(self, i):
        songs = self.songs_list()
        if not 0 <= i < len(songs):
            return False
        setlist.apply(self.win, songs[i]["som"])
        self.current = i
        self.refresh()
        self.win.refresh_sounds()
        self.win.flash_status(f"Música {i + 1}: {songs[i]['nome']}", 4000)
        return True

    def step(self, d):
        songs = self.songs_list()
        if not songs:
            return False
        i = 0 if self.current is None else (self.current + d) % len(songs)
        return self.load_song(i)

    def update_song(self, i):
        self.songs_list()[i]["som"] = setlist.capture(self.win)
        self.current = i
        self._save()
        self.refresh()

    def rename_song(self, i, name=None):
        songs = self.songs_list()
        if name is None:
            name, ok = QInputDialog.getText(self, "Renomear música", "Nome:", text=songs[i]["nome"])
            if not ok:
                return
        if name.strip():
            songs[i]["nome"] = name.strip()[:60]
            self._save()
            self.refresh()

    def remove_song(self, i, ask=True):
        songs = self.songs_list()
        if ask and QMessageBox.question(self, "Remover música",
                                        f"Remover “{songs[i]['nome']}” deste setlist?") != QMessageBox.Yes:
            return
        songs.pop(i)
        if self.current is not None:
            self.current = None if self.current == i else self.current - (self.current > i)
        self._save()
        self.refresh()

    def _reordered(self):
        """Arrastou na lista: refaz a ordem pelo texto "n. nome" de cada linha."""
        songs = self.songs_list()
        order = []
        for r in range(self.songs.count()):
            text = self.songs.item(r).text()
            try:
                order.append(int(text.split(".", 1)[0]) - 1)
            except ValueError:
                return
        if sorted(order) != list(range(len(songs))):
            return
        cur = songs[self.current] if self.current is not None else None
        self.data["listas"][self.data["atual"]] = [songs[j] for j in order]
        self.current = self.songs_list().index(cur) if cur is not None else None
        self._save()
        self.refresh()

    def _song_menu(self, pos):
        it = self.songs.itemAt(pos)
        if it is None or not it.flags() & Qt.ItemIsEnabled:
            return
        i = self.songs.row(it)
        m = QMenu(self)
        m.addAction(icon("play", C["text"], 14), "Carregar", lambda: self.load_song(i))
        m.addAction(icon("save", C["text"], 14), "Guardar o som de agora nesta música", lambda: self.update_song(i))
        m.addAction(icon("file", C["text"], 14), "Renomear…", lambda: self.rename_song(i))
        m.addSeparator()
        m.addAction(icon("delete", C["text"], 14), "Remover do setlist…", lambda: self.remove_song(i))
        m.exec(self.songs.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------ setlists
    def choose_list(self, name):
        if name in self.data["listas"]:
            self.data["atual"] = name
            self.current = None
            self._save()
            self.refresh()

    def new_list(self, name=None):
        if name is None:
            name, ok = QInputDialog.getText(self, "Novo setlist", "Nome (ex.: Culto de domingo):")
            if not ok:
                return None
        name = (name or "").strip()[:60]
        if not name or name in self.data["listas"]:
            return None
        self.data["listas"][name] = []
        self.choose_list(name)
        return name

    def rename_list(self, name=None):
        old = self.data["atual"]
        if name is None:
            name, ok = QInputDialog.getText(self, "Renomear setlist", "Nome:", text=old)
            if not ok:
                return
        name = name.strip()[:60]
        if not name or name in self.data["listas"]:
            return
        self.data["listas"] = {(name if k == old else k): v for k, v in self.data["listas"].items()}
        self.data["atual"] = name
        self._save()
        self.refresh()

    def delete_list(self, ask=True):
        if len(self.data["listas"]) <= 1:
            QMessageBox.information(self, "Setlist", "É o único setlist: crie outro antes de apagar este.")
            return
        name = self.data["atual"]
        if ask and QMessageBox.question(self, "Apagar setlist", f"Apagar o setlist “{name}” inteiro?") != QMessageBox.Yes:
            return
        del self.data["listas"][name]
        self.data["atual"] = next(iter(self.data["listas"]))
        self.current = None
        self._save()
        self.refresh()

    def _lists_menu(self):
        m = QMenu(self)
        m.addAction(icon("add", C["text"], 14), "Novo setlist…", lambda: self.new_list())
        m.addAction(icon("file", C["text"], 14), "Renomear este setlist…", lambda: self.rename_list())
        m.addSeparator()
        m.addAction(icon("delete", C["text"], 14), "Apagar este setlist…", lambda: self.delete_list())
        m.exec(self.more.mapToGlobal(self.more.rect().bottomLeft()))
