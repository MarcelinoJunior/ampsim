"""Liga o servidor da tela remota ao AmpSim: comandos da página viram as mesmas ações da tela, e o
estado do AmpSim (pads, faders, setlist, guitarra, baixo...) vai para a página."""
import math
import re
import time

from PySide6.QtCore import QObject, QTimer, Signal

from ..audio import sampler as smp
from .. import storage
from ..audio.sampler import MAX_SECONDS, REC_PREFIX
from ..dsp.params import CAB_IR_INDEX, EFFECTS, TRACK_PARAMS
from ..instruments import (
    CATEGORIES, CONT_PAD_SOUNDS, KEY_NAMES, MAX_LAYERS, PAD_CATEGORIES, PAD_COUNT, PAD_SOUND_BY_NAME, PAD_SOUNDS,
    SOUND_BY_NAME, SOUNDS,
)
from ..presets import FACTORY
from . import config as wcfg
from .server import TRACK_PANEL, WebServer

PAD_VOLUMES = ("Volume pad contínuo", "Volume bateria")
# faders só da tela remota (a barra de baixo do PC não tem lugar): mesma função de knob do MIDI
WEB_FADERS = (("Compressor", "Compressor"),)
# pedais que dá para mexer pelo celular (captura NAM e plugin VST dependem de arquivos escolhidos no PC)
REMOTE_EFFECTS = tuple(e for e in EFFECTS if e.key not in ("nam", "vst"))
REMOTE_FX = {e.key: e for e in REMOTE_EFFECTS}
FX_SHORT = {"denoise": "Ruído", "gate": "Gate", "comp": "Comp", "overdrive": "Drive", "amp": "Amp",
            "cab": "Gabinete", "eq": "EQ", "chorus": "Chorus", "delay": "Delay", "reverb": "Reverb"}
TRACK_VOL = next(p for p in TRACK_PARAMS if p.key == "volume")
NAME_MAX = 60
TRACK_COMMANDS = ("trilha_preset_passo", "trilha_preset", "trilha_volume", "trilha_on", "efeito_on", "efeito_param",
                  "trilha_salvar")


def to_norm(p, v):
    """Valor do parâmetro -> 0..1 (como o knob da tela: log nos parâmetros de frequência/tempo)."""
    if p.log and p.lo > 0:
        t = math.log(max(v, p.lo) / p.lo) / math.log(p.hi / p.lo)
    else:
        t = (v - p.lo) / (p.hi - p.lo)
    return min(max(t, 0.0), 1.0)


def from_norm(p, t):
    t = min(max(t, 0.0), 1.0)
    v = p.lo * (p.hi / p.lo) ** t if (p.log and p.lo > 0) else p.lo + (p.hi - p.lo) * t
    if p.step:
        v = round(v / p.step) * p.step
    return min(max(v, p.lo), p.hi)


def _num(v):
    """Número de um comando, ou None (texto, lista, booleano, NaN e infinito não valem: o comando é ignorado)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    v = float(v)
    return v if math.isfinite(v) else None


def _int(v):
    """Inteiro de um comando (ex. 3 ou 3.0), ou None."""
    v = _num(v)
    return int(v) if v is not None and v == int(v) and abs(v) < 1e9 else None


def _str(v):
    return v if isinstance(v, str) else None


def _step(v):
    """Direção de ◀ ▶ (+1 / -1), ou None."""
    v = _num(v)
    return None if v is None or v == 0 else (1 if v > 0 else -1)


RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"{p}{i}" for p in ("COM", "LPT") for i in range(1, 10)}


def clean_name(v):
    """Nome de preset/setup vindo do celular: caracteres de controle viram um espaço (espaços repetidos
    viram um só), sem espaço/ponto nas pontas,
    até 60 letras e nada que o Windows recuse como nome de arquivo. "" = inválido."""
    if not isinstance(v, str):
        return ""
    v = re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", v)           # quebra de linha, tab... viram espaço
    v = re.sub(r"\s+", " ", v).strip().strip(".").strip()[:NAME_MAX].strip()
    if v.upper().split(".")[0] in RESERVED:
        v = "_" + v
    return v


class Remote(QObject):
    command = Signal(object)            # comando para a thread da interface

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.server = WebServer(self._from_server, self.state)
        self.command.connect(self.apply)
        self.cfg = wcfg.load()
        self._recs = ([], 0.0)              # gravações do banco (lidas da pasta no máximo a cada 2 s)
        self._sounds = (None, 0.0)          # catálogo de timbres (o piano baixado aparece em até 2 s)
        # arrastar um fader de pedal manda muitos comandos: a aba do PC acompanha no máximo ~15x/s
        self._dirty_tracks = set()
        self._track_sync = QTimer(self)
        self._track_sync.setSingleShot(True)
        self._track_sync.setInterval(66)
        self._track_sync.timeout.connect(self._sync_tracks)
        self._rec_by = None                 # aparelho que começou a gravação (recebe o aviso dos 60 s)
        rec = getattr(win, "dock", None) and win.dock.recorder
        if rec is not None:
            rec.on_auto_stop = self._rec_auto_stopped

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
            i, vel = _int(msg.get("i")), _num(msg.get("vel", 110))
            if i is not None and 0 <= i < PAD_COUNT:
                vel = 110 if vel is None else int(max(1, min(127, vel)))
                self.win.engine.instruments.pad_hit(i, vel)
            return
        self.command.emit(msg)

    def apply(self, msg):
        """Thread da interface. Cada campo é conferido: tipo errado, NaN ou valor fora da lista = ignora."""
        win = self.win
        inst = win.engine.instruments
        c = msg.get("c")
        if c == "pad_cont":
            key = _str(msg.get("tom"))
            if key not in KEY_NAMES:
                return
            if key == inst.cont_key:
                inst.stop_cont_pad()
            else:
                inst.start_cont_pad(key)
        elif c == "pad_parar":
            inst.stop_cont_pad()
        elif c == "pad_timbre":
            nome = _str(msg.get("nome"))
            if nome not in CONT_PAD_SOUNDS:
                return
            inst.set_cont_sound(nome)
        elif c in ("fader", "pad_volume"):
            # pad_volume: os 2 faders da aba Pads (quem só vê os pads também ajusta o volume deles)
            sid, v = _str(msg.get("id")), _num(msg.get("valor"))
            if sid is None or v is None or (c == "pad_volume" and sid not in PAD_VOLUMES):
                return
            v = max(0.0, min(100.0, v))
            if c == "fader" and sid in dict(WEB_FADERS):
                from ..ui.funcs import set_func
                set_func(win.engine, sid, v)
            else:
                target = self._strip(sid)
                if target is None:
                    return
                win.dock._mix(target, int(round(v)))
            # arrastar o fader manda muitos comandos: só os volumes da tela acompanham (como um knob)
            if not win._knob_sync.isActive():
                win._knob_sync.start()
            self.push()
            return
        elif c in ("mute", "pad_mute"):
            sid, on = _str(msg.get("id")), msg.get("on")
            if sid is None or not isinstance(on, bool) or (c == "pad_mute" and sid not in PAD_VOLUMES):
                return
            target = self._strip(sid)
            if target is None or target[0] != "func" or target[1] not in win.dock.mute_buttons:
                return
            win.dock._mute(target[1], on)
        elif c == "musica":
            i = _int(msg.get("i"))
            if i is None or not 0 <= i < len(win.setlist.songs_list()):
                return
            win.setlist.load_song(i)
        elif c == "musica_passo":
            d = _step(msg.get("d"))
            if d is None:
                return
            win.setlist.step(d)
        elif c == "setlist":
            nome = _str(msg.get("nome"))
            if nome is None or nome not in win.setlist.data["listas"]:
                return
            win.setlist.choose_list(nome)
        elif c in TRACK_COMMANDS:
            name = msg.get("trilha")
            if isinstance(name, str) and name in TRACK_PANEL:
                self._track_command(c, name, msg)
                self.push()
            return
        elif c == "timbre_salvar":
            nome = clean_name(msg.get("nome"))
            if not nome:
                self.tell(msg, "Digite um nome para o setup")
                return
            # mesmo caminho do 💾 do PC, sem a janela de nome (ela abriria no PC, longe do músico)
            try:
                saved = win.save_keys_preset(nome)
            except (OSError, ValueError) as exc:
                self.tell(msg, f"Não deu para salvar: {exc}")
                return
            self.tell(msg, f"Setup salvo: {saved}")
        elif c == "pad_som":
            i, nome = _int(msg.get("i")), _str(msg.get("nome"))
            if i is None or nome is None or not 0 <= i < PAD_COUNT:
                return
            ok = nome in PAD_SOUND_BY_NAME or (nome.startswith(REC_PREFIX) and nome[len(REC_PREFIX):] in self.recordings())
            if not ok:
                return
            inst.set_pad_sound(i, nome)
        elif c == "rec":
            why = win.dock.recorder.start(quiet=True)
            if why:
                self.tell(msg, why)
            else:
                self._rec_by = msg.get("_c")
        elif c == "rec_parar":
            rec = win.dock.recorder
            if win.engine.recorder.active:
                name = rec.stop(quiet=True)
                self._recs = ([], 0.0)
                self._rec_by = None
                self.tell(msg, f"Gravado: {name}" if name else "Nada gravado: só chegou silêncio")
            else:
                win.engine.sampler.stop_all()          # STOP sem gravar: para o que está tocando (e o loop)
        elif c == "rec_ouvir":
            names = self.recordings()
            nome = msg.get("nome")
            if nome is not None and not isinstance(nome, str):
                return
            nome = nome or win.dock.recorder.current() or (names[-1] if names else "")
            if nome not in names:
                return
            loop = msg.get("loop")
            if loop is True:
                # 2º toque no PLAY (duplo toque): a gravação que já começou passa a repetir até o STOP
                win.engine.sampler.loop(nome, 110)
            elif loop is None or loop is False:
                if win.engine.sampler.looping:
                    win.engine.sampler.stop_all()      # um toque com loop tocando: para o loop e toca 1 vez
                win.dock.recorder.preview(nome)
            else:
                return
        elif c == "timbre_camada":
            n, nome = _int(msg.get("camada")), _str(msg.get("nome"))
            if n is None or nome not in SOUND_BY_NAME:
                return
            count = inst.layer_count()
            if n in (1, 2):
                if n == 2:
                    inst.keys["layer2_on"] = True        # escolheu um timbre para a L2: ela toca
                inst.set_sound(n, nome)
            elif 3 <= n <= count:
                inst.set_extra_layer(n, sound=nome, on=True)
            elif n == count + 1 and n <= MAX_LAYERS:
                inst.add_layer(nome)
            else:
                return
            win.pad_view.user_preset = ""
            if inst.pack_missing(nome):
                self.tell(msg, "Este piano ainda não foi baixado: toca o Piano de Cauda até baixar no PC "
                               "(menu ☰ → Timbres adicionais)")
        elif c == "timbre_l2":
            # liga/desliga a L2 como o interruptor da L2 no PC (o timbre dela fica guardado)
            on = msg.get("on")
            if not isinstance(on, bool):
                return
            mode2 = inst.keys.get("mode2")
            win.pad_view.set_key_mode(("split" if mode2 == "split" else "layer") if on else "single")
        elif c == "timbre_remover":
            n = _int(msg.get("camada"))
            if n is None or not 3 <= n <= inst.layer_count():
                return
            inst.remove_layer(n)                    # L3/L4 (L1 e L2 não saem: a L2 só desliga)
            win.pad_view.user_preset = ""
        elif c == "preset_passo":
            d = _step(msg.get("d"))
            if d is None:
                return
            # a tela "Timbre atual" é a do Pad/Piano: troca o preset dele sem mudar a aba do PC
            page = win.tabs.currentIndex()
            win.preset_step(d, kind="pads")
            win.tabs.setCurrentIndex(page)
        else:
            return
        win.refresh_sounds()
        self.push()

    def _track_command(self, c, name, msg):
        """Telas Guitarra e Baixo: os mesmos controles da aba da trilha no PC (sem trocar a aba)."""
        win = self.win
        page = win.track_pages[name]
        track = page.track()
        if c == "trilha_preset_passo":
            d = _step(msg.get("d"))
            if d is None:
                return
            page.preset_step(d)
        elif c == "trilha_preset":
            kind, n = _str(msg.get("tipo")), _str(msg.get("nome"))
            if kind not in ("factory", "user") or n is None:
                return
            page.load_preset(kind, n)               # só carrega o que está na lista da aba
        elif c == "trilha_volume":
            v = _num(msg.get("valor"))
            if v is None:
                return
            v = min(max(v, 0.0), 100.0)
            track.set_param("track", "volume", TRACK_VOL.lo + (TRACK_VOL.hi - TRACK_VOL.lo) * v / 100)
            self._mark(name)
            return
        elif c == "trilha_on":
            on = msg.get("on")
            if not isinstance(on, bool):
                return
            track.set_param("track", "on", on)
        elif c == "efeito_on":
            eff, on = _str(msg.get("efeito")), msg.get("on")
            if eff not in REMOTE_FX or not isinstance(on, bool):
                return
            track.set_on(eff, on)
        elif c == "efeito_param":
            eff = REMOTE_FX.get(_str(msg.get("efeito")) or "")
            key = _str(msg.get("param"))
            p = next((p for p in eff.params if p.key == key), None) if eff else None
            v = _num(msg.get("valor"))
            if p is None or v is None:
                return
            if p.is_choice:
                top = len(p.choices) - 1
                if eff.key == "cab" and not track.ir_path:
                    top = CAB_IR_INDEX - 1          # IR de arquivo: só escolhendo o .wav no PC
                v = float(min(max(int(v), 0), top))
            else:
                v = from_norm(p, v / 100)
            track.set_param(eff.key, p.key, v)
            self._mark(name)
            return
        elif c == "trilha_salvar":
            nome = clean_name(msg.get("nome"))
            if not nome:
                self.tell(msg, "Digite um nome para o preset")
                return
            try:
                page.save_preset_as(nome)
            except (OSError, ValueError) as exc:
                self.tell(msg, f"Não deu para salvar: {exc}")
                return
            win.bank.reload()
            self.tell(msg, f"Salvo: {storage._safe(nome)}")      # o nome como ficou na lista
        else:
            return
        win.refresh_track(name)
        win._sync_bank()

    def _rec_auto_stopped(self, name):
        """O gravador parou sozinho nos 60 s: avisa o aparelho que começou a gravação."""
        self._recs = ([], 0.0)
        by, self._rec_by = self._rec_by, None
        if by is not None:
            self.server.tell(by, f"Gravação parou no limite de {MAX_SECONDS} s: {name}" if name
                             else "Gravação parou no limite: só chegou silêncio")

    def _mark(self, name):
        self._dirty_tracks.add(name)
        if not self._track_sync.isActive():
            self._track_sync.start()

    def _sync_tracks(self):
        for name in self._dirty_tracks:
            self.win.refresh_track(name)
        self._dirty_tracks = set()
        self.win.dock.refresh_levels()

    def tell(self, msg, text):
        c = msg.get("_c")
        if c is not None:
            self.server.tell(c, text)

    def recordings(self):
        names, at = self._recs
        if time.monotonic() - at > 2.0:
            names = smp.list_recordings()
            self._recs = (names, time.monotonic())
        return names

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
            if arg == "Master":
                for func, label in WEB_FADERS:               # logo depois do Master
                    faders.append({"id": func, "nome": label, "valor": round(func_value(e, func)), "mudo": False,
                                   "pode_mutar": False, "ativo": True})
        sl = win.setlist
        songs = sl.songs_list()
        k = inst.keys
        layers = [k["sound1"]] + ([k["sound2"]] if k["sound2"] and k["layer2_on"] else []) \
            + [x["sound"] for x in inst.extra_layers if x.get("on", True)]
        rec = e.recorder
        recs = self.recordings()
        out = {
            "pads": {"tons": list(KEY_NAMES), "tom": inst.cont_key, "timbre": inst.cont_sound,
                     "timbres": [{"nome": n, "curto": n.replace("Pad ", "")} for n in CONT_PAD_SOUNDS],
                     "bateria": [{"i": i, "nome": pad_label(inst.pad_sounds[i]), "som": inst.pad_sounds[i]}
                                 for i in range(PAD_COUNT)],
                     "segue": inst.pad_follow},
            "pads.gravador": {"gravando": rec.active, "segundos": round(rec.seconds, 1) if rec.active else 0,
                              "gravacoes": recs, "atual": win.dock.recorder.current(), "audio": e.running,
                              "loop": e.sampler.looping},
            "pads.sons": self._pad_catalog(recs),
            "faders": {"canais": faders},
            "pads.volumes": [dict(f, nome="Volume do pad contínuo" if f["id"] == PAD_VOLUMES[0] else "Volume dos pads")
                             for f in faders if f["id"] in PAD_VOLUMES],
            "setlist": {"listas": list(sl.data["listas"]), "atual": sl.data["atual"], "tocando": sl.current,
                        "musicas": [{"nome": s["nome"], "tom": s["som"].get("pad_tom")} for s in songs]},
            "timbre": {"preset": win.pad_view.title.text(), "camadas": layers,
                       "lista": [{"n": n, "som": s, "ligada": on} for n, s, on in inst.layer_sounds()],
                       "max": MAX_LAYERS, "audio": e.running,
                       "nome_salvar": win.pad_view.user_preset or inst.ready or "Meu timbre",
                       "meus": self._keys_user_presets()},
            "timbre.sons": self._sound_catalog(),
        }
        for name, panel in TRACK_PANEL.items():
            out[panel] = self._track_state(name)
            out[panel + ".presets"] = self._track_presets(name)
        return out

    def _track_state(self, name):
        from ..ui.widgets import fmt_value
        page = self.win.track_pages[name]
        t = page.track()
        tv = t.values["track"]
        fx = []
        for eff in REMOTE_EFFECTS:
            vals = t.values[eff.key]
            params = []
            for p in eff.params:
                v = vals.get(p.key, p.default)
                if p.is_choice:
                    # no celular só o nome do modelo (o "(estilo …)" do PC não cabe na lista)
                    opts = [ch.split("  (estilo")[0] for ch in p.choices]
                    if eff.key == "cab" and not t.ir_path and int(round(v)) != CAB_IR_INDEX:
                        opts = opts[:CAB_IR_INDEX]
                    params.append({"k": p.key, "nome": p.label, "i": int(round(v)), "opcoes": opts})
                else:
                    params.append({"k": p.key, "nome": p.label, "valor": round(to_norm(p, v) * 100),
                                   "txt": fmt_value(p, v)})
            fx.append({"k": eff.key, "nome": eff.title, "curto": FX_SHORT.get(eff.key, eff.title),
                       "on": bool(vals.get("on")), "params": params})
        data = page.preset.currentData()
        vol = tv["volume"]
        # captura NAM (amp real) escolhida no PC: aparece acesa, só para ver (o Amp por cima soma os dois)
        nam = t.values.get("nam", {})
        nam_on = bool(nam.get("on") and nam.get("file"))
        return {"preset": page.preset.currentText() or "—", "atual": ":".join(data) if data else "",
                "nome_salvar": data[1] if data else "Meu preset",
                "volume": round(to_norm(TRACK_VOL, vol) * 100),
                "txt": "-∞ dB" if vol <= TRACK_VOL.lo + 0.05 else fmt_value(TRACK_VOL, vol),
                "on": bool(tv["on"]), "efeitos": fx, "audio": self.win.engine.running,
                "nam": str(nam.get("file")) if nam_on else ""}

    def _keys_user_presets(self):
        """Nomes em "Meus timbres" (para o celular avisar antes de salvar por cima de um)."""
        c = self.win.ready_combo
        return [d[1] for d in (c.itemData(i) for i in range(c.count())) if d and d[0] == "keys_user"]

    def _track_presets(self, name):
        """Presets da aba (★ de fábrica e os do usuário), no formato da lista que sobe de baixo."""
        # a lista da aba no PC já é a dos arquivos (relida ao salvar/excluir): sem ler a pasta 10x por segundo
        combo = self.win.track_pages[name].preset
        user = [d[1] for d in (combo.itemData(i) for i in range(combo.count())) if d and d[0] == "user"]
        out = [{"cat": "Meus presets", "sons": [{"nome": "user:" + n, "curto": n} for n in user]}] if user else []
        out.append({"cat": "De fábrica", "sons": [{"nome": "factory:" + n, "curto": "★ " + n}
                                                  for n in FACTORY.get(name, {})]})
        return out

    def _pad_catalog(self, recs):
        """Sons que dá para pôr num pad: gravações do banco e os sons de bateria por categoria."""
        out = [{"cat": "Gravações", "sons": [{"nome": REC_PREFIX + r, "curto": "● " + r} for r in recs]}] if recs else []
        for cat in PAD_CATEGORIES:
            out.append({"cat": cat, "sons": [{"nome": s.name, "curto": s.name} for s in PAD_SOUNDS if s.cat == cat]})
        return out

    def _sound_catalog(self):
        """Timbres das camadas por categoria; pianos gravados não baixados vêm marcados."""
        cat_list, at = self._sounds
        if cat_list is None or time.monotonic() - at > 2.0:
            inst = self.win.engine.instruments
            cat_list = [{"cat": cat, "sons": [{"nome": s.name, "falta": bool(s.pack and inst.pack_missing(s.name))}
                                              for s in SOUNDS if s.cat == cat]} for cat in CATEGORIES]
            self._sounds = (cat_list, time.monotonic())
        return cat_list
