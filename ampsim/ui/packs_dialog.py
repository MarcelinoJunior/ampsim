"""Tela "Downloads: timbres e plugins": baixar ou remover os pianos gravados e os plugins VST3 gratuitos
(audio/packs.py)."""
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QGridLayout, QLabel, QMessageBox, QProgressBar, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from ..audio import packs, vst
from ..audio.soundfont import available
from .theme import C

TITLE = "Downloads: timbres e plugins"


class _Signals(QObject):
    progress = Signal(str, int, int, str)       # pacote, feito, total, fase
    done = Signal(str, str)                      # pacote, erro ("" = deu certo)


def _section(text):
    lab = QLabel(f"<b>{text}</b>")
    lab.setContentsMargins(0, 8, 0, 0)
    return lab


class PacksDialog(QDialog):
    def __init__(self, win, parent=None):
        super().__init__(parent or win)
        self.win = win
        self.inst = win.engine.instruments
        self.setWindowTitle(TITLE)
        self.resize(660, 640)
        self.sig = _Signals(self)
        self.sig.progress.connect(self._progress)
        self.sig.done.connect(self._done)
        self.busy = None
        self._cancel = False
        self._source = None
        self.queue = []                              # (pacote, arquivo já baixado) a instalar em seguida
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 6, 0)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        lay.addWidget(_section("Pianos gravados"))
        intro = QLabel("Pianos gravados de instrumentos de verdade. Baixe só os que quiser: ficam no seu "
                       "computador e aparecem na lista de timbres (categoria Pianos).")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        base = QLabel(("✓ Pacote básico instalado (timbres GM, motores e capturas de amplificador)."
                       if available() else
                       "⚠ Pacote básico não instalado: rode instalar.bat (ou tools\\baixar_extras.py) uma vez."))
        base.setObjectName("small")
        base.setWordWrap(True)
        base.setStyleSheet(f"color: {C['green'] if available() else C['yellow']};")
        lay.addWidget(base)
        self.rows = {}
        for p in packs.PACKS:
            lay.addWidget(self._card(p, f"{p.licenca} · download {p.download_mb} MB · ocupa {p.disco_mb} MB"))

        lay.addWidget(_section("Plugins de efeito (VST3)"))
        pintro = QLabel("Plugins gratuitos para usar no slot “Plugin” das camadas do teclado (L1–L4) e do "
                        "Master, e nas trilhas Guitarra/Baixo. Ficam na pasta de plugins do seu usuário "
                        f"({vst.user_vst3_dir()}), que outros programas de áudio também enxergam.")
        pintro.setWordWrap(True)
        lay.addWidget(pintro)
        if not vst.available():
            warn = QLabel("⚠ O módulo de plugins (pedalboard) não está instalado: os plugins baixados não "
                          "vão funcionar até instalar o AmpSim de novo.")
            warn.setWordWrap(True)
            warn.setObjectName("small")
            warn.setStyleSheet(f"color: {C['yellow']};")
            lay.addWidget(warn)
        for p in packs.PLUGIN_PACKS:
            info = f"{p.licenca} · download {p.download_mb} MB · ocupa {p.disco_mb} MB"
            if p.site:
                info += f" · <a href='{p.site}' style='color:{C['dim']}'>site do plugin</a>"
            lay.addWidget(self._card(p, info))
        lay.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Close).clicked.connect(self.reject)
        outer.addWidget(buttons)
        self.refresh()

    def _card(self, p, info_text):
        card = QFrame()
        card.setObjectName("card")
        g = QGridLayout(card)
        g.setContentsMargins(10, 8, 10, 8)
        g.addWidget(QLabel(f"<b>{p.nome}</b>"), 0, 0)
        desc = QLabel(p.descricao)
        desc.setWordWrap(True)
        desc.setObjectName("small")
        g.addWidget(desc, 1, 0)
        info = QLabel(info_text)
        info.setObjectName("small")
        info.setWordWrap(True)
        info.setOpenExternalLinks(True)
        info.setStyleSheet(f"color: {C['dim']};")
        g.addWidget(info, 2, 0)
        status = QLabel("")
        status.setObjectName("small")
        status.setWordWrap(True)
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
        self.rows[p.id] = (status, bar, btn)
        return card

    @staticmethod
    def _is_plugin(p):
        return isinstance(p, packs.PluginPack)

    def _pack(self, pid):
        return packs.PACK_BY_ID.get(pid) or packs.PLUGIN_PACK_BY_ID[pid]

    def _state(self, p):
        """(instalado, dá para remover por aqui, texto do status)."""
        if self._is_plugin(p):
            ok = packs.plugin_installed(p)
            removable = packs.plugin_removable(p)
            if ok:
                names = ", ".join(vst.display_name(b) for b in p.bundles)
                where = "" if removable else " (instalado por outro programa)"
                return True, removable, f"✓ Instalado{where}: escolha {names} no slot “Plugin”"
            return False, removable, "Não instalado"
        ok = packs.sf2_path(p) is not None
        return ok, ok, ("✓ Instalado: escolha o timbre “" + p.sound + "” nas camadas" if ok else "Não instalado")

    def refresh(self):
        for p in list(packs.PACKS) + list(packs.PLUGIN_PACKS):
            status, bar, btn = self.rows[p.id]
            if self.busy == p.id:
                btn.setText("Cancelar")
                btn.setEnabled(True)
                continue
            ok, removable, text = self._state(p)
            status.setText(text)
            status.setStyleSheet(f"color: {C['green'] if ok else C['dim']};")
            btn.setText("Remover" if removable else "Baixar")
            btn.setObjectName("" if removable else "primary")
            btn.setStyle(btn.style())
            btn.setEnabled(self.busy is None and (removable or not ok))
            bar.setVisible(False)

    def toggle(self, p):
        if self.busy == p.id:
            self._cancel = True
            return
        ok, removable, _ = self._state(p)
        if removable:
            if QMessageBox.question(self, "Remover", f"Remover “{p.nome}” do computador?") == QMessageBox.Yes:
                if self._is_plugin(p):
                    try:
                        packs.remove_plugin_pack(p)
                    except packs.PackError as exc:
                        QMessageBox.warning(self, "Remover", str(exc))
                    self._plugins_changed()
                else:
                    packs.remove(p)
                self.refresh()
            return
        if not ok:
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
        install = packs.install_plugin_pack if self._is_plugin(p) else packs.install

        def work():
            try:
                install(p, progress=lambda d, t, ph: self.sig.progress.emit(p.id, d, t, ph),
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

    def _plugins_changed(self):
        """Avisa a janela para recarregar as listas de plugins dos slots (se ela souber)."""
        fn = getattr(self.win, "refresh_plugins", None)
        if callable(fn):
            fn()

    def _done(self, pid, error):
        self.busy = None
        p = self._pack(pid)
        src = self._source
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
        if self._is_plugin(p):
            self._plugins_changed()
        else:
            if self.inst.sf is not None:
                self.inst.sf.load_font(pid, packs.sf2_path(p))
                self.inst.apply_all()
            self.win.refresh_sounds()
        self.refresh()
        self._next()
