"""Janela principal: menus (Arquivo, Exibir), barra superior, a aba aberta no centro e as subjanelas
(Setlist, Banco de presets, partes da tela Pad/Piano e a barra Pads / Faders / MIDI) que dá para arrastar,
destacar e esconder (ui/docks.py).
"""
import math
import os
import subprocess
import threading
import time

from PySide6.QtCore import QObject, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication, QLabel, QMainWindow, QMenu, QMenuBar, QMessageBox, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from .. import sharing, storage, updater
from ..version import version_text
from ..audio import devices as dev
from ..audio.hotplug import DeviceWatcher, audio_outputs, find_instrument_output, instrument_of
from ..audio.engine import TRACKS
from ..midi import winmm
from ..instruments import READY
from .health import HealthDialog, style_badge
from .packs_dialog import PacksDialog
from .setlist_panel import SetlistPanel
from .shortcuts import Shortcuts, ShortcutsDialog
from ..presets import DEFAULT_PRESET, FACTORY
from ..sharing import sound_state
from .audio_dialog import AudioDialog
from .dock import BottomDock
from .docks import DockManager
from .file_menu import FileMenu
from .icons import icon
from .keyboard import PcKeyboard
from .pad_piano import DEVICES, PadPianoView, PadSoundDialog
from .panels import SynthPanel, TrackPage
from .preset_bank import PresetBank
from .theme import ACCENT, C
from .topbar import TopBar
from .vocal_page import VocalPage
from .webserver_dialog import WebServerDialog
from ..web.remote import Remote
from .widgets import find_data

TITLES = {"guitar": "Guitarra", "bass": "Baixo", "pads": "Pad/Piano", "vocal": "Vocal"}
NO_MIDI = "(nenhum)"
PAGE_ORDER = ("guitar", "bass", "pads", "vocal")


class _PageStack(QStackedWidget):
    """Abas do centro: o tamanho mínimo é o da aba aberta (a da guitarra não obriga a janela a crescer
    quando a Pad/Piano está na tela, e vice-versa). aboutToChange avisa ANTES de trocar, para a janela
    tirar as subjanelas que só cabem na aba que sai (senão, por um instante, a janela cresceria)."""
    aboutToChange = Signal(int)

    def __init__(self):
        super().__init__()
        self.floor_w = self.floor_h = 0   # mínimo extra fora da Pad/Piano (ver DockManager._apply_floor)
        self.no_floor = None          # a página que não usa floor_w (a Pad/Piano)
        self.currentChanged.connect(lambda *_: self.updateGeometry())

    def setCurrentIndex(self, i):
        if i != self.currentIndex():
            self.aboutToChange.emit(i)
        super().setCurrentIndex(i)

    def setCurrentWidget(self, w):
        self.setCurrentIndex(self.indexOf(w))

    def minimumSizeHint(self):
        w = self.currentWidget()
        m = w.minimumSizeHint() if w is not None else super().minimumSizeHint()
        if w is not None and w is not self.no_floor:
            m = m.expandedTo(QSize(self.floor_w, self.floor_h))
        return m

    def sizeHint(self):
        w = self.currentWidget()
        return w.sizeHint() if w is not None else super().sizeHint()


class _UpdateBridge(QObject):
    done = Signal(object, str, bool)       # UpdateInfo ou None, erro, foi pedido à mão


class _CtlBridge(QObject):
    wake = Signal()                        # controle mapeado das abas/plugins mexeu (thread do MIDI)


class _Toast(QLabel):
    """Aviso legível por cima da janela (texto inteiro, quebra linha); some sozinho ou com um clique."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWordWrap(True)
        self.setObjectName("toast")
        self.setStyleSheet(f"QLabel#toast {{ background: {C['card2']}; color: {C['text']}; border: 1px solid "
                           f"{C['yellow']}; border-radius: 8px; padding: 10px 14px; font-size: 10pt; }}")
        self.setCursor(Qt.PointingHandCursor)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self.hide()

    def show_text(self, text, ms):
        self.setText(text)
        p = self.parentWidget()
        w = min(560, max(260, p.width() - 40))
        self.setFixedWidth(w)
        self.adjustSize()
        top = p.menuWidget().height() + 8 if p.menuWidget() is not None else 60
        self.move((p.width() - w) // 2, top)
        self.show()
        self.raise_()
        self._timer.start(ms)

    def mousePressEvent(self, e):
        self.hide()


class MainWindow(QMainWindow):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.inst = engine.instruments
        self.setWindowTitle(f"AmpSim {version_text()} — Live Performance")
        self.resize(1536, 800)
        self._dock_by_page = {"guitar": True, "bass": True, "pads": False, "vocal": True}   # recolhida?

        # topo: barra de menus (Arquivo, Exibir), a barra superior e a faixa do mute geral
        head = QWidget()
        root = QVBoxLayout(head)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.menu_bar = QMenuBar()
        self.menu_bar.setNativeMenuBar(False)
        root.addWidget(self.menu_bar)
        self.topbar = TopBar()
        root.addWidget(self.topbar)
        # mute geral ligado: faixa vermelha bem visível (clique nela também volta o som)
        self.mute_banner = QPushButton("SEM SOM  ·  mute geral ligado  ·  clique aqui ou Alt+Espaço para voltar")
        self.mute_banner.setFocusPolicy(Qt.NoFocus)
        self.mute_banner.setCursor(Qt.PointingHandCursor)
        self.mute_banner.setStyleSheet(f"QPushButton {{ background: {C['red']}; color: white; border: none; "
                                       "font-size: 13pt; font-weight: 800; padding: 6px; }")
        self.mute_banner.clicked.connect(lambda: self.toggle_mute_all())
        self.mute_banner.setVisible(False)
        root.addWidget(self.mute_banner)
        self.setMenuWidget(head)
        self.bank = PresetBank()
        self.setlist = SetlistPanel(self)

        self.tabs = _PageStack()
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
        vocal = VocalPage(engine, ACCENT)            # microfone (dsp/vocal.py)
        self.pages["vocal"] = vocal
        self.track_pages["vocal"] = vocal
        for name in PAGE_ORDER:
            self.tabs.addWidget(self.pages[name])
        self.ready_combo = self._build_ready_combo()
        for name in PAGE_ORDER:
            combo = self.ready_combo if name == "pads" else self.pages[name].preset
            self.topbar.preset_stack.addWidget(combo)
        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(2, 0, 2, 0)
        cl.addWidget(self.tabs)
        self.setCentralWidget(central)
        self.dock = BottomDock(self)
        # subjanelas (arrastar, destacar, esconder, travar; menu Exibir)
        self.panels = DockManager(self)

        self.file_menu = FileMenu(self)
        self.main_menu = self._build_main_menu()
        self.topbar.set_menu(self.file_menu, self.main_menu)
        self._build_menu_bar()
        self.topbar.pageRequested.connect(self.tabs.setCurrentIndex)
        self.topbar.powerToggled.connect(self.toggle_power)
        self.topbar.audioSettings.connect(self.open_audio_dialog)
        self.topbar.presetStep.connect(self.preset_step)
        for b, d in ((self.topbar.prev_btn, "prev"), (self.topbar.next_btn, "next")):
            # botão direito: mapear preset anterior/próximo da aba num botão do controlador
            b.setContextMenuPolicy(Qt.CustomContextMenu)
            b.customContextMenuRequested.connect(lambda pos, b=b, d=d: self._preset_button_popup(b, d, pos))
        self.topbar.presetSave.connect(self.save_preset)
        self.bank.activated.connect(self.load_from_bank)
        self.bank.requestSave.connect(self.save_preset)
        self.bank.requestImport.connect(self.file_menu.open_file)
        self.bank.requestExport.connect(self._bank_export)
        self.bank.requestShareCode.connect(self._bank_code)
        self.bank.requestDelete.connect(self._bank_delete)
        self.bank.requestPart.connect(self.load_part)
        self.dock.collapsedChanged.connect(self._dock_collapsed)
        self.dock.rescan.clicked.connect(lambda *_: (self._reload_midi(), self.reopen_midi("botão ↻")))
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
        # o knob mexe em volumes/efeitos: painel lateral e Mixer acompanham (no máximo ~30x/s)
        self._knob_sync = QTimer(self)
        self._knob_sync.setSingleShot(True)
        self._knob_sync.setInterval(33)
        self._knob_sync.timeout.connect(self._sync_knob_values)
        br.knob.connect(lambda *_: self._knob_sync.isActive() or self._knob_sync.start())
        br.changed.connect(self.refresh_sounds)
        br.learn.connect(self._on_learn)
        inst = self.inst
        inst.on_pad = br.pad.emit
        inst.on_key = br.key.emit
        inst.on_knob = br.knob.emit
        inst.on_change = br.changed.emit
        inst.on_learn = br.learn.emit
        inst.on_song = br.song.emit
        br.song.connect(lambda d: self.setlist.step(d))
        inst.on_monitor = br.monitor.emit
        inst.on_control = br.control.emit
        inst.on_unmapped = br.unmapped.emit
        br.unmapped.connect(self._unmapped_control)
        # controles mapeados das abas Guitarra/Baixo/Vocal e dos plugins (midi_map.py): a mensagem chega na
        # thread do MIDI; o valor é aplicado aqui, na thread da interface, pelo mesmo caminho da tela
        self._ctl_bridge = _CtlBridge(self)
        self._ctl_bridge.wake.connect(self._ctl_flush, Qt.QueuedConnection)
        inst.ctl.wake = self._ctl_bridge.wake.emit
        inst.ctl.on_preset = lambda track, d: self.preset_step(d, kind=track)
        self._toast = _Toast(self)
        br.monitor.connect(self._midi_activity)
        self._unmapped_at = 0.0
        self.tabs.aboutToChange.connect(self._before_tab)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.midi = winmm.MidiInput(inst.handle_midi) if winmm.available else None
        self._midi_lost = None              # teclado que sumiu e deve ser religado quando voltar

        self.shortcuts = Shortcuts(self)
        self._want_audio = False            # o usuário quer o áudio ligado (para religar se cair)
        self._reconnect_at = None           # próximo instante de tentar religar (None = não caiu)
        self.topbar.health_btn.clicked.connect(lambda *_: HealthDialog(self.engine, self).exec())
        self._restore_state()
        from . import ctl_map_ui
        ctl_map_ui.refresh_tags(self)           # ponto verde/dica nos controles mapeados das abas
        self.bank.set_page(self.current_kind())
        self._update_kbd_label()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(33)
        # aparelhos conectados com o app aberto (ex.: teclado com interface de áudio própria)
        self.watcher = DeviceWatcher()
        self.watcher.poll()
        self._declined_outputs = set()
        self.hotplug_timer = QTimer(self)
        self.hotplug_timer.timeout.connect(self.check_new_devices)
        self.hotplug_timer.start(2000)
        # atualização pelo GitHub: confere ao abrir (em segundo plano)
        self._update_bridge = _UpdateBridge(self)
        self._update_bridge.done.connect(self._update_done)
        self._update_thread = None
        self.topbar.update_btn.clicked.connect(lambda *_: self.restart())
        self.topbar.version_btn.clicked.connect(lambda *_: self.show_about())
        self.dock.auto_update.toggled.connect(lambda on: setattr(self, "auto_update", on))
        self._show_version()
        # a pasta pode ganhar uma versão nova com o programa aberto (git pull, atualização feita
        # por outra janela): aí o botão de reiniciar aparece mesmo sem nada para baixar
        self._running_commit = updater.local_commit()
        self.stale_timer = QTimer(self)
        self.stale_timer.timeout.connect(self._check_stale)
        self.stale_timer.start(30000)
        if self.auto_update and not os.environ.get("AMPSIM_NO_UPDATE"):    # testes não acessam a rede
            QTimer.singleShot(2500, self.check_updates)
        # tela remota (celular/tablet na rede): liga sozinho se ficou ligado da última vez
        self.remote = Remote(self)
        self.topbar.web_btn.clicked.connect(lambda *_: self.open_webserver())
        if self.remote.cfg["ligado"] and not os.environ.get("AMPSIM_NO_WEB"):
            if not self.remote.start():
                QTimer.singleShot(1500, lambda: self.flash_status(self.remote.server.error, 8000))
        self._update_web_btn()

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

    def _build_menu_bar(self):
        """Arquivo: o mesmo do botão Arquivo e do menu ☰. Exibir: subjanelas, travar e layout padrão."""
        arq = self.menu_bar.addMenu("&Arquivo")
        seen = set()
        for group in (self.file_menu.actions(), [None], self.main_menu.actions()):
            for a in group:
                if a is None or a.isSeparator():
                    acts = arq.actions()
                    if acts and not acts[-1].isSeparator():
                        arq.addSeparator()          # sem separador repetido nem no começo
                    continue
                if a.menu() is not None and a.menu().title() == "Arquivo":
                    continue                            # o ☰ repete o Arquivo num submenu
                key = a.text().replace("&", "").strip()
                if key in seen:
                    continue                            # o ☰ e o botão Arquivo têm itens iguais ("Sobre…")
                seen.add(key)
                arq.addAction(a)
        while arq.actions() and arq.actions()[-1].isSeparator():
            arq.removeAction(arq.actions()[-1])
        self.view_menu = self.menu_bar.addMenu("&Exibir")
        self.panels.build_menu(self.view_menu)

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
        m.addAction(icon("mixer", C["text"], 14), "Faders / Pads", lambda: self.dock.show_tab(1))
        m.addAction(icon("tap", C["text"], 14), "Teclas de atalho…", self.open_shortcuts)
        m.addAction(icon("download", C["text"], 14), "Downloads: timbres e plugins…", lambda: self.open_packs())
        m.addAction(icon("eq", C["text"], 14), "Plugins no Master (FX)…", lambda: self.open_master_plugin())
        m.addAction(icon("stop", C["text"], 14), "Pânico (soltar todas as notas)", self.panic)
        m.addSeparator()
        m.addAction(icon("info", C["text"], 14), "Sobre o AmpSim…", lambda: self.show_about())
        m.addAction(icon("close", C["text"], 14), "Sair (salva a sessão)", self.close)
        return m

    # ------------------------------------------------------------------ navegação
    def current_kind(self):
        return PAGE_ORDER[self.tabs.currentIndex()]

    def _before_tab(self, index):
        """Antes de trocar de aba: o que só cabe na aba que sai some primeiro (subjanelas da Pad/Piano,
        barra de baixo que recolhe); o que a aba nova mostra aparece depois, em _tab_changed."""
        name = PAGE_ORDER[index]
        if name != "pads":
            self.panels.set_page(name)
        if self._dock_by_page.get(name, False) and not self.dock.collapsed:
            self.dock.blockSignals(True)              # sem gravar "recolhida" na aba que está saindo
            self.dock.set_collapsed(True)
            self.dock.blockSignals(False)

    def _tab_changed(self, index):
        name = PAGE_ORDER[index]
        self.topbar.set_page(index)
        self.panels.set_page(name)
        self.dock.set_collapsed(self._dock_by_page.get(name, False))
        self._dock_collapsed(self.dock.collapsed)
        if name == "pads":
            self.pad_view.refresh()
        else:
            self.pages[name].refresh()
        self.bank.set_page(name)                    # o banco mostra só presets desta aba
        self._sync_bank()

    def _dock_collapsed(self, on):
        kind = self.current_kind()
        self._dock_by_page[kind] = on
        if kind != "pads":
            self.pages[kind].set_compact(not on)

    # ------------------------------------------------------------------ presets e banco
    def preset_button_menu(self, d):
        """Botão direito em ◀ / ▶ (preset da aba): mapear num botão do controlador. Na Pad/Piano são os
        atalhos "Timbre anterior"/"Próximo timbre"; nas outras abas, "<aba>/preset/prev|next"."""
        from . import ctl_map_ui
        kind = self.current_kind()
        if kind != "pads":
            return ctl_map_ui.menu(self, f"{kind}/preset/{d}", self.topbar)
        func = "Timbre anterior" if d == "prev" else "Próximo timbre"
        cur = self.inst.free_map.get(func)
        from .midi_learn import key_text
        m = QMenu(self.topbar)
        m.addSection(f"Pad/Piano › {func}")
        m.addAction(f"Mapear controle físico…   (atual: {key_text(cur)})", lambda: self.pad_view.learn(func))
        a = m.addAction("Remover mapeamento", lambda: self.pad_view.unmap(func))
        a.setEnabled(bool(cur))
        return m

    def _preset_button_popup(self, b, d, pos):
        m = self.preset_button_menu(d)
        if m is not None:
            m.exec(b.mapToGlobal(pos))

    def preset_step(self, d, kind=None):
        kind = kind or self.current_kind()
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

    # ------------------------------------------------------------------ mute geral e atalhos
    def toggle_mute_all(self, on=None):
        e = self.engine
        e.muted = (not e.muted) if on is None else bool(on)
        self.mute_banner.setVisible(e.muted)

    def click_output_ok(self):
        """Antes de ligar o click: ele tem por onde sair? Sem saída escolhida, pergunta se pode tocar
        na saída principal (aí ele vai junto para o PA)."""
        e = self.engine
        if e.click_offset != -2 or e.config.click_offset == -1:
            return True
        ans = QMessageBox.question(
            self, "Metrônomo",
            "O click ainda não tem saída escolhida.\n\nTocar o click na saída principal? (Ele vai junto "
            "para o PA: bom para ensaiar em casa.)\n\nPara mandar só para os fones da banda, escolha um par de "
            "saídas livre da placa em Placa de som e driver → Saída do metrônomo.")
        if ans != QMessageBox.Yes:
            return False
        e.config.click_offset = -1
        e.click_offset = -1
        return True

    def open_master_plugin(self):
        """Janela "Plugins — Master": cadeia FX antes do Compressor/limitador."""
        return self.open_fx("master")

    def open_fx(self, kind, arg=None):
        """Janela (não modal, uma por cadeia) dos plugins VST3: kind "layer" (arg = camada 1-4), "master"
        ou "track" (arg = "guitar"/"bass"/"vocal"). -> a FxChainWindow."""
        from .plugin_slot import FxChainWindow
        wins = self.__dict__.setdefault("_fx_windows", {})
        key = (kind, arg)
        dlg = wins.get(key)
        if dlg is None:
            e, inst = self.engine, self.inst
            note_fn = None
            if kind == "layer":
                get = (lambda n=arg: inst.layer_chain(n))
                title = f"Plugins — Layer {arg}"
                intro = (f"Plugins só da camada {arg}, em série (de cima para baixo, até 4), depois de "
                         "Rotação/Drive/Delay. O painel de cada plugin (⚙) abre numa janela própria.")

                def note_fn(n=arg):
                    if inst.synth_layer_index() == n - 1:
                        return ("Timbre do synth AmpSim: os plugins recebem o synth em mono e o resultado "
                                "volta em mono para a trilha das teclas.")
                    pads = e.tracks["pads"].values["track"]
                    if pads.get("use_amp", True) and pads.get("on", True):
                        return ("Com “Amp e efeitos” ligado nas teclas, os plugins entram antes do "
                                "amplificador, em mono (Rotação/Drive/Delay da camada ficam de fora).")
                    return ""
            elif kind == "master":
                get = (lambda: e.master_chain)
                title = "Plugins — Master"
                intro = ("Entram em tudo o que sai do AmpSim (teclas, pads, bateria, guitarra e baixo), antes do "
                         "Compressor e do limitador da saída, que continuam protegendo as caixas. Ficam na "
                         "sessão (não mudam com presets nem músicas).")
            elif arg == "vocal":
                get = (lambda: e.tracks["vocal"].fx_chain)
                title = "Plugins — Vocal"
                intro = ("Plugins da voz, em série (até 4). Entram antes da dobra/delay/reverb ou no fim da "
                         "cadeia, conforme “Os plugins entram” na aba Vocal, e sempre antes do volume da trilha. "
                         "O compressor/limitador do Master continua protegendo as caixas.")

                def vocal_note():
                    if e.config.blocksize / max(e.fs, 1.0) > 0.0107:
                        return ("Buffer da placa alto: plugins pesados somados ao buffer atrasam a voz no "
                                "retorno de quem canta.")
                    return ""
                note_fn = vocal_note
            else:
                get = (lambda name=arg: e.tracks[name].fx_chain)
                title = "Plugins — " + {"guitar": "Guitarra", "bass": "Baixo"}.get(arg, str(arg))
                intro = ("Plugins no fim da trilha, depois do gabinete e dos efeitos e antes do volume da "
                         "trilha (o plugin no lugar do amplificador continua no seletor do amp).")
            chain_id = f"L{arg}" if kind == "layer" else "master" if kind == "master" else arg
            dlg = FxChainWindow(get, title, on_downloads=lambda: self.open_packs(), parent=self,
                                note_fn=note_fn, intro=intro, chain_id=chain_id)
            wins[key] = dlg
        dlg.bind()
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        return dlg

    def refresh_plugins(self):
        """Plugins instalados/removidos (tela de downloads): recarrega as listas das janelas FX e dos
        seletores de amp de Guitarra/Baixo."""
        for dlg in self.__dict__.get("_fx_windows", {}).values():
            dlg.refresh_lists()
        for page in self.track_pages.values():
            amp = getattr(page, "rig", None)
            if amp is not None and hasattr(amp, "_fill_selector"):
                amp._fill_selector()
                amp.refresh()

    def open_packs(self, start=None):
        """Tela "Downloads: timbres e plugins"; start = pacote para já começar a baixar."""
        dlg = PacksDialog(self)
        if start is not None:
            dlg.download(start)
        dlg.exec()

    def install_pending_packs(self):
        """Pianos que o instalador baixou: instala agora (com a barra de progresso da tela)."""
        from ..audio import packs
        items = packs.pending()
        if not items:
            return False
        dlg = PacksDialog(self)
        dlg.install_many(items)
        dlg.show()
        return True

    def offer_pack(self, sound_name):
        """Escolheu um timbre de pacote não instalado: toca o piano padrão e oferece baixar."""
        pack = self.inst.pack_missing(sound_name)
        if pack is None:
            return False
        if QMessageBox.question(
                self, "Timbre adicional",
                f"“{sound_name}” é um piano gravado que ainda não está no computador "
                f"(download de {pack.download_mb} MB).\n\nEnquanto isso toca o Piano de Cauda normal.\n\n"
                "Baixar agora?") == QMessageBox.Yes:
            self.open_packs(start=pack)
        return True

    def open_shortcuts(self):
        ShortcutsDialog(self.shortcuts, self).exec()

    def shortcut_action(self, action):
        inst = self.inst
        mutes = {"mute_l1": "Volume camada 1", "mute_l2": "Volume camada 2", "mute_l3": "Volume camada 3",
                 "mute_l4": "Volume camada 4", "mute_pad": "Volume pad contínuo", "mute_drums": "Volume bateria"}
        if action == "mute_all":
            self.toggle_mute_all()
        elif action == "mute_vocal":
            self.dock._mute("vocal", not self.engine.tracks["vocal"].values["track"]["mute"])
        elif action in mutes:
            f = mutes[action]
            self.dock._mute(f, f not in inst.mutes)
        elif action in ("preset_next", "preset_prev"):
            self.preset_step(1 if action == "preset_next" else -1)
        elif action.startswith("tab_"):
            self.tabs.setCurrentIndex(PAGE_ORDER.index(action[4:]))
        elif action == "panic":
            self.panic()
            self.refresh_sounds()
        elif action == "rec":
            rec = self.dock.recorder
            rec.stop() if self.engine.recorder.active else rec.start()
        elif action == "tap":
            inst.tap_tempo()
        elif action == "click":
            if self.engine.metronome.on or self.click_output_ok():
                inst.do_button("Metrônomo liga/desliga")
                self.pad_view.refresh_values()
        elif action in ("song_next", "song_prev"):
            self.setlist.step(1 if action == "song_next" else -1)
        elif action == "stop_pad":
            inst.stop_cont_pad()
            self.refresh_sounds()

    def load_part(self, kind, arg, part):
        """Botão direito no banco: só uma parte do preset (timbre numa camada, só amp, só efeitos...)."""
        if kind in ("ready", "keys_user"):
            if kind == "ready":
                cfg = READY[arg]
                sound, fx = cfg["sound1"], cfg.get("fx", {})
            else:
                data = storage.load_user_preset("teclas", arg) or {}
                sound = data.get("keys", {}).get("sound1")
                fx = (data.get("layer_fx") or [data.get("fx") or {}])[0]
            if not sound:
                return
            self.tabs.setCurrentWidget(self.pad_view)
            self.pad_view.send_sound(sound, fx, part)
        elif kind == "track":
            name, src, n = arg
            data = FACTORY[name][n] if src == "factory" else storage.load_user_preset(name, n)
            if not data:
                return
            if part == "other":                     # preset de guitarra no baixo (ou o contrário)
                page = self.track_pages["bass" if name == "guitar" else "guitar"]
                self.tabs.setCurrentWidget(page)
                page.apply_preset_data(data)
            else:
                page = self.track_pages[name]
                if name == "pads":
                    self.tabs.setCurrentWidget(self.pad_view)
                    self.pad_view.show_view(2)
                else:
                    self.tabs.setCurrentWidget(page)
                page.apply_preset_part(data, part)
        self.refresh_sounds()
        self._sync_bank()

    def save_preset(self):
        kind = self.current_kind()
        if kind == "pads" and self.pad_view.views.currentIndex() != 2:
            from PySide6.QtWidgets import QInputDialog

            default = self.pad_view.user_preset or self.inst.ready or "Meu timbre"
            n, ok = QInputDialog.getText(self, "Salvar timbre", "Nome do timbre (Pad/Piano):", text=default)
            if ok and n.strip():
                self.save_keys_preset(n)
            return
        page = self.track_pages["pads" if kind == "pads" else kind]
        page.save_preset()
        self.bank.reload()
        self._sync_bank()

    def save_keys_preset(self, name):
        """Salva o setup atual do Pad/Piano (camadas, volumes, efeitos...) em "Meus timbres".
        Usado pela janela de salvar e pela tela remota. -> nome salvo (ou None se vazio)."""
        n = (name or "").strip()
        if not n:
            return None
        storage.save_user_preset("teclas", n, sound_state(self.inst.get_state()))
        self.pad_view.user_preset = storage._safe(n)
        self._rebuild_ready_combo()
        self.refresh_sounds()
        self.bank.reload()
        self._sync_bank()
        return self.pad_view.user_preset

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
        from . import ctl_map_ui
        ctl_map_ui.refresh_tags(self)

    def _ctl_flush(self):
        """Aplica os valores que chegaram dos controles mapeados (abas e plugins) e a tela acompanha."""
        from . import ctl_map_ui
        tids = self.inst.ctl.flush()
        if tids:
            ctl_map_ui.sync_widgets(self, tids)

    def _sync_knob_values(self):
        self.pad_view.refresh_values()
        self.dock.refresh_levels()

    def _midi_activity(self, kind, ch, num, val):
        """Toda mensagem do teclado: monitor + pitch/modulação mexendo no desenho."""
        self.dock.log_midi(self.inst.describe_midi(kind, ch, num, val))
        ctrl = self.pad_view.ctrl
        if kind == "bend":
            ctrl.set_wheel("pitch", num | (val << 7))
        elif kind == "cc" and num == 1:
            ctrl.set_wheel("mod", val)

    def _unmapped_control(self, ch, cc):
        """Knob girado que não está ligado a nada: avisa (no máximo a cada 6 s)."""
        import time

        now = time.monotonic()
        if now - self._unmapped_at < 6.0:
            return
        self._unmapped_at = now
        self.flash_status(f"Knob (CC {cc}) ainda não ligado: MIDI / Controlador → Só os knobs")

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
        self.engine.sampler.stop_all()              # gravações tocando nos pads
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

    def reopen_midi(self, why):
        """Fecha e abre de novo o teclado MIDI atual. Quando o USB do teclado reinicia (o áudio cai e
        volta, cabo mexido), a conexão antiga fica muda: as teclas param de chegar sem nenhum erro."""
        if self.midi is None:
            return False
        name = self.midi.name or self._midi_lost
        if not name:
            return False
        self.midi.close()
        try:
            self.midi.open(name)
        except RuntimeError:
            self._midi_lost = name                  # ainda não voltou: tenta quando reaparecer
            return False
        self._midi_lost = None
        self.dock.log_midi(f"Teclado MIDI religado ({why}): {name}")
        return True

    def _open_midi(self, name):
        if self.midi is None:
            return
        self._midi_lost = None
        self.midi.close()
        if name and name != NO_MIDI:
            try:
                self.midi.open(name)
            except RuntimeError as exc:
                QMessageBox.warning(self, "MIDI", str(exc))
                self.dock.midi_combo.setCurrentText(NO_MIDI)
                return
            status = self.inst.use_midi_device(name)      # cada controlador com o próprio mapeamento
            self.refresh_sounds()
            if status == "restaurado":
                self.dock.log_midi(f"Mapeamento de “{name}” de volta (pads, knobs e botões dele)")
            elif status == "novo":
                self.dock.log_midi(f"“{name}”: controlador novo, mapeamento padrão")
                if QMessageBox.question(
                        self, "Controlador novo",
                        f"“{name}” ainda não foi mapeado.\n\nOs mapeamentos do controlador anterior não valem "
                        "para ele (eles voltam quando você usar o anterior de novo).\n\n"
                        "Mapear os pads, knobs e botões deste agora?") == QMessageBox.Yes:
                    self.dock.show_tab(2)
                    self.inst.start_learning()

    # ------------------------------------------------------------------ atualização (GitHub)
    def _show_version(self, extra=""):
        sha = updater.local_commit()
        mode = "git" if updater.install_mode() == "git" else "ZIP"
        self.dock.version_label.setText(f"Versão {version_text()} · {sha[:7] or '?'} ({mode})" +
                                        (f"\n{extra}" if extra else ""))

    def check_updates(self, manual=False):
        """Confere o GitHub numa thread; com atualização automática, já baixa e instala."""
        if self._update_thread is not None and self._update_thread.is_alive():
            return
        auto = self.auto_update and not manual
        self.dock.version_label.setText("Procurando atualização…")

        def work():
            try:
                info = updater.check_and_apply(auto=auto)
                self._update_bridge.done.emit(info, "", manual)
            except Exception as exc:  # noqa: BLE001 - rede/GitHub/disco: só avisa
                self._update_bridge.done.emit(None, str(exc), manual)
        self._update_thread = threading.Thread(target=work, daemon=True)
        self._update_thread.start()

    def _update_done(self, info, error, manual):
        if info is None:
            self._show_version("Sem conexão com o GitHub agora." if not manual else f"Erro: {error}")
            if manual:
                QMessageBox.information(self, "Atualizações", f"Não foi possível verificar agora.\n\n{error}")
            return
        if info.notes:                                   # instalou
            self._update_ready(info)
            return
        if info.available:                               # achou, mas só instala com o seu ok
            if QMessageBox.question(self, "Atualização disponível",
                                    f"Nova versão no GitHub: {info.label()}\n{info.message}\n\n"
                                    "Baixar e instalar agora?") == QMessageBox.Yes:
                try:
                    info.notes = updater.apply(info) or ["ok"]
                except Exception as exc:  # noqa: BLE001
                    QMessageBox.warning(self, "Atualizações", f"Não foi possível atualizar:\n{exc}")
                    return
                self._update_ready(info)
            return
        if self._check_stale():
            return
        msg = info.reason or "Você já está com a versão mais nova."
        self._show_version(msg)
        if manual:
            QMessageBox.information(self, "Atualizações", msg)

    def _check_stale(self):
        now = updater.local_commit()
        if self._running_commit and now and now != self._running_commit:
            self.topbar.update_btn.setVisible(True)
            self.topbar.update_btn.setToolTip("Os arquivos do AmpSim já estão numa versão mais nova que a aberta.\n"
                                              "Clique para reiniciar e usar a versão nova.")
            self._show_version("Versão nova já instalada na pasta: reinicie para usar.")
            return True
        return False

    def _update_ready(self, info):
        notes = [n for n in info.notes if n != "ok"]
        self.topbar.update_btn.setVisible(True)
        self.topbar.update_btn.setToolTip(f"Versão {info.label()}: {info.message}\n"
                                          "Clique para reiniciar o AmpSim com a versão nova")
        self._show_version(f"Versão {info.label()} instalada: reinicie para usar." +
                           (" " + " ".join(notes) if notes else ""))
        self.flash_status("Atualização instalada · clique em “Reiniciar para atualizar”")

    def show_about(self):
        from .about import AboutDialog

        AboutDialog(self).exec()

    def restart(self):
        """Fecha (salvando a sessão) e abre de novo, já com a versão nova."""
        cmd, cwd = updater.restart_command()
        flags = 0x00000008 if hasattr(subprocess, "STARTUPINFO") else 0     # DETACHED_PROCESS
        self.close()
        subprocess.Popen(cmd, cwd=cwd, creationflags=flags, close_fds=True)
        QApplication.quit()

    # ------------------------------------------------------------------ aparelhos conectados
    def check_new_devices(self):
        if getattr(self, "_asking", False):             # pergunta aberta: o timer continua rodando
            return
        new_outs, new_midis = self.watcher.poll()
        # o teclado aberto sumiu (USB desligado/reiniciando): religa assim que ele voltar
        current = self.midi.name if self.midi else None
        if current and current not in self.watcher.midis:
            self._midi_lost = current
            self.midi.close()
            self.dock.log_midi(f"Teclado MIDI desconectado: {current}")
            self.flash_status(f"Teclado MIDI desconectado: {current}")
        elif self._midi_lost and self._midi_lost in self.watcher.midis:
            if self.reopen_midi("voltou"):
                self.flash_status(f"Teclado MIDI de volta: {self.midi.name}")
        if new_midis:
            self._reload_midi()
            current = self.midi.name if self.midi else None
            if self.midi is not None and not current:      # nenhum teclado aberto: usa o novo
                self.dock.midi_combo.setCurrentText(new_midis[0])
                self._open_midi(new_midis[0])
                self.flash_status(f"Teclado MIDI conectado: {new_midis[0]}")
        for name in new_outs:
            if name in self._declined_outputs or name == self.engine.config.output_device:
                continue
            self._asking = True
            try:
                use = self.ask_use_output(name)
            finally:
                self._asking = False
            if use:
                self.use_new_output(name)
                return
            self._declined_outputs.add(name)

    def ask_use_output(self, name):
        model = instrument_of(name)
        box = QMessageBox(self)
        box.setWindowTitle("Aparelho de áudio conectado")
        who = f"<b>{model}</b> ({name})" if model else f"<b>{name}</b>"
        box.setText(f"{who} foi conectado e tem saída de áudio.<br><br>"
                    "Quer que o som do AmpSim saia por ele (ex.: a saída P10 / fones do teclado)?")
        use = box.addButton("Usar a saída dele", QMessageBox.AcceptRole)
        box.addButton("Agora não", QMessageBox.RejectRole)
        box.exec()
        return box.clickedButton() is use

    def use_instrument_output(self):
        """Botão "Usar a saída do teclado": procura M-VAVE, PSR-E473 ou VR-730 entre as saídas."""
        from .pad_piano import is_simple

        prefer = None if is_simple(self.inst.device) else self.inst.device
        model, name = find_instrument_output(audio_outputs(), prefer)
        if name:
            self.use_new_output(name)
            return True
        QMessageBox.information(
            self, "Saída do teclado",
            "Nenhum teclado com saída de áudio apareceu no Windows.<br><br>"
            "1. Ligue o teclado no computador pelo cabo USB dele (porta USB TO HOST / COMPUTER).<br>"
            "2. Confira em Configurações do Windows → Som → Saída se ele aparece.<br>"
            "3. Se o fabricante tiver driver próprio de áudio USB para o modelo, instale.<br><br>"
            "Se ele aparecer com outro nome, escolha em <b>Placa de som e driver…</b>. Se não aparecer, "
            "o teclado só manda MIDI e o som continua saindo pela placa do computador.")
        return False

    def use_new_output(self, short_name):
        """Recarrega a lista de placas (o PortAudio só vê aparelhos novos assim) e abre a
        configuração de áudio já com a saída do aparelho escolhida."""
        self.engine.stop()
        dev.refresh()
        self._update_status()
        self.open_audio_dialog(suggest_output=short_name)

    # ------------------------------------------------------------------ áudio
    def toggle_power(self, on):
        if on:
            self._start_audio()
        else:
            self._want_audio = False
            self._reconnect_at = None
            self.engine.stop()
            self._update_status()

    def _start_audio(self):
        cfg = self.engine.config
        if not cfg.output_device:
            self.open_audio_dialog()
            return
        try:
            self.engine.start(cfg)
            self._want_audio = True
            self._reconnect_at = None
            if self.engine.start_notes:
                QMessageBox.information(self, "Áudio ligado com ajustes", "\n\n".join(self.engine.start_notes))
        except Exception as exc:  # noqa: BLE001 - PortAudio pode falhar de muitas formas
            QMessageBox.warning(self, "Erro de áudio",
                                f"Não foi possível abrir o dispositivo:\n\n{exc}\n\n"
                                "Dica: verifique se outro programa está usando a placa "
                                "(no ASIO só um programa por vez) ou tente outra taxa/buffer.")
        self._refresh_all()
        self._update_status()

    def open_audio_dialog(self, suggest_output=None):
        dlg = AudioDialog(self.engine, self, suggest_output=suggest_output)
        if dlg.exec():
            cfg, channels = dlg.result_config()
            self.engine.input_channel.update(channels)
            self.engine.config = cfg
            self._start_audio()
        else:
            self._update_status()

    def watch_audio(self, now):
        """O áudio parou sozinho (cabo USB solto, driver travou)? Avisa e tenta religar a cada 3 s,
        assim que a placa aparecer de novo. Quem desligou no botão não é religado."""
        e = self.engine
        if not self._want_audio or (e.running and not e.lost):
            if self._reconnect_at is not None and e.running:
                self._reconnect_at = None
            return False
        if self._reconnect_at is None:
            self._reconnect_at = now
            self.dock.log_midi("Áudio caiu: tentando religar sozinho")
        self.topbar.set_audio(False, "Áudio caiu", "religando… (confira o cabo USB)", error=True)
        if now < self._reconnect_at:
            return False
        self._reconnect_at = now + 3.0
        cfg = e.config
        try:
            e.stop()
            dev.refresh()                               # enxerga a placa reconectada
            if dev.find_device(cfg.hostapi, cfg.output_device, "output") is None:
                return False
            e.start(cfg)
        except Exception:  # noqa: BLE001 - placa ainda não voltou direito: tenta de novo depois
            return False
        self._reconnect_at = None
        self._refresh_all()
        self._update_status()
        self.flash_status("Áudio religado sozinho")
        self.dock.log_midi("Áudio religado sozinho")
        # o mesmo tropeço no USB costuma derrubar o MIDI do teclado sem avisar
        self.reopen_midi("junto com o áudio")
        return True

    def flash_status(self, text, ms=8000):
        self.topbar.info2.setText(text)
        self.topbar.info2.setToolTip(text)
        QTimer.singleShot(ms, self._update_status)

    def notify(self, text, ms=9000):
        """Aviso que precisa ser lido inteiro: balão por cima da janela (some sozinho ou com um clique) e a
        mesma frase na linha de status."""
        self._toast.show_text(text, ms)
        self.flash_status(text, ms)

    def _update_status(self):
        e = self.engine
        cfg = e.config
        if not e.running:
            line1 = f"{cfg.hostapi or 'Sem driver'} · desligado"
            line2 = cfg.output_device or "clique para escolher a placa"
            for name in ("guitar", "bass", "vocal"):
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
        for name in ("guitar", "bass", "vocal"):
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
        # saída de verdade (depois do master, compressor e limitador) e redução do compressor
        peaks["master"], peaks["comp_gr"] = e.read_output_meter()
        self.dock.update_meters(peaks)
        self.remote.meter(peaks["master"], peaks["comp_gr"])
        self._cpu_tick = getattr(self, "_cpu_tick", 0) + 1
        if self._cpu_tick % 30 == 0:                        # 1x por segundo: o áudio caiu?
            self.watch_audio(time.monotonic())
        if self._cpu_tick % 15 == 0:
            style_badge(self.topbar.health_btn, e)
            self._update_web_btn()
        if self._cpu_tick % 3 == 0 and self.remote.server.clients:     # ~10x por segundo para os aparelhos
            self.remote.push()
        if e.running and self._cpu_tick % 15 == 0:          # 2x por segundo basta
            cfg = e.config
            _, _, total = e.latency_ms()
            self.topbar.info2.setText(f"Buffer {cfg.blocksize} · {total:.1f} ms · CPU {e.cpu_load() * 100:.0f}%")
            self.topbar.power.setToolTip(f"Áudio ligado · CPU {e.cpu_load() * 100:.0f}% · falhas {e.xruns}\n"
                                         "Clique para desligar")

    # ------------------------------------------------------------------ tela remota
    def open_webserver(self):
        WebServerDialog(self.remote, self).exec()
        self._update_web_btn()

    def _update_web_btn(self):
        srv = self.remote.server
        urls = srv.urls()
        self.topbar.set_web(srv.running, len([c for c in list(srv.clients) if c.telas is not None]),
                            urls[0] if urls else "")

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
                if name == "vocal":             # a cena não liga nem desliga o microfone
                    cur = e.tracks["vocal"].values["track"]
                    tr = ts.setdefault("values", {}).setdefault("track", {})
                    for k in ("on", "mute"):
                        tr[k] = cur[k]
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
        st = _as_dict(storage.load_state())     # state.json estragado (lista, número...): começa do padrão
        e = self.engine
        audio = _as_dict(st.get("audio"))
        cfg = dev.AudioConfig.from_dict(audio) if audio else dev.default_config()
        e.config = cfg
        e.input_channel.update({k: v for k, v in _as_dict(st.get("input_channel")).items()
                                if k in e.input_channel and _int_in(v, 0, 63, None) is not None})
        tracks = _as_dict(st.get("tracks"))
        for name in TRACKS:
            if isinstance(tracks.get(name), dict):
                e.tracks[name].load_state(tracks[name])
            else:
                self.track_pages[name].apply_preset_data(FACTORY[name][DEFAULT_PRESET[name]])
        pads = e.tracks["pads"]
        if "use_amp" not in _as_dict(_as_dict(_as_dict(tracks.get("pads")).get("values")).get("track")):
            pads.set_param("track", "use_amp", False)      # teclas limpas por padrão
        e.instruments.load_state(_clean_like(_as_dict(st.get("instruments")), e.instruments.get_state()))
        if isinstance(st.get("synth"), dict):
            e.synth.load_state(st["synth"])
        master = st.get("master_db", 0.0)
        self.set_master_db(master if isinstance(master, (int, float)) and not isinstance(master, bool) else 0.0)
        kb = _as_dict(st.get("keyboard"))
        self.kbd.octave = _int_in(kb.get("octave"), 0, 8, 4)
        self.kbd.velocity = _int_in(kb.get("velocity"), 1, 127, 100)
        self.dock.kbd_enable.setChecked(kb.get("enabled", True) is not False)
        ui = _as_dict(st.get("ui"))
        self.shortcuts.set_keys(ui.get("shortcuts"))
        self.auto_update = ui.get("auto_update", True) is not False
        self.dock.auto_update.setChecked(self.auto_update)
        if ui.get("layout") != 2:
            e.instruments.device = "Teclado simples"      # 1ª vez no visual novo: teclado + knobs
        if isinstance(ui.get("dock_collapsed"), dict):
            self._dock_by_page.update({k: bool(v) for k, v in ui["dock_collapsed"].items()
                                       if k in self._dock_by_page})
        if isinstance(ui.get("dock_tab"), int) and 0 <= ui["dock_tab"] < 4:
            self.dock.stack.setCurrentIndex(ui["dock_tab"])
        self.pad_view.user_preset = ui.get("keys_user", "") if isinstance(ui.get("keys_user"), str) else ""
        self.panels.restore(ui.get("janela"))           # subjanelas: posição, tamanho, visíveis e travadas
        tab = st.get("tab", 2)
        self.tabs.setCurrentIndex(tab if _int_in(tab, 0, len(PAGE_ORDER) - 1, None) is not None else 2)
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
            "midi_input": (self.midi.name or self._midi_lost) if self.midi else None,
            "tab": self.tabs.currentIndex(),
            "running": e.running,
            "ui": {"layout": 2, "auto_update": self.auto_update,
                   "dock_collapsed": dict(self._dock_by_page), "dock_tab": self.dock.stack.currentIndex(),
                   "keys_user": self.pad_view.user_preset, "shortcuts": dict(self.shortcuts.keys),
                   "janela": self.panels.save()},
        })

    def autostart(self):
        if self._autostart and self.engine.config.output_device:
            self._start_audio()

    def closeEvent(self, ev):
        self.hotplug_timer.stop()
        self.remote.stop()
        self.stale_timer.stop()
        self.save_state()
        if self.midi:
            self.midi.close()
        self.engine.stop()
        from ..audio import vst
        vst.host().shutdown()               # fecha o painel de plugin aberto e destrói os plugins trocados
        super().closeEvent(ev)


def _as_dict(x):
    """Pedaço do state.json que deveria ser um dicionário (estragado: vazio, e vale o padrão)."""
    return x if isinstance(x, dict) else {}


def _int_in(x, lo, hi, default):
    return x if isinstance(x, int) and not isinstance(x, bool) and lo <= x <= hi else default


def _clean_like(d, ref):
    """Tira de `d` os campos que deveriam ser dicionário/lista (como em `ref`) e não são (state.json
    estragado, ex. instruments.keys = 3): esses ficam no padrão."""
    out = {}
    for k, v in d.items():
        r = ref.get(k)
        if isinstance(r, dict) and not isinstance(v, dict):
            continue
        if isinstance(r, list) and not isinstance(v, list):
            continue
        out[k] = v
    return out
