"""Janela principal: barra superior, Banco de Presets à esquerda, a aba aberta no centro e a
barra inferior (Pads, Mixer, MIDI / Controlador, Configurações).
"""
import math

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QMainWindow, QMenu, QMessageBox, QStackedWidget, QVBoxLayout, QWidget,
)

from .. import sharing, storage
from ..audio import devices as dev
from ..audio.engine import TRACKS
from ..midi import winmm
from ..presets import DEFAULT_PRESET, FACTORY
from ..sharing import sound_state
from .audio_dialog import AudioDialog
from .dock import BottomDock
from .file_menu import FileMenu
from .icons import icon
from .keyboard import PcKeyboard
from .pad_piano import DEVICES, PadPianoView, PadSoundDialog
from .panels import SynthPanel, TrackPage
from .preset_bank import PresetBank
from .theme import ACCENT, C
from .topbar import TopBar
from .widgets import find_data

TITLES = {"guitar": "Guitarra", "bass": "Baixo", "pads": "Pad/Piano"}
NO_MIDI = "(nenhum)"
PAGE_ORDER = ("guitar", "bass", "pads")


class MainWindow(QMainWindow):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.inst = engine.instruments
        self.setWindowTitle("AmpSim — Live Performance")
        self.resize(1536, 800)
        self._dock_by_page = {"guitar": True, "bass": True, "pads": False}   # recolhida?

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.topbar = TopBar()
        root.addWidget(self.topbar)
        body = QVBoxLayout()
        body.setContentsMargins(10, 10, 10, 10)
        body.setSpacing(10)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.bank = PresetBank()
        row.addWidget(self.bank)

        self.tabs = QStackedWidget()
        self.pages = {}
        self.track_pages = {}
        for name in ("guitar", "bass"):
            page = TrackPage(name, engine, ACCENT)
            self.pages[name] = page
            self.track_pages[name] = page
        amp_keys = TrackPage("pads", engine, ACCENT)
        self.track_pages["pads"] = amp_keys
        self.synth_panel = SynthPanel(engine, ACCENT)
        self.pad_view = PadPianoView(self, amp_keys, self.synth_panel)
        self.pages["pads"] = self.pad_view
        for name in PAGE_ORDER:
            self.tabs.addWidget(self.pages[name])
        self.ready_combo = self._build_ready_combo()
        for name in PAGE_ORDER:
            combo = self.ready_combo if name == "pads" else self.pages[name].preset
            self.topbar.preset_stack.addWidget(combo)
        row.addWidget(self.tabs, 1)
        body.addLayout(row, 1)
        self.dock = BottomDock(self)
        body.addWidget(self.dock)
        root.addLayout(body, 1)
        self.setCentralWidget(central)

        self.file_menu = FileMenu(self)
        self.topbar.set_menu(self.file_menu, self._build_main_menu())
        self.topbar.pageRequested.connect(self.tabs.setCurrentIndex)
        self.topbar.powerToggled.connect(self.toggle_power)
        self.topbar.audioSettings.connect(self.open_audio_dialog)
        self.topbar.presetStep.connect(self.preset_step)
        self.topbar.presetSave.connect(self.save_preset)
        self.bank.activated.connect(self.load_from_bank)
        self.bank.requestSave.connect(self.save_preset)
        self.bank.requestImport.connect(self.file_menu.open_file)
        self.bank.requestExport.connect(self._bank_export)
        self.bank.requestShareCode.connect(self._bank_code)
        self.bank.requestDelete.connect(self._bank_delete)
        self.dock.collapsedChanged.connect(self._dock_collapsed)
        self.dock.rescan.clicked.connect(self._reload_midi)
        self.dock.midi_combo.activated.connect(lambda _: self._open_midi(self.dock.midi_combo.currentText()))
        self.dock.kbd_enable.toggled.connect(self._kbd_toggled)
        self.dock.device.addItems(DEVICES)
        self.dock.device.activated.connect(lambda _: self.pad_view.set_device(self.dock.device.currentText()))
        self.dock.use_amp.clicked.connect(lambda on: amp_keys.amp_check.setChecked(on))

        self.kbd = PcKeyboard(self)
        self.kbd.noteOn.connect(lambda n, v: self.inst.key_on(n, v))
        self.kbd.noteOff.connect(lambda n: self.inst.key_off(n))
        self.kbd.changed.connect(self._update_kbd_label)

        # avisos do roteador de teclas/pads (podem vir da thread de MIDI) -> interface
        br = self.pad_view.bridge
        self.inst_bridge = br
        br.pad.connect(lambda i, v: self.pad_view.ctrl.flash_pad(i))
        br.key.connect(self._show_key)
        br.knob.connect(lambda i, v: self.pad_view.ctrl.set_knob(i, v))
        br.changed.connect(self.refresh_sounds)
        br.learn.connect(self._on_learn)
        inst = self.inst
        inst.on_pad = br.pad.emit
        inst.on_key = br.key.emit
        inst.on_knob = br.knob.emit
        inst.on_change = br.changed.emit
        inst.on_learn = br.learn.emit
        inst.on_monitor = br.monitor.emit
        inst.on_control = br.control.emit
        self.tabs.currentChanged.connect(self._tab_changed)
        self.midi = winmm.MidiInput(inst.handle_midi) if winmm.available else None

        self._restore_state()
        self._update_kbd_label()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(33)

    # ------------------------------------------------------------------ construção
    def _build_ready_combo(self):
        from .pad_piano import _combo
        from ..instruments import READY_GROUPS
        from PySide6.QtGui import QStandardItemModel

        c = _combo()
        c.setMaxVisibleItems(30)
        c.setToolTip("Timbre do Pad/Piano")
        self._ready_entries = []
        model = c.model()

        def header(text):
            c.addItem(f"──  {text}  ──")
            if isinstance(model, QStandardItemModel):
                model.item(c.count() - 1).setEnabled(False)
        mine = storage.list_user_presets("teclas")
        if mine:
            header("Meus timbres")
            for n in mine:
                c.addItem(n, ("keys_user", n))
        for group, items in READY_GROUPS:
            header(group)
            for n in items:
                c.addItem(n, ("ready", n))
        c.activated.connect(lambda i: self.load_from_bank(*c.itemData(i)) if c.itemData(i) else None)
        return c

    def _rebuild_ready_combo(self):
        old = self.ready_combo
        self.ready_combo = self._build_ready_combo()
        i = self.topbar.preset_stack.indexOf(old)
        self.topbar.preset_stack.insertWidget(i, self.ready_combo)
        self.topbar.preset_stack.removeWidget(old)
        old.deleteLater()
        self.topbar.set_page(self.tabs.currentIndex())
        self._sync_ready_combo()

    def _build_main_menu(self):
        m = QMenu(self)
        m.addAction(icon("gear", C["text"], 14), "Placa de som e driver…", self.open_audio_dialog)
        m.addAction(icon("power", C["text"], 14), "Ligar / desligar áudio",
                    lambda: self.toggle_power(not self.engine.running))
        m.addSeparator()
        fm = m.addMenu(icon("folder", C["text"], 14), "Arquivo")
        for a in self.file_menu.actions():
            fm.addAction(a)
        m.addAction(icon("midi", C["text"], 14), "MIDI / Controlador", lambda: self.dock.show_tab(2))
        m.addAction(icon("mixer", C["text"], 14), "Mixer", lambda: self.dock.show_tab(1))
        m.addAction(icon("stop", C["text"], 14), "Pânico (soltar todas as notas)", self.panic)
        m.addSeparator()
        m.addAction(icon("info", C["text"], 14), "Sobre o AmpSim e licenças…", self.file_menu.about)
        m.addAction(icon("close", C["text"], 14), "Sair (salva a sessão)", self.close)
        return m

    # ------------------------------------------------------------------ navegação
    def current_kind(self):
        return PAGE_ORDER[self.tabs.currentIndex()]

    def _tab_changed(self, index):
        name = PAGE_ORDER[index]
        self.topbar.set_page(index)
        self.dock.set_collapsed(self._dock_by_page.get(name, False))
        self._dock_collapsed(self.dock.collapsed)
        if name == "pads":
            self.pad_view.refresh()
        else:
            self.pages[name].refresh()
        self._sync_bank()

    def _dock_collapsed(self, on):
        kind = self.current_kind()
        self._dock_by_page[kind] = on
        if kind != "pads":
            self.pages[kind].set_compact(not on)

    # ------------------------------------------------------------------ presets e banco
    def preset_step(self, d):
        kind = self.current_kind()
        if kind != "pads":
            self.pages[kind].preset_step(d)
            self._sync_bank()
            return
        c = self.ready_combo
        n = c.count()
        i = c.currentIndex()
        for _ in range(n):
            i = (i + d) % n
            if c.itemData(i):
                c.setCurrentIndex(i)
                self.load_from_bank(*c.itemData(i))
                return

    def load_from_bank(self, kind, arg):
        if kind == "ready":
            self.tabs.setCurrentWidget(self.pad_view)
            self.pad_view.load_ready(arg)
        elif kind == "keys_user":
            data = storage.load_user_preset("teclas", arg)
            if data:
                self.inst.load_state(sharing.sanitize_instruments(data, self.inst.get_state()))
                self.inst.ready = ""
                self.pad_view.user_preset = arg
                self.tabs.setCurrentWidget(self.pad_view)
                self.refresh_sounds()
        elif kind == "track":
            name, src, n = arg
            page = self.track_pages[name]
            if name == "pads":
                self.tabs.setCurrentWidget(self.pad_view)
                self.pad_view.show_view(2)
            else:
                self.tabs.setCurrentWidget(page)
            page.load_preset(src, n)
        elif kind == "file":
            try:
                self.file_menu.apply_doc(sharing.load_file(arg))
            except sharing.ShareError as exc:
                QMessageBox.warning(self, "Abrir", str(exc))
        self._sync_bank()

    def save_preset(self):
        kind = self.current_kind()
        if kind == "pads" and self.pad_view.views.currentIndex() != 2:
            from PySide6.QtWidgets import QInputDialog

            default = self.pad_view.user_preset or self.inst.ready or "Meu timbre"
            n, ok = QInputDialog.getText(self, "Salvar timbre", "Nome do timbre (Pad/Piano):", text=default)
            if not ok or not n.strip():
                return
            n = n.strip()
            storage.save_user_preset("teclas", n, sound_state(self.inst.get_state()))
            self.pad_view.user_preset = storage._safe(n)
            self._rebuild_ready_combo()
            self.refresh_sounds()
        else:
            page = self.track_pages["pads" if kind == "pads" else kind]
            page.save_preset()
        self.bank.reload()
        self._sync_bank()

    def _bank_doc(self, kind, arg):
        """Documento .ampsim de um item do banco (sem precisar carregá-lo)."""
        if kind == "ready":
            from ..instruments import READY
            cur = sound_state(self.inst.get_state())
            cfg = READY[arg]
            keys = dict(cur["keys"], sound2="", mode2="layer", split=48, vol1=100, vol2=70, layer2_on=True, oct2=0)
            keys.update({k: v for k, v in cfg.items() if k != "fx"})
            data = dict(cur, keys=keys, ready=arg)
            return sharing.make_doc("preset", data, arg, "", trilha="teclas")
        if kind == "keys_user":
            return sharing.make_doc("preset", storage.load_user_preset("teclas", arg) or {}, arg, "",
                                    trilha="teclas")
        name, src, n = arg
        data = FACTORY[name][n] if src == "factory" else storage.load_user_preset(name, n)
        return sharing.make_doc("preset", data or {}, n, "", trilha=name)

    def _bank_export(self, kind, arg):
        doc = self._bank_doc(kind, arg)
        self.file_menu._save_dialog(doc, doc["nome"])
        self.bank.reload()

    def _bank_code(self, kind, arg):
        from PySide6.QtGui import QGuiApplication

        doc = self._bank_doc(kind, arg)
        QGuiApplication.clipboard().setText(sharing.to_text(doc))
        self.flash_status(f"Código de “{doc['nome']}” copiado: cole numa mensagem ou grupo.")

    def _bank_delete(self, kind, arg):
        if kind == "keys_user":
            if QMessageBox.question(self, "Excluir", f"Excluir o timbre “{arg}”?") == QMessageBox.Yes:
                storage.delete_user_preset("teclas", arg)
                self._rebuild_ready_combo()
        elif kind == "track":
            name, _src, n = arg
            self.track_pages[name].delete_user_preset(n)
        elif kind == "file":
            import os

            if QMessageBox.question(self, "Excluir", f"Excluir o arquivo “{os.path.basename(arg)}”?\n"
                                    "(vai para a Lixeira não: some de verdade)") == QMessageBox.Yes:
                try:
                    os.remove(arg)
                except OSError as exc:
                    QMessageBox.warning(self, "Excluir", str(exc))
        self.bank.reload()

    def _sync_ready_combo(self):
        c = self.ready_combo
        data = ("keys_user", self.pad_view.user_preset) if self.pad_view.user_preset else \
            (("ready", self.inst.ready) if self.inst.ready else None)
        c.blockSignals(True)
        i = find_data(c, data) if data else -1
        if i < 0:
            if c.findText("(personalizado)") < 0:
                c.insertItem(0, "(personalizado)")
            i = 0
        else:
            j = c.findText("(personalizado)")
            if j >= 0:
                c.removeItem(j)
                i = find_data(c, data)
        c.setCurrentIndex(i)
        c.blockSignals(False)
        return data

    def _sync_bank(self):
        kind = self.current_kind()
        if kind == "pads":
            if self.pad_view.views.currentIndex() == 2:
                d = self.track_pages["pads"].preset.currentData()
                self.bank.select(("track", ("pads",) + tuple(d)) if d else None)
            else:
                self.bank.select(self._sync_ready_combo())
        else:
            d = self.pages[kind].preset.currentData()
            self.bank.select(("track", (kind,) + tuple(d)) if d else None)

    # ------------------------------------------------------------------ atualização
    def refresh_sounds(self):
        """Algo das teclas/pads mudou (MIDI, menus, presets)."""
        self.pad_view.refresh()
        self.dock.refresh()
        if self.current_kind() == "pads":
            self._sync_bank()

    def refresh_track(self, name):
        if name == "pads":
            self.track_pages["pads"].refresh()
        elif self.current_kind() == name:
            self.pages[name].refresh()

    def _refresh_all(self):
        for page in self.track_pages.values():
            page.refresh()
        self.synth_panel.refresh()
        self.refresh_sounds()

    def _on_learn(self):
        self.dock.on_learn()
        self.pad_view.refresh()

    def _show_key(self, note, on):
        self.pad_view.show_key(note, on)

    def open_pad_eq(self):
        self.pad_view.open_pad_eq()

    def choose_pad_sound(self, i):
        dlg = PadSoundDialog(self.inst, i, self)
        if dlg.exec() and dlg.choice:
            self.inst.set_pad_sound(i, dlg.choice)
        self.refresh_sounds()

    def panic(self):
        self.kbd.release_all()
        self.inst.all_off()
        self.inst.stop_cont_pad()
        self.pad_view.piano.clear()

    def _kbd_toggled(self, on):
        self.kbd.release_all()
        self.kbd.enabled = on
        self._update_kbd_label()

    def _update_kbd_label(self):
        piano = self.pad_view.piano
        if not self.kbd.enabled:
            self.dock.kbd_label.setText("Desligado: as letras não tocam notas.")
            piano.marker_low = None
        else:
            self.dock.kbd_label.setText(f"Oitava C{self.kbd.octave} (Z/X) · Força {self.kbd.velocity} (C/V)\n"
                                        "Teclas: A W S E D F T G Y H U J K O L P Ç")
            piano.marker_low = self.kbd.base_note
        piano.update()

    # ------------------------------------------------------------------ master
    def master_db(self):
        m = self.engine.master
        return 20 * math.log10(m) if m > 1e-4 else -40.0

    def set_master_db(self, db):
        self.engine.master = 10 ** (db / 20) if db > -39.9 else 0.0

    def set_master_pct(self, pct):
        self.engine.master = (pct / 100) ** 2 * 2.0
        self.dock.refresh()

    # ------------------------------------------------------------------ MIDI
    def _reload_midi(self):
        combo = self.dock.midi_combo
        current = self.midi.name if self.midi else None
        combo.clear()
        combo.addItem(NO_MIDI)
        combo.addItems(winmm.list_inputs())
        if current:
            combo.setCurrentText(current)

    def _open_midi(self, name):
        if self.midi is None:
            return
        self.midi.close()
        if name and name != NO_MIDI:
            try:
                self.midi.open(name)
            except RuntimeError as exc:
                QMessageBox.warning(self, "MIDI", str(exc))
                self.dock.midi_combo.setCurrentText(NO_MIDI)

    # ------------------------------------------------------------------ áudio
    def toggle_power(self, on):
        if on:
            self._start_audio()
        else:
            self.engine.stop()
            self._update_status()

    def _start_audio(self):
        cfg = self.engine.config
        if not cfg.output_device:
            self.open_audio_dialog()
            return
        try:
            self.engine.start(cfg)
        except Exception as exc:  # noqa: BLE001 - PortAudio pode falhar de muitas formas
            QMessageBox.warning(self, "Erro de áudio",
                                f"Não foi possível abrir o dispositivo:\n\n{exc}\n\n"
                                "Dica: verifique se outro programa está usando a placa "
                                "(no ASIO só um programa por vez) ou tente outra taxa/buffer.")
        self._refresh_all()
        self._update_status()

    def open_audio_dialog(self):
        dlg = AudioDialog(self.engine, self)
        if dlg.exec():
            cfg, channels = dlg.result_config()
            self.engine.input_channel.update(channels)
            self.engine.config = cfg
            self._start_audio()
        else:
            self._update_status()

    def flash_status(self, text, ms=8000):
        self.topbar.info2.setText(text)
        self.topbar.info2.setToolTip(text)
        QTimer.singleShot(ms, self._update_status)

    def _update_status(self):
        e = self.engine
        cfg = e.config
        if not e.running:
            line1 = f"{cfg.hostapi or 'Sem driver'} · desligado"
            line2 = cfg.output_device or "clique para escolher a placa"
            for name in ("guitar", "bass"):
                self.pages[name].input_label.setText("")
            self.topbar.set_audio(False, line1, line2)
            self.dock.audio_label.setText("Áudio desligado. " + (f"{cfg.hostapi}: {cfg.output_device}"
                                                                 if cfg.output_device else ""))
            self.dock.refresh()
            return
        li, lo, total = e.latency_ms()
        self.topbar.set_audio(True, f"{cfg.hostapi} · {int(e.fs):,} Hz".replace(",", "."),
                              f"Buffer {cfg.blocksize} · {total:.1f} ms")
        dev_txt = cfg.output_device if not cfg.input_device or cfg.input_device == cfg.output_device \
            else f"{cfg.input_device} → {cfg.output_device}"
        self.dock.audio_label.setText(f"{cfg.hostapi} · {dev_txt}\n{int(e.fs)} Hz · buffer {cfg.blocksize} · "
                                      f"latência {li:.1f} + {lo:.1f} = {total:.1f} ms")
        for name in ("guitar", "bass"):
            ch = e.input_channel[name]
            if not cfg.input_device:
                txt = "Sem entrada de áudio escolhida"
            elif ch >= e.n_in:
                txt = f"Canal {ch + 1} indisponível na placa"
            else:
                txt = f"Entrada: canal {ch + 1} · {cfg.input_device}"
            self.pages[name].input_label.setText(txt)
        self.dock.refresh()

    def _tick(self):
        e = self.engine
        self.inst.tick(0.033)      # fades do pad contínuo, note-offs programados
        peaks = {name: self.track_pages[name].update_meters() for name in TRACKS}
        peaks["master"] = max(peaks.values()) * e.master
        self.dock.update_meters(peaks)
        self._cpu_tick = getattr(self, "_cpu_tick", 0) + 1
        if e.running and self._cpu_tick % 15 == 0:          # 2x por segundo basta
            cfg = e.config
            _, _, total = e.latency_ms()
            self.topbar.info2.setText(f"Buffer {cfg.blocksize} · {total:.1f} ms · CPU {e.cpu_load() * 100:.0f}%")
            self.topbar.power.setToolTip(f"Áudio ligado · CPU {e.cpu_load() * 100:.0f}% · falhas {e.xruns}\n"
                                         "Clique para desligar")

    # ------------------------------------------------------------------ cenas (menu Arquivo)
    def scene_state(self):
        """Tudo que é som: trilhas, synth, timbres/pads e master (sem placa de áudio nem mapeamento)."""
        e = self.engine
        return {"tracks": {name: e.tracks[name].get_state() for name in TRACKS},
                "synth": e.synth.get_state(),
                "instruments": sound_state(e.instruments.get_state()),
                "master_db": self.master_db()}

    def apply_scene(self, st):
        """`st` já limpo por sharing.sanitize_scene."""
        e = self.engine
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for name, ts in st.get("tracks", {}).items():
                e.tracks[name].load_state(ts)
            if st.get("synth"):
                e.synth.load_state(st["synth"])
            e.instruments.load_state(st.get("instruments"))
        finally:
            QApplication.restoreOverrideCursor()
        if "master_db" in st:
            self.set_master_db(st["master_db"])
        self.pad_view.user_preset = ""
        self._refresh_all()

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
                self.track_pages[name].apply_preset_data(FACTORY[name][DEFAULT_PRESET[name]])
        pads = e.tracks["pads"]
        if "use_amp" not in tracks.get("pads", {}).get("values", {}).get("track", {}):
            pads.set_param("track", "use_amp", False)      # teclas limpas por padrão
        e.instruments.load_state(st.get("instruments"))
        if "synth" in st:
            e.synth.load_state(st["synth"])
        self.set_master_db(st.get("master_db", 0.0))
        kb = st.get("keyboard", {})
        self.kbd.octave = kb.get("octave", 4)
        self.kbd.velocity = kb.get("velocity", 100)
        self.dock.kbd_enable.setChecked(kb.get("enabled", True))
        ui = st.get("ui", {})
        if ui.get("layout") != 2:
            e.instruments.device = "Teclado simples"      # 1ª vez no visual novo: teclado + knobs
        if isinstance(ui.get("dock_collapsed"), dict):
            self._dock_by_page.update({k: bool(v) for k, v in ui["dock_collapsed"].items()
                                       if k in self._dock_by_page})
        if isinstance(ui.get("dock_tab"), int) and 0 <= ui["dock_tab"] < 4:
            self.dock.stack.setCurrentIndex(ui["dock_tab"])
        self.pad_view.user_preset = ui.get("keys_user", "") if isinstance(ui.get("keys_user"), str) else ""
        tab = st.get("tab", 2)
        self.tabs.setCurrentIndex(tab if isinstance(tab, int) and 0 <= tab < 3 else 2)
        self._tab_changed(self.tabs.currentIndex())
        self._reload_midi()
        midi_name = st.get("midi_input")
        if midi_name and midi_name in winmm.list_inputs():
            self.dock.midi_combo.setCurrentText(midi_name)
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
            "master_db": self.master_db(),
            "keyboard": {"octave": self.kbd.octave, "velocity": self.kbd.velocity,
                         "enabled": self.kbd.enabled},
            "midi_input": self.midi.name if self.midi else None,
            "tab": self.tabs.currentIndex(),
            "running": e.running,
            "ui": {"layout": 2, "dock_collapsed": dict(self._dock_by_page), "dock_tab": self.dock.stack.currentIndex(),
                   "keys_user": self.pad_view.user_preset},
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
