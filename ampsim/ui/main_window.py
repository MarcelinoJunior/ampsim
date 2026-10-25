"""Janela principal."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton,
    QSizePolicy, QTabWidget, QVBoxLayout, QWidget,
)

from .. import storage
from ..audio import devices as dev
from ..audio.engine import TRACKS
from ..dsp.params import Param
from ..midi import winmm
from ..presets import DEFAULT_PRESET, FACTORY
from .audio_dialog import AudioDialog
from .keyboard import PcKeyboard
from .keys_page import InstrumentBridge
from .panels import TrackPage
from .widgets import Knob, Meter, PianoWidget

ACCENTS = {"guitar": "#e8a33d", "bass": "#4fb3a9", "pads": "#9b7bff"}
TITLES = {"guitar": "Guitarra", "bass": "Baixo", "pads": "Teclas && Pads"}
NO_MIDI = "(nenhum)"


class MainWindow(QMainWindow):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.setWindowTitle("AmpSim — Guitarra · Baixo · Teclas & Pads")
        self.resize(1400, 900)

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)
        root.addWidget(self._build_topbar())
        self.tabs = QTabWidget()
        self.tabs.setFocusPolicy(Qt.NoFocus)
        self.pages = {}
        for name in TRACKS:
            page = TrackPage(name, engine, ACCENTS[name])
            self.pages[name] = page
            self.tabs.addTab(page, TITLES[name])
        root.addWidget(self.tabs, 1)
        root.addWidget(self._build_keyboard_bar())
        self.setCentralWidget(central)

        self.kbd = PcKeyboard(self)
        self.kbd.noteOn.connect(self._note_on)
        self.kbd.noteOff.connect(self._note_off)
        self.kbd.changed.connect(self._update_kbd_label)

        # avisos do roteador de teclas/pads (podem vir da thread de MIDI) -> interface
        inst = engine.instruments
        self.inst_bridge = InstrumentBridge()
        kv = self.pages["pads"].keys_view
        self.inst_bridge.pad.connect(lambda i, v: kv.ctrl.flash_pad(i))
        self.inst_bridge.key.connect(self._show_key)
        self.inst_bridge.knob.connect(lambda i, v: kv.ctrl.set_knob(i, v))
        self.inst_bridge.changed.connect(kv.refresh)
        self.inst_bridge.learn.connect(kv.refresh)
        inst.on_pad = self.inst_bridge.pad.emit
        inst.on_key = self.inst_bridge.key.emit
        inst.on_knob = self.inst_bridge.knob.emit
        inst.on_change = self.inst_bridge.changed.emit
        inst.on_learn = self.inst_bridge.learn.emit
        self.tabs.currentChanged.connect(self._tab_changed)
        self.midi = winmm.MidiInput(inst.handle_midi) if winmm.available else None

        self._restore_state()
        self._update_kbd_label()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(33)

    # ------------------------------------------------------------------ construção
    def _build_topbar(self):
        bar = QFrame()
        bar.setObjectName("topbar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 2, 8, 2)
        title = QLabel("AmpSim")
        title.setObjectName("apptitle")
        lay.addWidget(title)
        lay.addSpacing(12)
        self.power = QPushButton("▶ Ligar áudio")
        self.power.setCheckable(True)
        self.power.setFocusPolicy(Qt.NoFocus)
        self.power.setObjectName("power")
        self.power.clicked.connect(self._toggle_power)
        lay.addWidget(self.power)
        cfg_btn = QPushButton("⚙ Áudio…")
        cfg_btn.setFocusPolicy(Qt.NoFocus)
        cfg_btn.clicked.connect(self._open_audio_dialog)
        lay.addWidget(cfg_btn)
        lay.addSpacing(10)
        self.status = QLabel("Áudio desligado")
        self.status.setObjectName("status")
        lay.addWidget(self.status, 1)
        self.cpu = QLabel("")
        self.cpu.setObjectName("small")
        lay.addWidget(self.cpu)
        lay.addSpacing(10)
        self.master_knob = Knob(Param("master", "Master", -40, 6, 0, "dB"), "#e5e5e5", size="mini")
        self.master_knob.valueChanged.connect(self._set_master)
        lay.addWidget(self.master_knob)
        self.m_master = Meter(horizontal=True)
        lay.addWidget(self.m_master)
        lay.addSpacing(10)
        quit_btn = QPushButton("⏻ Sair")
        quit_btn.setObjectName("quit")
        quit_btn.setToolTip("Salva a sessão, desliga o áudio e fecha o AmpSim")
        quit_btn.setFocusPolicy(Qt.NoFocus)
        quit_btn.clicked.connect(self.close)
        lay.addWidget(quit_btn)
        return bar

    def _build_keyboard_bar(self):
        box = QFrame()
        box.setObjectName("kbdbar")
        self.kbd_box = box
        box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(8, 4, 8, 6)
        row = QHBoxLayout()
        self.kbd_enable = QCheckBox("Teclado do PC toca os pads")
        self.kbd_enable.setChecked(True)
        self.kbd_enable.setFocusPolicy(Qt.NoFocus)
        self.kbd_enable.toggled.connect(self._kbd_toggled)
        row.addWidget(self.kbd_enable)
        self.kbd_label = QLabel("")
        self.kbd_label.setObjectName("small")
        row.addWidget(self.kbd_label)
        row.addStretch(1)
        row.addWidget(QLabel("MIDI:"))
        self.midi_combo = QComboBox()
        self.midi_combo.setFocusPolicy(Qt.NoFocus)
        self.midi_combo.setMinimumWidth(200)
        self.midi_combo.activated.connect(lambda _: self._open_midi(self.midi_combo.currentText()))
        row.addWidget(self.midi_combo)
        rescan = QPushButton("↻")
        rescan.setToolTip("Procurar dispositivos MIDI")
        rescan.setFocusPolicy(Qt.NoFocus)
        rescan.clicked.connect(self._reload_midi)
        row.addWidget(rescan)
        panic = QPushButton("Pânico (soltar notas)")
        panic.setFocusPolicy(Qt.NoFocus)
        panic.clicked.connect(self._panic)
        row.addWidget(panic)
        lay.addLayout(row)
        self.piano = PianoWidget(24, 108)
        self.piano.setFixedHeight(62)
        self.piano.noteOn.connect(self._note_on)
        self.piano.noteOff.connect(self._note_off)
        lay.addWidget(self.piano)
        return box

    # ------------------------------------------------------------------ notas
    def _note_on(self, note, vel):
        self.engine.instruments.key_on(note, vel)

    def _note_off(self, note):
        self.engine.instruments.key_off(note)

    def _show_key(self, note, on):
        self.piano.set_active(note, on)
        self.pages["pads"].keys_view.ctrl.set_key(note, on)

    def _tab_changed(self, index):
        # na aba Teclas & Pads o controlador desenhado já tem teclado: esconde o piano de baixo
        self.piano.setVisible(self.tabs.widget(index) is not self.pages["pads"])
        lay = self.kbd_box.layout()
        lay.invalidate()
        lay.activate()
        self.kbd_box.setMaximumHeight(lay.sizeHint().height())

    def _panic(self):
        self.kbd.release_all()
        self.engine.instruments.all_off()
        self.piano.clear()

    def _kbd_toggled(self, on):
        self.kbd.release_all()
        self.kbd.enabled = on
        self._update_kbd_label()

    def _update_kbd_label(self):
        if not self.kbd.enabled:
            self.kbd_label.setText("")
            self.piano.marker_low = None
        else:
            self.kbd_label.setText(f"Oitava C{self.kbd.octave} (Z/X) · Velocidade {self.kbd.velocity} (C/V) · "
                                   "Teclas: A W S E D F T G Y H U J K O L P Ç")
            self.piano.marker_low = self.kbd.base_note
        self.piano.update()

    # ------------------------------------------------------------------ MIDI
    def _reload_midi(self):
        current = self.midi.name if self.midi else None
        self.midi_combo.clear()
        self.midi_combo.addItem(NO_MIDI)
        self.midi_combo.addItems(winmm.list_inputs())
        if current:
            self.midi_combo.setCurrentText(current)

    def _open_midi(self, name):
        if self.midi is None:
            return
        self.midi.close()
        if name and name != NO_MIDI:
            try:
                self.midi.open(name)
            except RuntimeError as exc:
                QMessageBox.warning(self, "MIDI", str(exc))
                self.midi_combo.setCurrentText(NO_MIDI)

    # ------------------------------------------------------------------ áudio
    def _set_master(self, v):
        self.engine.master = 10 ** (v / 20) if v > -39.9 else 0.0

    def _toggle_power(self, on):
        if on:
            self._start_audio()
        else:
            self.engine.stop()
            self._update_status()

    def _start_audio(self):
        cfg = self.engine.config
        if not cfg.output_device:
            self._open_audio_dialog()
            return
        try:
            self.engine.start(cfg)
        except Exception as exc:  # noqa: BLE001 - PortAudio pode falhar de muitas formas
            self.power.setChecked(False)
            QMessageBox.warning(self, "Erro de áudio",
                                f"Não foi possível abrir o dispositivo:\n\n{exc}\n\n"
                                "Dica: verifique se outro programa está usando a placa "
                                "(no ASIO só um programa por vez) ou tente outra taxa/buffer.")
        self._refresh_all()
        self._update_status()

    def _open_audio_dialog(self):
        dlg = AudioDialog(self.engine, self)
        if dlg.exec():
            cfg, channels = dlg.result_config()
            self.engine.input_channel.update(channels)
            self.engine.config = cfg
            self.power.setChecked(True)
            self._start_audio()
        else:
            self.power.setChecked(self.engine.running)
            self._update_status()

    def _update_status(self):
        e = self.engine
        cfg = e.config
        self.power.setChecked(e.running)
        self.power.setText("■ Desligar áudio" if e.running else "▶ Ligar áudio")
        if not e.running:
            self.status.setText("Áudio desligado" + (f" · {cfg.hostapi}: {cfg.output_device}"
                                                      if cfg.output_device else ""))
            for name in ("guitar", "bass"):
                self.pages[name].input_label.setText("")
            return
        li, lo, total = e.latency_ms()
        dev_txt = cfg.output_device if not cfg.input_device or cfg.input_device == cfg.output_device \
            else f"{cfg.input_device} → {cfg.output_device}"
        self.status.setText(f"{cfg.hostapi} · {dev_txt} · {int(e.fs)} Hz · buffer {cfg.blocksize} · "
                            f"latência: entrada {li:.1f} ms + saída {lo:.1f} ms = {total:.1f} ms")
        for name in ("guitar", "bass"):
            ch = e.input_channel[name]
            if not cfg.input_device:
                txt = "sem entrada de áudio"
            elif ch >= e.n_in:
                txt = f"canal {ch + 1} indisponível"
            else:
                txt = f"Entrada {ch + 1}"
            self.pages[name].input_label.setText(txt)

    def _tick(self):
        peak = max(page.update_meters() for page in self.pages.values())
        self.m_master.push(peak * self.engine.master)
        if self.engine.running:
            self.cpu.setText(f"CPU {self.engine.cpu_load() * 100:4.0f}% · falhas {self.engine.xruns}")
        else:
            self.cpu.setText("")

    def _refresh_all(self):
        for page in self.pages.values():
            page.refresh()

    # ------------------------------------------------------------------ estado
    def _restore_state(self):
        st = storage.load_state()
        e = self.engine
        cfg = dev.AudioConfig.from_dict(st.get("audio")) if st.get("audio") else dev.default_config()
        e.config = cfg
        e.input_channel.update(st.get("input_channel", {}))
        tracks = st.get("tracks", {})
        for name in TRACKS:
            if name in tracks:
                e.tracks[name].load_state(tracks[name])
            else:
                self.pages[name].apply_preset_data(FACTORY[name][DEFAULT_PRESET[name]])
        pads = e.tracks["pads"]
        if "use_amp" not in tracks.get("pads", {}).get("values", {}).get("track", {}):
            pads.set_param("track", "use_amp", False)      # teclas limpas por padrão
        e.instruments.load_state(st.get("instruments"))
        if "synth" in st:
            e.synth.load_state(st["synth"])
        master = st.get("master_db", 0.0)
        self.master_knob.setValue(master)
        self._set_master(master)
        kb = st.get("keyboard", {})
        self.kbd.octave = kb.get("octave", 4)
        self.kbd.velocity = kb.get("velocity", 100)
        self.kbd_enable.setChecked(kb.get("enabled", True))
        if "tab" in st:
            self.tabs.setCurrentIndex(st["tab"])
        self._tab_changed(self.tabs.currentIndex())
        self._reload_midi()
        midi_name = st.get("midi_input")
        if midi_name and midi_name in winmm.list_inputs():
            self.midi_combo.setCurrentText(midi_name)
            self._open_midi(midi_name)
        self._refresh_all()
        self._update_status()
        self._autostart = st.get("running", False)

    def save_state(self):
        e = self.engine
        storage.save_state({
            "audio": e.config.to_dict(),
            "input_channel": e.input_channel,
            "tracks": {name: e.tracks[name].get_state() for name in TRACKS},
            "synth": e.synth.get_state(),
            "instruments": e.instruments.get_state(),
            "master_db": self.master_knob.value(),
            "keyboard": {"octave": self.kbd.octave, "velocity": self.kbd.velocity,
                         "enabled": self.kbd.enabled},
            "midi_input": self.midi.name if self.midi else None,
            "tab": self.tabs.currentIndex(),
            "running": e.running,
        })

    def autostart(self):
        if self._autostart and self.engine.config.output_device:
            self._start_audio()

    def closeEvent(self, ev):
        self.save_state()
        if self.midi:
            self.midi.close()
        self.engine.stop()
        super().closeEvent(ev)
