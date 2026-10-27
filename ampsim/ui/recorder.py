"""Gravador da aba Faders / Pads: REC/STOP, banco de gravações e "pôr no pad"."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QListWidget, QMenu, QMessageBox, QPushButton, QVBoxLayout,
    QWidget,
)

from ..audio import sampler as smp
from ..audio.sampler import MAX_SECONDS, REC_PREFIX
from ..instruments import PAD_COUNT, PAD_PRESETS
from .icons import icon
from .theme import C

REC_IDLE = (f"QPushButton {{ background: #3a1820; border: 1px solid #6b2632; color: #ff9aa5; font-weight: 800; }}"
            f"QPushButton:hover {{ background: #5a1e2a; }}"
            f"QPushButton:disabled {{ background: {C['card']}; color: {C['faint']}; border-color: {C['border']}; }}")
REC_ON = (f"QPushButton {{ background: {C['red']}; border: 1px solid #ff8a96; color: white; font-weight: 800; }}")


def pad_label(name):
    """Texto curto do som de um pad (gravação aparece como "● nome")."""
    if name.startswith(REC_PREFIX):
        return "● " + name[len(REC_PREFIX):]
    return name.split(" — ")[0]


class RecorderPanel(QWidget):
    def __init__(self, win, parent=None):
        super().__init__(parent)
        self.win = win
        self.engine = win.engine
        self.inst = win.engine.instruments
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        row = QHBoxLayout()
        row.setSpacing(4)
        self.source = QComboBox()
        self.source.setFocusPolicy(Qt.NoFocus)
        self.source.setToolTip("O que o REC grava: o som do AmpSim (o que você toca) ou uma entrada da placa")
        row.addWidget(self.source, 1)
        self.rec_btn = QPushButton("● REC")
        self.rec_btn.setFocusPolicy(Qt.NoFocus)
        self.rec_btn.setFixedSize(84, 26)
        self.rec_btn.setStyleSheet(REC_IDLE)
        self.rec_btn.setToolTip(f"Começa a gravar (até {MAX_SECONDS} s). O silêncio do começo e do fim é cortado.")
        self.rec_btn.clicked.connect(self.start)
        row.addWidget(self.rec_btn)
        self.stop_btn = QPushButton("■ STOP")
        self.stop_btn.setFocusPolicy(Qt.NoFocus)
        self.stop_btn.setFixedSize(70, 26)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setToolTip("Para a gravação e guarda no banco (ou para a gravação que está em loop)")
        self.stop_btn.clicked.connect(self.stop)
        row.addWidget(self.stop_btn)
        self.time = QLabel("")
        self.time.setObjectName("small")
        self.time.setFixedWidth(64)
        row.addWidget(self.time)
        lay.addLayout(row)

        row = QHBoxLayout()
        row.setSpacing(4)
        self.bank = QListWidget()
        self.bank.setFocusPolicy(Qt.NoFocus)
        self.bank.setToolTip("Banco de gravações (duplo-clique: ouvir)")
        self.bank.setStyleSheet("QListWidget { font-size: 9pt; } QListWidget::item { padding: 1px 4px; }")
        self.bank.itemDoubleClicked.connect(lambda *_: self.preview())
        self.bank.currentRowChanged.connect(lambda *_: self._enable())
        row.addWidget(self.bank, 1)
        col = QGridLayout()
        col.setSpacing(3)
        self.play_btn = self._small_button(" Ouvir", "play", self.preview)
        self.assign_btn = self._small_button(" Pôr no pad", "pads", self.assign_menu)
        self.rename_btn = self._small_button(" Renomear", "file", self.rename)
        self.delete_btn = self._small_button(" Apagar", "delete", self.delete)
        for k, b in enumerate((self.play_btn, self.assign_btn, self.rename_btn, self.delete_btn)):
            col.addWidget(b, k // 2, k % 2)
        col.setRowStretch(2, 1)
        row.addLayout(col)
        lay.addLayout(row, 1)

        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._tick)
        self._recording = False
        self._quiet = False                 # gravação pedida pela tela remota: nada de janela no PC
        self.on_auto_stop = None            # (nome ou None) quando para sozinho no limite de tempo
        # gravação em loop (PLAY duas vezes na tela remota): aparece aqui e o STOP para
        self.loop_timer = QTimer(self)
        self.loop_timer.setInterval(250)
        self.loop_timer.timeout.connect(self._loop_tick)
        self.loop_timer.start()
        self.load_bank()

    def _small_button(self, text, ic, slot):
        b = QPushButton(text)
        b.setIcon(icon(ic, C["text"], 13))
        b.setFocusPolicy(Qt.NoFocus)
        b.setFixedHeight(26)
        b.clicked.connect(lambda *_: slot())
        return b

    # ------------------------------------------------------------------ banco
    def load_bank(self):
        """Lê as gravações da pasta para o tocador e para a lista (no início do programa)."""
        for name in smp.list_recordings():
            got = smp.load_recording(name)
            if got is not None:
                self.engine.sampler.put(name, *got)
        self.refresh()

    def refresh(self):
        cur = self.current()
        self.bank.clear()
        names = smp.list_recordings()
        self.bank.addItems(names)
        if not names:
            self.bank.addItem("(nenhuma gravação ainda)")
            self.bank.item(0).setFlags(Qt.NoItemFlags)
        elif cur in names:
            self.bank.setCurrentRow(names.index(cur))
        self._sources()
        self._enable()

    def _sources(self):
        keep = self.source.currentData()
        self.source.blockSignals(True)
        self.source.clear()
        self.source.addItem("Som do AmpSim", "out")
        for c in range(self.engine.n_in if self.engine.running else 0):
            self.source.addItem(f"Entrada {c + 1} da placa", c)
        if self.source.count() == 1:
            self.source.addItem("Entrada da placa (nenhuma ligada)", None)
            self.source.model().item(1).setEnabled(False)
        i = self.source.findData(keep) if keep is not None else 0
        self.source.setCurrentIndex(max(0, i))
        self.source.blockSignals(False)

    def current(self):
        it = self.bank.currentItem()
        return it.text() if it is not None and it.flags() & Qt.ItemIsEnabled else None

    def _enable(self):
        has = self.current() is not None
        for b in (self.play_btn, self.assign_btn, self.rename_btn, self.delete_btn):
            b.setEnabled(has)

    # ------------------------------------------------------------------ gravar
    def start(self, quiet=False):
        """quiet: pedido da tela remota (sem janela no PC). -> "" ou o motivo de não gravar."""
        if self.engine.recorder.active:
            return ""
        if not self.engine.running:
            if not quiet:
                QMessageBox.information(self, "Gravador", "Ligue o áudio primeiro (botão “Áudio” lá em cima).")
            return "O áudio do AmpSim está desligado"
        src = self.source.currentData()
        if src is None:
            return "Escolha a fonte do gravador no AmpSim"
        self.engine.recorder.start(self.engine.fs, src)
        self._recording = True
        self._quiet = bool(quiet)
        self.rec_btn.setText("● GRAVANDO")
        self.rec_btn.setStyleSheet(REC_ON)
        self.rec_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.source.setEnabled(False)
        self.timer.start()
        self._tick()
        return ""

    def _tick(self):
        r = self.engine.recorder
        self.time.setText(f"{r.seconds:4.1f} s")
        if not r.active and self._recording:                    # chegou nos 60 s: guarda sozinho
            name = self.stop(quiet=self._quiet)
            if self.on_auto_stop is not None:
                self.on_auto_stop(name)

    def _loop_tick(self):
        if self._recording:
            return
        name = self.engine.sampler.looping
        self.stop_btn.setEnabled(bool(name))
        if name:
            self.time.setText("⟳ loop")
            self.time.setToolTip(f"Repetindo “{name}” até o STOP")
        elif self.time.text() == "⟳ loop":
            self.time.setText("")
            self.time.setToolTip("")

    def stop(self, quiet=False):
        r = self.engine.recorder
        if not r.active and not self._recording:
            if self.engine.sampler.looping:                     # STOP com uma gravação em loop: para ela
                self.engine.sampler.stop_all()
                self._loop_tick()
            return None
        self._recording = False
        fs = r.fs
        data = r.stop()
        self.timer.stop()
        self.rec_btn.setText("● REC")
        self.rec_btn.setStyleSheet(REC_IDLE)
        self.rec_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.source.setEnabled(True)
        if len(data) == 0:
            self.time.setText("silêncio")
            if not quiet:
                QMessageBox.information(self, "Gravador", "Nada foi gravado: só chegou silêncio.\n"
                                        "Confira a fonte escolhida ao lado do REC.")
            return None
        name = smp.save_recording(data, fs)
        self.engine.sampler.put(name, data, fs)
        self.time.setText(f"{len(data) / fs:4.1f} s")
        self.refresh()
        self.bank.setCurrentRow(smp.list_recordings().index(name))
        return name

    # ------------------------------------------------------------------ usar
    def preview(self, name=None):
        name = name or self.current()
        if name:
            self.engine.sampler.trigger(name, 110)

    def assign_menu(self):
        name = self.current()
        if not name:
            return
        menu = QMenu(self)
        for i in range(PAD_COUNT):
            menu.addAction(f"Pad {i + 1}   (agora: {pad_label(self.inst.pad_sounds[i])})",
                           lambda i=i: self.assign(i, name))
        menu.exec(self.assign_btn.mapToGlobal(self.assign_btn.rect().bottomLeft()))

    def assign(self, pad, name):
        self.inst.set_pad_sound(pad, REC_PREFIX + name)
        self.win.refresh_sounds()

    def rename(self):
        old = self.current()
        if not old:
            return
        new, ok = QInputDialog.getText(self, "Renomear gravação", "Nome:", text=old)
        if not ok:
            return
        new = smp.rename_recording(old, new)
        if new is None:
            QMessageBox.information(self, "Renomear", "Nome vazio ou já usado por outra gravação.")
            return
        got = self.engine.sampler.raw.get(old)
        self.engine.sampler.remove(old)
        if got is not None:
            self.engine.sampler.put(new, *got)
        self.inst.pad_sounds = [REC_PREFIX + new if s == REC_PREFIX + old else s for s in self.inst.pad_sounds]
        self.refresh()
        self.bank.setCurrentRow(smp.list_recordings().index(new))
        self.win.refresh_sounds()

    def delete(self):
        name = self.current()
        if not name:
            return
        used = [i + 1 for i, s in enumerate(self.inst.pad_sounds) if s == REC_PREFIX + name]
        msg = f"Apagar a gravação “{name}”?"
        if used:
            msg += f"\n\nEla está no(s) pad(s) {', '.join(map(str, used))}: eles voltam para o som padrão."
        if QMessageBox.question(self, "Apagar gravação", msg) != QMessageBox.Yes:
            return
        smp.delete_recording(name)
        self.engine.sampler.remove(name)
        default = list(PAD_PRESETS.values())[0]
        for i in range(PAD_COUNT):
            if self.inst.pad_sounds[i] == REC_PREFIX + name:
                self.inst.set_pad_sound(i, default[i])
        self.refresh()
        self.win.refresh_sounds()
