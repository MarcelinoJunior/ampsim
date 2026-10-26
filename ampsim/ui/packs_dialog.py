"""Tela "Timbres adicionais": baixar ou remover os pacotes de pianos gravados (audio/packs.py)."""
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QGridLayout, QLabel, QMessageBox, QProgressBar, QPushButton,
    QVBoxLayout,
)

from ..audio import packs
from ..audio.soundfont import available
from .theme import C


class _Signals(QObject):
    progress = Signal(str, int, int, str)       # pacote, feito, total, fase
    done = Signal(str, str)                      # pacote, erro ("" = deu certo)


class PacksDialog(QDialog):
    def __init__(self, win, parent=None):
        super().__init__(parent or win)
        self.win = win
        self.inst = win.engine.instruments
        self.setWindowTitle("Timbres adicionais")
        self.resize(640, 520)
        self.sig = _Signals()
        self.sig.progress.connect(self._progress)
        self.sig.done.connect(self._done)
        self.busy = None
        self._cancel = False
        self.queue = []                              # (pacote, arquivo já baixado) a instalar em seguida
        lay = QVBoxLayout(self)
        intro = QLabel("Pianos gravados de instrumentos de verdade. Baixe só os que quiser: ficam no seu "
                       "computador e aparecem na lista de timbres (categoria Pianos).")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        base = QLabel(("✓ Pacote básico instalado (timbres GM, motores e capturas de amplificador)."
                       if available() else
                       "⚠ Pacote básico não instalado: rode instalar.bat (ou tools\\baixar_extras.py) uma vez."))
        base.setObjectName("small")
        base.setStyleSheet(f"color: {C['green'] if available() else C['yellow']};")
        lay.addWidget(base)
        self.rows = {}
        for p in packs.PACKS:
            card = QFrame()
            card.setObjectName("card")
            g = QGridLayout(card)
            g.setContentsMargins(10, 8, 10, 8)
            title = QLabel(f"<b>{p.nome}</b>")
            g.addWidget(title, 0, 0)
            desc = QLabel(p.descricao)
            desc.setWordWrap(True)
            desc.setObjectName("small")
            g.addWidget(desc, 1, 0)
            info = QLabel(f"{p.licenca} · download {p.download_mb} MB · ocupa {p.disco_mb} MB")
            info.setObjectName("small")
            info.setStyleSheet(f"color: {C['dim']};")
            g.addWidget(info, 2, 0)
            status = QLabel("")
            status.setObjectName("small")
            g.addWidget(status, 3, 0)
            bar = QProgressBar()
            bar.setVisible(False)
            bar.setTextVisible(True)
            g.addWidget(bar, 4, 0, 1, 2)
            btn = QPushButton("")
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setMinimumWidth(110)
            btn.clicked.connect(lambda _, p=p: self.toggle(p))
            g.addWidget(btn, 0, 1, 4, 1, Qt.AlignVCenter)
            g.setColumnStretch(0, 1)
            lay.addWidget(card)
            self.rows[p.id] = (status, bar, btn)
        lay.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Close).clicked.connect(self.reject)
        lay.addWidget(buttons)
        self.refresh()

    def refresh(self):
        for p in packs.PACKS:
            status, bar, btn = self.rows[p.id]
            ok = packs.sf2_path(p) is not None
            if self.busy == p.id:
                btn.setText("Cancelar")
                btn.setEnabled(True)
                continue
            status.setText("✓ Instalado: escolha o timbre “" + p.sound + "” nas camadas" if ok else "Não instalado")
            status.setStyleSheet(f"color: {C['green'] if ok else C['dim']};")
            btn.setText("Remover" if ok else "Baixar")
            btn.setObjectName("" if ok else "primary")
            btn.setStyle(btn.style())
            btn.setEnabled(self.busy is None)
            bar.setVisible(False)

    def toggle(self, p):
        if self.busy == p.id:
            self._cancel = True
            return
        if packs.sf2_path(p) is not None:
            if QMessageBox.question(self, "Remover", f"Remover “{p.nome}” do computador?") == QMessageBox.Yes:
                packs.remove(p)
                self.refresh()
            return
        self.download(p)

    def download(self, p, source=None, wait=False):
        """Baixa e instala em segundo plano (o áudio continua tocando)."""
        self.busy = p.id
        self._cancel = False
        status, bar, _ = self.rows[p.id]
        status.setText("Baixando…")
        bar.setVisible(True)
        bar.setRange(0, 0)
        self.refresh()

        def work():
            try:
                packs.install(p, progress=lambda d, t, ph: self.sig.progress.emit(p.id, d, t, ph),
                              cancel=lambda: self._cancel, source=source)
                self.sig.done.emit(p.id, "")
            except packs.PackError as exc:
                self.sig.done.emit(p.id, str(exc))
        t = threading.Thread(target=work, daemon=True)
        t.start()
        if wait:
            t.join()
        return t

    def _progress(self, pid, done, total, phase):
        status, bar, _ = self.rows[pid]
        if phase == "baixando" and total:
            bar.setRange(0, 100)
            bar.setValue(int(done * 100 / total))
            status.setText(f"Baixando… {done / 1e6:.0f} de {total / 1e6:.0f} MB")
        else:
            bar.setRange(0, 0)
            status.setText("Instalando…")

    def install_many(self, items):
        """Instala, um de cada vez, os pacotes que o instalador já baixou [(pacote, arquivo)]."""
        self.queue = list(items)
        self._next()

    def _next(self):
        if self.queue and self.busy is None:
            p, src = self.queue.pop(0)
            self._source = src
            self.download(p, source=src)

    def _done(self, pid, error):
        self.busy = None
        p = packs.PACK_BY_ID[pid]
        src = getattr(self, "_source", None)
        self._source = None
        if error:
            self.refresh()
            status, _, _ = self.rows[pid]
            status.setText("Erro: " + error)
            status.setStyleSheet(f"color: {C['red']};")
            self._next()
            return
        if src is not None and src.parent.name in ("_instalar", "_timbres"):
            try:
                src.unlink()                         # arquivo baixado pelo instalador: já foi usado
            except OSError:
                pass
        if self.inst.sf is not None:
            self.inst.sf.load_font(pid, packs.sf2_path(p))
            self.inst.apply_all()
        self.refresh()
        self.win.refresh_sounds()
        self._next()
