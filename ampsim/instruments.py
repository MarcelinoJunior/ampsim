"""Teclas e pads do controlador MIDI: timbres, camadas/divisão, bateria e mapeamento.

As notas do teclado tocam até dois timbres (camada sobreposta ou divisão "mão esquerda");
os 8 pads disparam sons de bateria. Knobs e botões do controlador ganham funções
(volume, reverb, próximo timbre...) aprendidas com o assistente de mapeamento.
"""
from dataclasses import dataclass

from .dsp import layout as Ly

# ------------------------------------------------------------------ catálogo de timbres
@dataclass(frozen=True)
class Sound:
    name: str
    cat: str
    src: str            # "sf2" (FluidSynth) ou "synth" (synth interno de pads)
    bank: int = 0
    prog: int = 0
    synth_preset: str = ""


_SF2 = (
    ("Pianos", (("Piano de Cauda", 0, 0), ("Piano Brilhante", 0, 1), ("Piano Elétrico (CP)", 0, 2),
                ("Piano Honky-tonk", 0, 3))),
    ("Pianos elétricos", (("Rhodes", 0, 4), ("Rhodes com Chorus", 8, 4), ("Piano FM (DX)", 0, 5),
                          ("Piano FM com Chorus", 8, 5), ("Clavinet", 0, 7))),
    ("Órgãos", (("Órgão Hammond", 0, 16), ("Órgão Percussivo", 0, 17), ("Órgão Rock", 0, 18),
                ("Órgão de Tubos", 0, 19), ("Órgão de Tubos 2", 8, 19))),
    ("Pads e cordas", (("Pad Quente", 0, 89), ("Pad Halo", 0, 94), ("Pad Polysynth", 0, 90),
                       ("Pad Atmosfera", 0, 99), ("Pad Vozes", 0, 91), ("Coral", 0, 52),
                       ("Cordas Lentas", 0, 49), ("Cordas", 0, 48), ("Cordas Synth", 0, 50),
                       ("Pad Orquestra", 8, 48))),
    ("Baixos", (("Baixo Finger", 0, 33), ("Baixo Palheta", 0, 34), ("Baixo Fretless", 0, 35),
                ("Baixo Acústico", 0, 32), ("Baixo Synth", 0, 38), ("Baixo Synth 101", 1, 38),
                ("Baixo FM", 8, 39))),
    ("Violões e guitarras", (("Violão Nylon", 0, 24), ("Violão Aço", 0, 25), ("Violão 12 Cordas", 8, 25),
                             ("Guitarra Limpa", 0, 27), ("Guitarra com Chorus", 8, 27),
                             ("Guitarra Jazz", 0, 26), ("Guitarra Overdrive", 0, 29),
                             ("Guitarra Distorcida", 0, 30))),
    ("Sinos e outros", (("Celesta", 0, 8), ("Sinos", 0, 14), ("Caixinha de Música", 0, 10),
                        ("Vibrafone", 0, 11), ("Marimba", 0, 12), ("Kalimba", 0, 108),
                        ("Synth Lead", 0, 81))),
)

SOUNDS = [Sound(name, cat, "sf2", b, p) for cat, items in _SF2 for name, b, p in items]
for _preset in ("Pad Quente", "Pad Escuro", "Cordas", "Saw Brilhante", "Órgão", "Sino Suave"):
    SOUNDS.append(Sound(f"{_preset} (AmpSim)", "Synth AmpSim", "synth", synth_preset=_preset))
SOUND_BY_NAME = {s.name: s for s in SOUNDS}
CATEGORIES = list(dict.fromkeys(s.cat for s in SOUNDS))

# timbres prontos: combinam um ou dois sons (camada ou divisão)
READY = {
    "Piano + Pad": dict(sound1="Piano de Cauda", sound2="Pad Quente", mode2="layer", vol2=70),
    "Piano + Cordas": dict(sound1="Piano de Cauda", sound2="Cordas Lentas", mode2="layer", vol2=65),
    "Rhodes + Pad": dict(sound1="Rhodes com Chorus", sound2="Pad Halo", mode2="layer", vol2=60),
    "Piano Brilhante": dict(sound1="Piano Brilhante", sound2=""),
    "Pad de Louvor (AmpSim)": dict(sound1="Pad Quente (AmpSim)", sound2=""),
    "Pad + Cordas": dict(sound1="Pad Atmosfera", sound2="Cordas Lentas", mode2="layer", vol2=75),
    "Baixo | Piano (divisão em C3)": dict(sound1="Piano de Cauda", sound2="Baixo Finger",
                                          mode2="split", split=48, vol2=100),
    "Baixo Synth | Rhodes": dict(sound1="Rhodes", sound2="Baixo Synth", mode2="split", split=48, vol2=95),
    "Órgão + Pad": dict(sound1="Órgão Hammond", sound2="Pad Quente", mode2="layer", vol2=55),
    "Violão Aço": dict(sound1="Violão Aço", sound2=""),
    "Guitarra Limpa (use com amp)": dict(sound1="Guitarra Limpa", sound2=""),
}

# ------------------------------------------------------------------ bateria
DRUM_NAMES = {
    35: "Bumbo 2", 36: "Bumbo", 37: "Aro (rim)", 38: "Caixa", 39: "Palmas", 40: "Caixa 2",
    41: "Surdo grave", 42: "Chimbal fechado", 43: "Surdo", 44: "Chimbal pedal", 45: "Tom grave",
    46: "Chimbal aberto", 47: "Tom médio", 48: "Tom médio-agudo", 49: "Prato de ataque",
    50: "Tom agudo", 51: "Prato de condução", 52: "Prato china", 53: "Cúpula do ride",
    54: "Pandeirola", 55: "Splash", 56: "Cowbell", 57: "Prato de ataque 2", 59: "Condução 2",
    69: "Cabasa", 70: "Shaker", 75: "Claves", 81: "Triângulo",
}
KITS = (("Acústico (Room)", 128, 8), ("Power (rock)", 128, 16), ("Standard", 128, 0),
        ("Eletrônico", 128, 24), ("808/909", 128, 25), ("Vassourinha (brush)", 128, 40),
        ("Jazz", 128, 32))
KIT_BY_NAME = {k[0]: k for k in KITS}
DEFAULT_PAD_NOTES = [36, 38, 37, 39, 42, 46, 49, 51]
PAD_COUNT = 8
KNOB_COUNT = 8
BUTTONS = ("PLAY", "STOP", "REC", "BT", "ARP", "SC/CH", "KNOB-B", "PAD-B")

KNOB_FUNCS = ("Nenhuma", "Volume teclas", "Volume camada 2", "Volume bateria", "Reverb", "Chorus",
              "Brilho", "Release", "Ataque", "Master")
DEFAULT_KNOB_FUNCS = ["Volume teclas", "Volume camada 2", "Volume bateria", "Reverb", "Chorus",
                      "Brilho", "Release", "Master"]
BUTTON_FUNCS = ("Nenhuma", "Timbre anterior", "Próximo timbre", "Kit anterior", "Próximo kit",
                "Liga/desliga camada 2", "Pânico (soltar notas)")
DEFAULT_BUTTON_FUNCS = ["Timbre anterior", "Próximo timbre", "Pânico (soltar notas)", "Nenhuma",
                        "Kit anterior", "Próximo kit", "Liga/desliga camada 2", "Nenhuma"]

CH_KEYS1, CH_KEYS2, CH_DRUMS = 0, 2, 9        # canais pares = grupo das teclas no FluidSynth


def note_name(n):
    return ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")[n % 12] + str(n // 12 - 1)


class Instruments:
    """Estado e roteamento. Os métodos de nota/MIDI podem ser chamados de qualquer thread."""

    def __init__(self, engine):
        self.engine = engine
        self.sf = None
        self.error = None
        self.keys = dict(sound1="Piano de Cauda", sound2="Pad Quente", mode2="layer", split=48,
                         vol1=100, vol2=70, layer2_on=True)
        self.ready = "Piano + Pad"
        self.kit = KITS[0][0]
        self.pad_notes = list(DEFAULT_PAD_NOTES)
        self.levels = dict(keys=80, drums=85, reverb=45, chorus=15, bright=64, release=64, attack=0)
        self.mapping = dict(pads=[[9, n] for n in range(36, 44)], knobs=[None] * KNOB_COUNT,
                            buttons=[None] * len(BUTTONS))
        self.knob_funcs = list(DEFAULT_KNOB_FUNCS)
        self.button_funcs = list(DEFAULT_BUTTON_FUNCS)
        self.knob_values = [0] * KNOB_COUNT
        self._held = {}
        self.learn_steps = []
        self._learned = set()
        # ganchos da interface (chamados de qualquer thread; a UI os liga a sinais Qt)
        self.on_pad = lambda i, vel: None
        self.on_key = lambda note, on: None
        self.on_knob = lambda i, val: None
        self.on_change = lambda: None
        self.on_learn = lambda: None

    # ------------------------------------------------------------------ motor
    def start(self, fs, max_block):
        from .audio.soundfont import SoundFontEngine, available

        old, self.sf = self.sf, None
        if old is not None:
            old.close()
        if not available():
            self.error = "Timbres não instalados: rode tools\\baixar_extras.py"
            return
        try:
            self.sf = SoundFontEngine(fs, max_block)
            self.error = None
        except (OSError, RuntimeError) as exc:
            self.error = str(exc)
            return
        self.apply_all()

    def keys_gain(self):
        return (self.levels["keys"] / 100.0) ** 2 * 2.0

    def drums_gain(self):
        return (self.levels["drums"] / 100.0) ** 2 * 2.0

    def apply_all(self):
        self.all_off()
        for chan, key in ((CH_KEYS1, "sound1"), (CH_KEYS2, "sound2")):
            s = SOUND_BY_NAME.get(self.keys.get(key) or "")
            if s is not None and s.src == "sf2" and self.sf:
                self.sf.program(chan, s.bank, s.prog)
            if s is not None and s.src == "synth":
                self.engine.synth.apply_preset(s.synth_preset)
        if self.sf:
            _, bank, prog = KIT_BY_NAME.get(self.kit, KITS[0])
            self.sf.program(CH_DRUMS, bank, prog)
            self.sf.cc(CH_KEYS1, 7, self.keys["vol1"])
            self.sf.cc(CH_KEYS2, 7, self.keys["vol2"])
            for ch in (CH_KEYS1, CH_KEYS2, CH_DRUMS):
                self.sf.cc(ch, 91, self.levels["reverb"])
                self.sf.cc(ch, 93, self.levels["chorus"] if ch != CH_DRUMS else 0)
            for ch in (CH_KEYS1, CH_KEYS2):
                self.sf.cc(ch, 74, self.levels["bright"])
                self.sf.cc(ch, 72, self.levels["release"])
                self.sf.cc(ch, 73, self.levels["attack"])

    # ------------------------------------------------------------------ timbres
    def set_ready(self, name):
        cfg = dict(sound2="", mode2="layer", split=48, vol1=100, vol2=70, layer2_on=True)
        cfg.update(READY[name])
        self.keys.update(cfg)
        self.ready = name
        self.apply_all()
        self.on_change()

    def set_sound(self, slot, name):
        self.keys["sound1" if slot == 1 else "sound2"] = name
        self.ready = ""
        self.apply_all()
        self.on_change()

    def set_kit(self, name):
        self.kit = name
        self.apply_all()
        self.on_change()

    def step_ready(self, delta):
        names = list(READY)
        i = names.index(self.ready) if self.ready in names else -1
        self.set_ready(names[(i + delta) % len(names)])

    def step_kit(self, delta):
        names = [k[0] for k in KITS]
        i = names.index(self.kit) if self.kit in names else 0
        self.set_kit(names[(i + delta) % len(names)])

    def display_text(self):
        k = self.keys
        if self.ready:
            return self.ready
        s2 = k["sound2"] if (k["sound2"] and k["layer2_on"]) else ""
        if not s2:
            return k["sound1"]
        sep = " | " if k["mode2"] == "split" else " + "
        return (s2 + sep + k["sound1"]) if k["mode2"] == "split" else (k["sound1"] + sep + s2)

    # ------------------------------------------------------------------ notas
    def _targets(self, note):
        k = self.keys
        s1 = SOUND_BY_NAME.get(k["sound1"])
        s2 = SOUND_BY_NAME.get(k["sound2"]) if (k["sound2"] and k["layer2_on"]) else None
        split = s2 is not None and k["mode2"] == "split"
        out = []
        if s1 is not None and (not split or note >= k["split"]):
            out.append((s1, CH_KEYS1))
        if s2 is not None and (not split or note < k["split"]):
            out.append((s2, CH_KEYS2))
        return out

    def key_on(self, note, vel=100):
        targets = self._targets(note)
        self._held[note] = targets
        synth_done = False
        for s, ch in targets:
            if s.src == "synth":
                if not synth_done:
                    self.engine.send_event(Ly.EV_NOTE_ON, note, vel)
                    synth_done = True
            elif self.sf:
                self.sf.noteon(ch, note, vel)
        self.on_key(note, True)

    def key_off(self, note):
        for s, ch in self._held.pop(note, []):
            if s.src == "synth":
                self.engine.send_event(Ly.EV_NOTE_OFF, note, 0)
            elif self.sf:
                self.sf.noteoff(ch, note)
        self.on_key(note, False)

    def pad_hit(self, i, vel=110):
        if self.sf and 0 <= i < PAD_COUNT:
            self.sf.noteon(CH_DRUMS, self.pad_notes[i], vel)
        self.on_pad(i, vel)

    def all_off(self):
        for note in list(self._held):
            self.key_off(note)
        if self.sf:
            self.sf.all_off()
        self.engine.send_event(Ly.EV_ALL_OFF)

    # ------------------------------------------------------------------ knobs e botões
    def set_knob(self, i, value):
        """value 0..127 vindo do knob físico ou do knob desenhado na tela."""
        self.knob_values[i] = value
        self.apply_knob_func(self.knob_funcs[i], value)
        self.on_knob(i, value)

    def apply_knob_func(self, func, value):
        lv = self.levels
        pct = round(value / 127 * 100)
        if func == "Volume teclas":
            lv["keys"] = pct
        elif func == "Volume bateria":
            lv["drums"] = pct
        elif func == "Volume camada 2":
            self.keys["vol2"] = value
            if self.sf:
                self.sf.cc(CH_KEYS2, 7, value)
        elif func == "Master":
            self.engine.master = (value / 127) ** 2 * 2.0
        elif self.sf and func in ("Reverb", "Chorus", "Brilho", "Release", "Ataque"):
            key, cc = {"Reverb": ("reverb", 91), "Chorus": ("chorus", 93), "Brilho": ("bright", 74),
                       "Release": ("release", 72), "Ataque": ("attack", 73)}[func]
            lv[key] = value
            chans = (CH_KEYS1, CH_KEYS2, CH_DRUMS) if cc == 91 else (CH_KEYS1, CH_KEYS2)
            for ch in chans:
                self.sf.cc(ch, cc, value)

    def button(self, i):
        func = self.button_funcs[i]
        if func == "Timbre anterior":
            self.step_ready(-1)
        elif func == "Próximo timbre":
            self.step_ready(1)
        elif func == "Kit anterior":
            self.step_kit(-1)
        elif func == "Próximo kit":
            self.step_kit(1)
        elif func == "Liga/desliga camada 2":
            self.keys["layer2_on"] = not self.keys["layer2_on"]
            self.ready = ""
            self.all_off()
            self.on_change()
        elif func.startswith("Pânico"):
            self.all_off()

    # ------------------------------------------------------------------ MIDI (thread do winmm)
    def handle_midi(self, status, d1, d2):
        kind, ch = status & 0xF0, status & 0x0F
        if self.learn_steps:
            self._learn(kind, ch, d1, d2)
            return
        m = self.mapping
        if kind in (0x80, 0x90):
            on = kind == 0x90 and d2 > 0
            for i, pad in enumerate(m["pads"]):
                if pad == [ch, d1]:
                    if on:
                        self.pad_hit(i, d2)
                    return
            for i, b in enumerate(m["buttons"]):
                if b == ["note", ch, d1]:
                    if on:
                        self.button(i)
                    return
            if on:
                self.key_on(d1, d2)
            else:
                self.key_off(d1)
        elif kind == 0xB0:
            for i, k in enumerate(m["knobs"]):
                if k == [ch, d1]:
                    self.set_knob(i, d2)
                    return
            for i, b in enumerate(m["buttons"]):
                if b == ["cc", ch, d1]:
                    if d2 > 0:
                        self.button(i)
                    return
            if d1 == 64:
                self.engine.send_event(Ly.EV_SUSTAIN, d2)
            elif d1 == 1:
                self.engine.send_event(Ly.EV_MOD, d2)
            elif d1 in (120, 123):
                self.all_off()
                return
            if self.sf:
                for c in (CH_KEYS1, CH_KEYS2):
                    self.sf.cc(c, d1, d2)
        elif kind == 0xE0:
            val = d1 | (d2 << 7)
            self.engine.send_event(Ly.EV_BEND, val)
            if self.sf:
                for c in (CH_KEYS1, CH_KEYS2):
                    self.sf.pitch_bend(c, val)

    # ------------------------------------------------------------------ assistente de mapeamento
    def start_learning(self, what=("pads", "knobs", "buttons")):
        steps = []
        if "pads" in what:
            steps += [("pads", i) for i in range(PAD_COUNT)]
        if "knobs" in what:
            steps += [("knobs", i) for i in range(KNOB_COUNT)]
        if "buttons" in what:
            steps += [("buttons", i) for i in range(len(BUTTONS))]
        self._learned = set()
        self.learn_steps = steps
        self.on_learn()

    def skip_learning_step(self):
        if self.learn_steps:
            self.learn_steps.pop(0)
            self.on_learn()

    def stop_learning(self):
        self.learn_steps = []
        self.on_learn()

    def learning_prompt(self):
        if not self.learn_steps:
            return ""
        kind, i = self.learn_steps[0]
        if kind == "pads":
            return f"Toque o PAD {i + 1} no controlador"
        if kind == "knobs":
            return f"Gire o KNOB {i + 1} no controlador"
        return f"Aperte o botão {BUTTONS[i]} no controlador"

    def _learn(self, kind, ch, d1, d2):
        step, i = self.learn_steps[0]
        if kind == 0x90 and d2 > 0:
            key = ("note", ch, d1)
        elif kind == 0xB0:
            key = ("cc", ch, d1)
        else:
            return
        if key in self._learned:          # resto do movimento de um knob já aprendido
            return
        if step == "pads" and key[0] == "note":
            self.mapping["pads"][i] = [ch, d1]
        elif step == "knobs" and key[0] == "cc":
            self.mapping["knobs"][i] = [ch, d1]
        elif step == "buttons" and (key[0] == "note" or d2 > 0):
            self.mapping["buttons"][i] = list(key)
        else:
            return
        self._learned.add(key)
        self.learn_steps.pop(0)
        if step == "pads":
            self.pad_hit(i, d2 if key[0] == "note" else 100)
        self.on_learn()

    # ------------------------------------------------------------------ persistência
    def get_state(self):
        return dict(keys=dict(self.keys), ready=self.ready, kit=self.kit, pad_notes=list(self.pad_notes),
                    levels=dict(self.levels), mapping={k: list(v) for k, v in self.mapping.items()},
                    knob_funcs=list(self.knob_funcs), button_funcs=list(self.button_funcs))

    def load_state(self, st):
        if not st:
            return
        self.keys.update({k: v for k, v in st.get("keys", {}).items() if k in self.keys})
        for k in ("sound1", "sound2"):
            if self.keys[k] and self.keys[k] not in SOUND_BY_NAME:
                self.keys[k] = "Piano de Cauda" if k == "sound1" else ""
        self.ready = st.get("ready", "") if st.get("ready", "") in READY else ""
        if st.get("kit") in KIT_BY_NAME:
            self.kit = st["kit"]
        if len(st.get("pad_notes", [])) == PAD_COUNT:
            self.pad_notes = list(st["pad_notes"])
        self.levels.update({k: v for k, v in st.get("levels", {}).items() if k in self.levels})
        for k, n in (("pads", PAD_COUNT), ("knobs", KNOB_COUNT), ("buttons", len(BUTTONS))):
            v = st.get("mapping", {}).get(k)
            if isinstance(v, list) and len(v) == n:
                self.mapping[k] = v
        for attr, valid, n in (("knob_funcs", KNOB_FUNCS, KNOB_COUNT),
                               ("button_funcs", BUTTON_FUNCS, len(BUTTONS))):
            v = st.get(attr)
            if isinstance(v, list) and len(v) == n and all(x in valid for x in v):
                setattr(self, attr, list(v))
        self.apply_all()
