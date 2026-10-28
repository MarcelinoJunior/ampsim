"""Controlador MIDI nas abas Guitarra, Baixo e Vocal e nos plugins VST3 (o Pad/Piano tem o seu em
instruments.py: knobs/botões/pads e os atalhos `free_map`).

Cada controle mapeável tem um identificador estável (o mesmo da propriedade Qt "ctrl_id" das telas):
    "<trilha>/<efeito>/<parâmetro>"   trilha = guitar, bass ou vocal (ex.: "guitar/delay/mix")
    "<trilha>/<efeito>/on"            liga/desliga do pedal
    "<trilha>/track/on|volume|pan…"   a trilha (Vocal também mute, phase e plug_pos)
    "<trilha>/preset/prev|next"       preset anterior/próximo da aba
    "fx/<cadeia>/<n>/on|mix"          plugin n (1-4) de uma cadeia FX (L1-L4, master, guitar, bass, vocal)
    "fx/<cadeia>/<n>/param:<nome>"    parâmetro interno do plugin (nome do parâmetro no plugin)

Os mapeamentos ficam em Instruments.ctl_map: {id: {"key": [tipo, canal, nº], "label": texto,
"plugin": "vst3:Nome.vst3" (só fx), "param": nome (só parâmetro)}}. Vão na sessão e no perfil de cada
controlador (como o free_map). O mapeamento é global: vale em qualquer aba.

Threads: a mensagem MIDI chega na thread do winmm. ControlMap.post só guarda o valor (um knob girando
vira um valor só por ciclo: coalescência) e chama `wake`; a janela principal aplica tudo na thread da
interface (flush), pelo mesmo caminho da tela. Sem janela (testes, `wake` None) aplica na hora.
Parâmetros de plugin vão para PluginSlot.set_param (thread dos plugins, também com coalescência).

Microfone: "vocal/track/on" pode ser mapeado (é ação explícita no controlador), mas nada aqui liga a
trilha ao abrir sessão ou preset: só o toque no controle mapeado.
"""
import threading

from .dsp.params import EFFECT_BY_KEY, EFFECTS, Param, TRACK_PARAMS
from .dsp.vocal import PLUG_POS_PARAM, TRACK_SWITCHES, VOCAL_EFFECT_BY_KEY, VOCAL_EFFECTS, VOCAL_TRACK_PARAMS

TRACKS = ("guitar", "bass", "vocal")
TRACK_NAMES = {"guitar": "Guitarra", "bass": "Baixo", "vocal": "Vocal"}
CHAINS = ("L1", "L2", "L3", "L4", "master", "guitar", "bass", "vocal")
CHAIN_NAMES = {"L1": "Layer 1", "L2": "Layer 2", "L3": "Layer 3", "L4": "Layer 4", "master": "Master",
               "guitar": "Guitarra", "bass": "Baixo", "vocal": "Vocal"}
GROUPS = ("Pad/Piano", "Guitarra", "Baixo", "Vocal", "Plugins")
KINDS = ("cc", "note", "pc")
# controles das trilhas que não são mapeáveis: o modelo do amp é o seletor (amp/captura/plugin), arquivos
SKIP = {("amp", "model")}
# Botão por CC: "momentâneo" manda um valor alto ao apertar e 0 ao soltar (só o valor alto alterna, segure o
# quanto quiser); "que trava" manda alto num toque e 0 no seguinte (cada mensagem alterna). O tipo fica no
# mapeamento ("latch": True); sem o campo (mapeamentos antigos) é momentâneo. Vale também no Pad/Piano.
MIX_PARAM = Param("mix", "Mix", 0, 100, 100, "%")
TRACK_TOGGLE_NAMES = {"on": "Liga/desliga", "mute": "Mudo", "phase": "Inverter fase"}


# ------------------------------------------------------------------ o que cada id controla
def _effects(track):
    return VOCAL_EFFECT_BY_KEY if track == "vocal" else EFFECT_BY_KEY


def track_param(track, effect, key):
    """Param (dsp/params.py) de um controle de trilha, ou None."""
    if effect == "track":
        if track == "vocal" and key == "plug_pos":
            return PLUG_POS_PARAM
        for p in (VOCAL_TRACK_PARAMS if track == "vocal" else TRACK_PARAMS):
            if p.key == key:
                return p
        return None
    eff = _effects(track).get(effect)
    if eff is None or (effect, key) in SKIP:
        return None
    for p in eff.params:
        if p.key == key:
            return p
    return None


def target_info(tid):
    """O que o id controla: dict(kind="knob"|"choice"|"switch"|"button", group, label, param, ...) ou None.
    kind: knob = contínuo (só CC); choice = seletor (CC escolhe a opção, nota/botão passa para a próxima);
    switch = liga/desliga (alterna a cada toque); button = ação (preset anterior/próximo)."""
    if not isinstance(tid, str) or len(tid) > 300:
        return None
    if tid.startswith("fx/"):
        parts = tid.split("/", 3)
        if len(parts) != 4 or parts[1] not in CHAINS or not parts[2].isdigit() or not 1 <= int(parts[2]) <= 4:
            return None
        chain, n, what = parts[1], int(parts[2]), parts[3]
        base = dict(group="Plugins", chain=chain, slot=n - 1, track=None)
        where = f"Plugins {CHAIN_NAMES[chain]} › {n}"
        if what == "on":
            return dict(base, kind="switch", label=f"{where} › liga/desliga", param=None, what="on")
        if what == "mix":
            return dict(base, kind="knob", label=f"{where} › Mix", param=MIX_PARAM, what="mix")
        if what.startswith("param:") and len(what) > 6:
            name = what[6:]
            return dict(base, kind="knob", label=f"{where} › {name}", param=None, what="param", name=name)
        return None
    parts = tid.split("/")
    if len(parts) != 3 or parts[0] not in TRACKS:
        return None
    track, effect, key = parts
    tname = TRACK_NAMES[track]
    base = dict(group=tname, track=track, effect=effect, key=key)
    if effect == "preset":
        if key in ("prev", "next"):
            return dict(base, kind="button", param=None,
                        label=f"{tname} › {'preset anterior' if key == 'prev' else 'próximo preset'}")
        return None
    if effect == "track":
        if key == "on" or (track == "vocal" and key in TRACK_SWITCHES):
            return dict(base, kind="switch", param=None, label=f"{tname} › trilha › {TRACK_TOGGLE_NAMES[key]}")
        p = track_param(track, effect, key)
        if p is None:
            return None
        return dict(base, kind="choice" if p.is_choice else "knob", param=p, label=f"{tname} › trilha › {p.label}")
    eff = _effects(track).get(effect)
    if eff is None:
        return None
    if key == "on":
        return dict(base, kind="switch", param=None, label=f"{tname} › {eff.title} › liga/desliga")
    p = track_param(track, effect, key)
    if p is None:
        return None
    return dict(base, kind="choice" if p.is_choice else "knob", param=p, label=f"{tname} › {eff.title} › {p.label}")


def kinds_for(tid):
    """Tipos de mensagem aceitos no MidiLearnDialog: knob só CC; o resto CC, nota ou troca de programa."""
    info = target_info(tid)
    return ("cc",) if info and info["kind"] == "knob" else KINDS


def track_targets(track):
    """Todos os ids mapeáveis de uma trilha (na ordem da tela)."""
    out = [f"{track}/track/on"]
    if track == "vocal":
        out += ["vocal/track/mute", "vocal/track/phase"]
    for p in (VOCAL_TRACK_PARAMS if track == "vocal" else TRACK_PARAMS):
        out.append(f"{track}/track/{p.key}")
    if track == "vocal":
        out.append("vocal/track/plug_pos")
    out += [f"{track}/preset/prev", f"{track}/preset/next"]
    for e in (VOCAL_EFFECTS if track == "vocal" else EFFECTS):
        if e.key not in ("nam", "vst", "amp"):
            out.append(f"{track}/{e.key}/on")
        out += [f"{track}/{e.key}/{p.key}" for p in e.params if (e.key, p.key) not in SKIP]
    return out


# ------------------------------------------------------------------ valores
def norm_to_value(p, t):
    """0..1 -> valor do Param (mesma curva do knob da tela, com log e passo)."""
    t = min(max(float(t), 0.0), 1.0)
    v = p.lo * (p.hi / p.lo) ** t if (p.log and p.lo > 0) else p.lo + (p.hi - p.lo) * t
    if p.step:
        v = round(v / p.step) * p.step
    return min(max(v, p.lo), p.hi)


def cc_to_value(p, cc):
    return norm_to_value(p, cc / 127.0)


def choice_index(p, cc):
    n = len(p.choices)
    return min(n - 1, int(cc) * n // 128)


# ------------------------------------------------------------------ mapeamentos (sem interface)
def valid_key(k):
    """[tipo, canal 0-15, nº 0-127] com tipos certos (bool não vale como número)."""
    return (isinstance(k, (list, tuple)) and len(k) == 3 and isinstance(k[0], str) and k[0] in KINDS
            and all(isinstance(x, int) and not isinstance(x, bool) for x in k[1:])
            and 0 <= k[1] <= 15 and 0 <= k[2] <= 127)


def clean_ctl_map(d):
    """Mapeamentos vindos de arquivo (sessão, perfil do controlador): só ids e chaves conhecidos."""
    out = {}
    if not isinstance(d, dict):
        return out
    for tid, e in list(d.items())[:512]:
        info = target_info(tid)
        if info is None or not isinstance(e, dict) or not valid_key(e.get("key")):
            continue
        if info["kind"] == "knob" and e["key"][0] != "cc":
            continue
        entry = {"key": list(e["key"]),
                 "label": e["label"] if isinstance(e.get("label"), str) and len(e["label"]) <= 300
                 else info["label"]}
        if e.get("latch") is True and e["key"][0] == "cc" and info["kind"] in ("switch", "button"):
            entry["latch"] = True
        if tid.startswith("fx/"):
            entry["plugin"] = e["plugin"] if isinstance(e.get("plugin"), str) and len(e["plugin"]) <= 1024 else ""
            if info["what"] == "param":
                entry["param"] = info["name"]
        out[tid] = entry
    return out


def make_entry(tid, key, label=None, plugin="", latch=False):
    """Mapeamento novo de `tid` no controle físico `key` ([tipo, canal, nº]). latch: botão que trava."""
    info = target_info(tid)
    entry = {"key": list(key), "label": label or (info["label"] if info else tid)}
    if latch and key[0] == "cc" and info and info["kind"] in ("switch", "button"):
        entry["latch"] = True
    if tid.startswith("fx/"):
        entry["plugin"] = plugin or ""
        if info and info["what"] == "param":
            entry["param"] = info["name"]
    return entry


def latchable(tid, key):
    """O mapeamento pode ser "botão que trava"? (liga/desliga ou ação, num CC)"""
    info = target_info(tid)
    return bool(info and info["kind"] in ("switch", "button") and key and key[0] == "cc")


def cc_press(value, latch):
    """Um CC de botão conta como toque? Momentâneo: só o valor alto (o 0 da soltura nunca conta, por mais
    tempo que fique segurado). Que trava: cada mensagem (alto num toque, 0 no outro)."""
    return True if latch else value > 0


def key_matches(a, b):
    return list(a) == list(b)


def conflicts(inst, key, tid=None):
    """Onde mais esse controle físico já é usado: [(descrição, função que tira de lá)]. Pad/Piano (atalhos,
    knobs, botões e pads), outros mapeamentos das abas. Notas: inclui o aviso de tecla (sem remoção)."""
    from .instruments import BUTTONS
    out = []
    kind, ch, num = key
    for func, k in list(inst.free_map.items()):
        if key_matches(k, key):
            out.append((f"Pad/Piano: {func}", lambda f=func: inst.free_map.pop(f, None)))
    for t, e in list(inst.ctl_map.items()):
        if t != tid and key_matches(e.get("key", []), key):
            out.append((e.get("label") or t, lambda t=t: inst.ctl_map.pop(t, None)))
    m = inst.mapping
    if kind == "cc":
        for i, k in enumerate(m["knobs"]):
            if k and k[1] == num:                   # o mesmo knob físico em qualquer canal (ex.: PSR)
                out.append((f"Pad/Piano: knob {i + 1} da tela ({inst.knob_funcs[i]})",
                            lambda i=i: m["knobs"].__setitem__(i, None)))
    for i, b in enumerate(m["buttons"]):
        if b and key_matches(b, key):
            out.append((f"Pad/Piano: botão {BUTTONS[i]} ({inst.button_funcs[i]})",
                        lambda i=i: m["buttons"].__setitem__(i, None)))
    if kind == "note":
        for bank, name in ((0, "pads"), (1, "pads_b")):
            for i, p in enumerate(m[name]):
                if p and list(p) == [ch, num]:
                    out.append((f"Pad/Piano: pad {i + 1} do banco {'AB'[bank]}",
                                lambda name=name, i=i: m[name].__setitem__(i, None)))
    return out


def is_plain_key(inst, key):
    """Nota que hoje toca uma tecla do teclado (não é pad, botão nem atalho)."""
    if key[0] != "note":
        return False
    return not conflicts(inst, key)


class ControlMap:
    """Despacha as mensagens dos controles mapeados (ver o topo do arquivo)."""

    def __init__(self, engine):
        self.engine = engine
        self.wake = None                 # chamado (de qualquer thread) quando há algo para aplicar
        self.on_preset = lambda track, d: None      # preset anterior/próximo (precisa da tela)
        self.on_applied = lambda tids: None
        self._lock = threading.Lock()
        self._pending = {}               # chave -> (tid, entry, tipo, valor)
        self._seq = 0
        self._woken = False

    # ------------------------------------------------------------------ entrada (thread do MIDI)
    def post(self, tid, entry, kind, value):
        """Chegou `value` (0-127) de um controle mapeado em `tid`. Knob/seletor por CC: só o último valor
        conta (coalescência); toques (liga/desliga, nota, preset) entram todos."""
        info = target_info(tid)
        if info is None:
            return
        press = None
        if info["kind"] == "knob":
            if kind != "cc":
                return
        elif info["kind"] == "choice" and kind == "cc":
            pass
        else:
            press = self._is_press(kind, value, bool((entry or {}).get("latch")))
            if not press:
                return
        with self._lock:
            if press:
                self._seq += 1
                self._pending[(tid, self._seq)] = (tid, entry, kind, value)
            else:
                self._pending[tid] = (tid, entry, kind, value)
            wake = self.wake
            need = wake is not None and not self._woken
            if need:
                self._woken = True
        if wake is None:
            self.flush()
        elif need:
            wake()

    @staticmethod
    def _is_press(kind, value, latch=False):
        if kind == "pc":
            return True
        if kind == "note":
            return value > 0
        return cc_press(value, latch)

    # ------------------------------------------------------------------ aplicar (thread da interface)
    def flush(self):
        """Aplica o que chegou. -> lista de ids aplicados (para a tela acompanhar)."""
        with self._lock:
            items = list(self._pending.values())
            self._pending.clear()
            self._woken = False
        done = []
        for tid, entry, kind, value in items:
            try:
                if self.apply(tid, entry, kind, value):
                    done.append(tid)
            except Exception:  # noqa: BLE001 - um mapeamento com problema não para os outros
                import traceback
                traceback.print_exc()
        if done:
            self.on_applied(done)
        return done

    def apply(self, tid, entry, kind, value):
        info = target_info(tid)
        if info is None:
            return False
        if info["group"] == "Plugins":
            return self._apply_fx(info, entry or {}, kind, value)
        track = self.engine.tracks.get(info["track"])
        if track is None:
            return False
        effect, key = info["effect"], info["key"]
        if info["kind"] == "button":
            self.on_preset(info["track"], -1 if key == "prev" else 1)
            return True
        if info["kind"] == "switch":
            if effect == "track":
                on = not bool(track.values["track"].get(key, False))
                if hasattr(track, "set_switch"):
                    track.set_switch(key, on)
                else:
                    track.set_param("track", key, on)
            else:
                track.set_on(effect, not bool(track.values[effect]["on"]))
            return True
        p = info["param"]
        if info["kind"] == "choice":
            n = len(p.choices)
            if kind == "cc":
                i = choice_index(p, value)
            else:
                i = (int(round(track.values[effect][key])) + 1) % n
            track.set_param(effect, key, float(i))
            return True
        track.set_param(effect, key, cc_to_value(p, value))
        return True

    # ------------------------------------------------------------------ plugins
    def chain(self, chain_id):
        e = self.engine
        if chain_id.startswith("L"):
            chains = getattr(e, "layer_chains", None) or ()
            n = int(chain_id[1:])
            return chains[n - 1] if 1 <= n <= len(chains) else None
        if chain_id == "master":
            return getattr(e, "master_chain", None)
        t = getattr(e, "tracks", {}).get(chain_id)
        return getattr(t, "fx_chain", None)

    def find_slot(self, chain_id, index, plugin=""):
        """O slot do plugin mapeado: o da posição gravada se é o mesmo plugin; senão o 1º da cadeia com esse
        plugin (a ordem mudou). Plugin ausente: None (o mapeamento fica inativo, sem erro)."""
        from .audio.vst import portable_ref
        chain = self.chain(chain_id)
        if chain is None:
            return None
        slots = tuple(chain.slots)

        def same(s):
            if not s.path:
                return False
            return not plugin or portable_ref(s.path) == plugin or s.path == plugin
        if 0 <= index < len(slots) and same(slots[index]):
            return slots[index]
        if plugin:
            for s in slots:
                if same(s):
                    return s
        return None

    def _apply_fx(self, info, entry, kind, value):
        slot = self.find_slot(info["chain"], info["slot"], entry.get("plugin", ""))
        if slot is None or slot.missing or slot.load_error:
            return False
        if info["what"] == "on":
            slot.set_on(not slot.on)
            return True
        if kind != "cc":
            return False
        if info["what"] == "mix":
            slot.set_mix(value / 127.0 * 100.0)
            return True
        return slot.set_param(info["name"], value / 127.0)

    def active(self, tid, entry):
        """O mapeamento está valendo agora? (plugin mapeado ausente = inativo)"""
        info = target_info(tid)
        if info is None:
            return False
        if info["group"] != "Plugins":
            return True
        slot = self.find_slot(info["chain"], info["slot"], (entry or {}).get("plugin", ""))
        return slot is not None and not slot.missing and not slot.load_error
