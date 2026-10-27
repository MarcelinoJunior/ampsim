"""Liga o servidor da tela remota ao AmpSim: comandos da página viram as mesmas ações da tela, e o
estado do AmpSim (pads, faders, setlist, BPM...) vai para a página."""
from PySide6.QtCore import QObject, Signal

from ..instruments import CONT_PAD_SOUNDS, KEY_NAMES, PAD_COUNT
from . import config as wcfg
from .server import WebServer


class Remote(QObject):
    command = Signal(object)            # comando para a thread da interface

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.server = WebServer(self._from_server, self.state)
        self.command.connect(self.apply)
        self.cfg = wcfg.load()

    # ------------------------------------------------------------------ ligar / desligar
    def start(self, host="0.0.0.0", port=None):
        ok = self.server.start(self.cfg, host, port)
        if ok:
            self.push()
        return ok

    def stop(self):
        self.server.stop()

    def set_config(self, cfg, host="0.0.0.0"):
        """Configuração nova (janela Webserver): salva, liga/desliga ou reinicia se mudou a porta."""
        old = self.cfg
        self.cfg = cfg
        wcfg.save(cfg)
        if not cfg["ligado"]:
            self.stop()
            return True
        if not self.server.running or old["porta"] != cfg["porta"]:
            return self.start(host)
        self.server.update_config(cfg)
        self.push()
        return True

    # ------------------------------------------------------------------ comandos
    def _from_server(self, msg, telas):
        """Thread do servidor: pad de bateria toca direto (o caminho mais curto, como o MIDI);
        o resto vai para a thread da interface."""
        if msg.get("c") == "pad":
            i = int(msg.get("i", -1))
            if 0 <= i < PAD_COUNT:
                vel = max(1, min(127, int(msg.get("vel", 110))))
                self.win.engine.instruments.pad_hit(i, vel)
            return
        self.command.emit(msg)

    def apply(self, msg):
        win = self.win
        inst = win.engine.instruments
        c = msg.get("c")
        if c == "pad_cont":
            key = msg.get("tom")
            if key in KEY_NAMES:
                if key == inst.cont_key:
                    inst.stop_cont_pad()
                else:
                    inst.start_cont_pad(key)
        elif c == "pad_parar":
            inst.stop_cont_pad()
        elif c == "pad_timbre":
            if msg.get("nome") in CONT_PAD_SOUNDS:
                inst.set_cont_sound(msg["nome"])
        elif c == "fader":
            target = self._strip(msg.get("id"))
            if target is not None:
                v = max(0, min(100, int(msg.get("valor", 0))))
                win.dock._mix(target, v)
                # arrastar o fader manda muitos comandos: só os volumes da tela acompanham (como um knob)
                if not win._knob_sync.isActive():
                    win._knob_sync.start()
                self.push()
            return
        elif c == "mute":
            target = self._strip(msg.get("id"))
            if target is not None and target[0] == "func" and target[1] in win.dock.mute_buttons:
                win.dock._mute(target[1], bool(msg.get("on")))
        elif c == "musica":
            win.setlist.load_song(int(msg.get("i", -1)))
        elif c == "musica_passo":
            win.setlist.step(1 if int(msg.get("d", 1)) > 0 else -1)
        elif c == "setlist":
            win.setlist.choose_list(str(msg.get("nome", "")))
        elif c == "tap":
            inst.tap_tempo()
        elif c == "click":
            m = win.engine.metronome
            if bool(msg.get("on")) != m.on:
                inst.do_button("Metrônomo liga/desliga")
        elif c == "bpm":
            inst.set_bpm(float(msg.get("valor", inst.bpm)))
        elif c == "mute_geral":
            win.toggle_mute_all(bool(msg.get("on")))
        elif c == "panico":
            win.panic()
        elif c == "preset_passo":
            # a tela "Timbre atual" é a do Pad/Piano: troca o preset dele sem mudar a aba do PC
            page = win.tabs.currentIndex()
            win.preset_step(1 if int(msg.get("d", 1)) > 0 else -1, kind="pads")
            win.tabs.setCurrentIndex(page)
        else:
            return
        win.refresh_sounds()
        self.push()

    def _strip(self, sid):
        for (kind, arg), *_ in self.win.dock.strips:
            if arg == sid:
                return kind, arg
        return None

    # ------------------------------------------------------------------ estado
    def push(self):
        if self.server.running:
            self.server.publish(self.state())

    def state(self):
        from ..ui.dock import STRIPS, VOL_RANGE
        from ..ui.funcs import FUNC_RANGES, func_value
        from ..ui.recorder import pad_label
        win = self.win
        e = win.engine
        inst = e.instruments
        faders = []
        count = inst.layer_count()
        for label, kind, arg, layer, mutable in STRIPS:
            if kind == "track":
                lo, hi = VOL_RANGE
                v = (e.tracks[arg].values["track"]["volume"] - lo) / (hi - lo) * 100
            else:
                _, lo, hi, _ = FUNC_RANGES[arg]
                v = (func_value(e, arg) - lo) / (hi - lo) * 100
            faders.append({"id": arg, "nome": label.replace("\n", " "), "valor": round(v),
                           "mudo": arg in inst.mutes, "pode_mutar": mutable,
                           "ativo": layer is None or layer <= count})
        sl = win.setlist
        songs = sl.songs_list()
        m = e.metronome
        k = inst.keys
        layers = [k["sound1"]] + ([k["sound2"]] if k["sound2"] and k["layer2_on"] else []) \
            + [x["sound"] for x in inst.extra_layers if x.get("on", True)]
        return {
            "pads": {"tons": list(KEY_NAMES), "tom": inst.cont_key, "timbre": inst.cont_sound,
                     "timbres": [{"nome": n, "curto": n.replace("Pad ", "")} for n in CONT_PAD_SOUNDS],
                     "bateria": [{"i": i, "nome": pad_label(inst.pad_sounds[i])} for i in range(PAD_COUNT)],
                     "segue": inst.pad_follow},
            "faders": {"canais": faders},
            "setlist": {"listas": list(sl.data["listas"]), "atual": sl.data["atual"], "tocando": sl.current,
                        "musicas": [{"nome": s["nome"], "tom": s["som"].get("pad_tom")} for s in songs]},
            "tempo": {"bpm": inst.bpm, "click": m.on, "click_saida": e.click_offset != -2,
                      "compasso": m.beats, "batida": m.count if m.on else 0},
            "emergencia": {"mudo": e.muted, "audio": e.running},
            "timbre": {"preset": win.pad_view.title.text(), "camadas": layers,
                       "audio": e.running},
        }
