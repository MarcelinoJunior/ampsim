"""Teclas e pads do controlador MIDI: timbres, camadas/divisão, bateria, pad contínuo e mapeamento.

As notas do teclado tocam até dois timbres (camada sobreposta ou divisão "mão esquerda").
Pads do banco A disparam sons de bateria (de qualquer kit, ou da bateria worship sintetizada);
pads do banco B ligam o pad contínuo no tom escolhido. Knobs e botões ganham funções
aprendidas com o assistente de mapeamento.
"""
import math
import time
from collections import deque
from dataclasses import dataclass

from .audio.sampler import REC_PREFIX
from .dsp import layout as Ly
from .dsp.padeq import DEFAULT_PAD_EQ, VOICINGS, clean_pad_eq
from .dsp.worship import DRUM_TYPE_NAMES

# ------------------------------------------------------------------ timbres das teclas
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
                       ("Pad Atmosfera", 0, 99), ("Pad Vozes", 0, 91), ("Pad Cristal", 0, 98),
                       ("Pad Sweep", 0, 95), ("Pad Vidro", 0, 92), ("Pad Chuva de Gelo", 0, 96),
                       ("Coral", 0, 52), ("Cordas Lentas", 0, 49), ("Cordas", 0, 48),
                       ("Cordas Synth", 0, 50), ("Pad Orquestra", 8, 48), ("Pad Órgão", 8, 16))),
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
for _preset in ("Baixo Pulsante", "Pad Quente", "Pad Escuro", "Cordas", "Saw Brilhante", "Órgão",
                "Sino Suave"):
    SOUNDS.append(Sound(f"{_preset} (AmpSim)", "Synth AmpSim", "synth", synth_preset=_preset))
SOUND_BY_NAME = {s.name: s for s in SOUNDS}
CATEGORIES = list(dict.fromkeys(s.cat for s in SOUNDS))

# timbres prontos (um ou dois sons + efeitos), agrupados para a lista da tela
READY_GROUPS = (
    ("Teclados 61/73 teclas", {
        "Piano de Concerto": dict(sound1="Piano de Cauda", sound2="Cordas Lentas", vol2=40,
                                  fx=dict(reverb=70, chorus=10)),
        "Piano + Pad (culto)": dict(sound1="Piano de Cauda", sound2="Pad Halo", vol2=62,
                                    fx=dict(reverb=85, chorus=20, shimmer=25)),
        "Pad | Piano (pad na esquerda)": dict(sound1="Piano de Cauda", sound2="Pad Atmosfera", mode2="split",
                                              split=55, vol2=85, fx=dict(reverb=90, shimmer=35)),
        "Cordas | Piano (cordas na esquerda)": dict(sound1="Piano Brilhante", sound2="Cordas Lentas",
                                                    mode2="split", split=55, vol2=90, fx=dict(reverb=80)),
        "Baixo | Piano (teclado grande)": dict(sound1="Piano de Cauda",
                                    sound2="Baixo Finger", mode2="split", split=48, vol2=100,
                                    fx=dict(reverb=75, chorus=15)),
        "Órgão Gospel (rotação)": dict(sound1="Órgão Hammond", sound2="", fx=dict(
            reverb=40, chorus=0, rot_on=True, rot_fast=False, rot_mix=100, drive_on=True, drive=25)),
        "Órgão Rock (drive + rotação rápida)": dict(sound1="Órgão Rock", fx=dict(
            reverb=35, rot_on=True, rot_fast=True, rot_mix=100, drive_on=True, drive=60)),
        "Órgão + Piano": dict(sound1="Piano de Cauda", sound2="Órgão Hammond", vol2=55, fx=dict(reverb=60),
                              fx2=dict(rot_on=True, rot_mix=100)),
        "Rhodes com Delay (balada)": dict(sound1="Rhodes", sound2="Pad Quente", vol2=45, fx=dict(
            reverb=70, chorus=40, delay_on=True, delay_div=3, delay_fb=30, delay_mix=22)),
        "Piano Brilhante + Synth Pad": dict(sound1="Piano Brilhante", sound2="Pad Polysynth", vol2=55,
                                           fx=dict(reverb=80, chorus=30, shimmer=20)),
    }),
    ("Espaciais (worship)", {
        # o mesmo som do pad contínuo (banco B), tocado nas teclas: timbre + oitava abaixo,
        # muito reverb/chorus, shimmer e ataque lento
        "Pad Quente Contínuo (nas teclas)": dict(sound1="Pad Quente", sound2="Pad Quente", vol2=80, oct2=-1,
                                                 fx=dict(reverb=120, chorus=60, shimmer=70, attack=45)),
        "Pad Halo Contínuo (nas teclas)": dict(sound1="Pad Halo", sound2="Pad Halo", vol2=80, oct2=-1,
                                               fx=dict(reverb=120, chorus=60, shimmer=70, attack=45)),
        "Pad Celestial (Shimmer)": dict(sound1="Pad Halo", sound2="Pad Vozes", vol2=80,
                                        fx=dict(reverb=110, chorus=40, shimmer=65)),
        "Céu Aberto": dict(sound1="Pad Atmosfera", sound2="Cordas Lentas", vol2=70,
                           fx=dict(reverb=115, chorus=30, shimmer=50)),
        "Pad Cristal": dict(sound1="Pad Cristal", sound2="Pad Halo", vol2=75,
                            fx=dict(reverb=110, chorus=35, shimmer=55)),
        "Coral Etéreo": dict(sound1="Coral", sound2="Pad Vidro", vol2=70,
                             fx=dict(reverb=120, chorus=25, shimmer=45)),
        "Piano Ambient": dict(sound1="Piano de Cauda", sound2="Pad Halo", vol2=65,
                              fx=dict(reverb=95, chorus=15, shimmer=40)),
        "Rhodes Ambient": dict(sound1="Rhodes com Chorus", sound2="Pad Atmosfera", vol2=60,
                               fx=dict(reverb=100, chorus=35, shimmer=40)),
        "Pad Sweep Worship": dict(sound1="Pad Sweep", sound2="Pad Quente", vol2=70,
                                  fx=dict(reverb=110, chorus=40, shimmer=55)),
    }),
    ("Clássicos", {
        "Piano + Pad": dict(sound1="Piano de Cauda", sound2="Pad Quente", vol2=70),
        "Piano + Cordas": dict(sound1="Piano de Cauda", sound2="Cordas Lentas", vol2=65),
        "Rhodes + Pad": dict(sound1="Rhodes com Chorus", sound2="Pad Halo", vol2=60),
        "Piano Brilhante": dict(sound1="Piano Brilhante"),
        "Pad de Louvor (AmpSim)": dict(sound1="Pad Quente (AmpSim)"),
        "Pad + Cordas": dict(sound1="Pad Atmosfera", sound2="Cordas Lentas", vol2=75),
        "Órgão + Pad": dict(sound1="Órgão Hammond", sound2="Pad Quente", vol2=55),
    }),
    ("Baixo na mão esquerda", {
        "Baixo Pulsante | Pad (BPM)": dict(sound1="Pad Halo", sound2="Baixo Pulsante (AmpSim)",
                                           mode2="split", split=48, vol2=100,
                                           fx=dict(reverb=95, chorus=30, shimmer=35)),
        "Baixo Pulsante (BPM)": dict(sound1="Baixo Pulsante (AmpSim)"),
        "Baixo | Piano (divisão em C3)": dict(sound1="Piano de Cauda", sound2="Baixo Finger",
                                              mode2="split", split=48, vol2=100),
        "Baixo Synth | Rhodes": dict(sound1="Rhodes", sound2="Baixo Synth", mode2="split", split=48,
                                     vol2=95),
        "Baixo | Pad Espacial": dict(sound1="Pad Halo", sound2="Baixo Synth", mode2="split", split=48,
                                     vol2=95, fx=dict(reverb=100, shimmer=45)),
    }),
    ("Violão e guitarra", {
        "Violão Aço": dict(sound1="Violão Aço"),
        "Guitarra Limpa (use com amp)": dict(sound1="Guitarra Limpa"),
    }),
)
READY = {name: cfg for _, group in READY_GROUPS for name, cfg in group.items()}

# ------------------------------------------------------------------ sons dos pads
KITS = (("Acústico (Room)", 128, 8), ("Power (rock)", 128, 16), ("Standard", 128, 0),
        ("Eletrônico", 128, 24), ("808/909", 128, 25), ("Dance", 128, 26),
        ("Vassourinha (brush)", 128, 40), ("Jazz", 128, 32), ("Orquestra", 128, 48))
KIT_SHORT = {k[0]: k[0].split(" (")[0] for k in KITS}


@dataclass(frozen=True)
class PadSound:
    name: str
    cat: str
    kind: str            # "sf2" ou "synth"
    bank: int = 0
    prog: int = 0
    note: int = 36
    melodic: bool = False   # timbre melódico: precisa de note-off programado
    synth: int = -1


def _kit_sounds(cat, label, note, kits):
    out = []
    for kit_name, bank, prog in KITS:
        if KIT_SHORT[kit_name] in kits:
            out.append(PadSound(f"{label} — {KIT_SHORT[kit_name]}", cat, "sf2", bank, prog, note))
    return out


def _synth(cat, name):
    return PadSound(name, cat, "synth", synth=DRUM_TYPE_NAMES.index(name))


_ALL_KITS = ("Acústico", "Power", "Standard", "Eletrônico", "808/909", "Dance", "Jazz", "Orquestra")
PAD_SOUNDS = (
    [_synth("Bumbos", n) for n in ("Bumbo Sub Worship", "Bumbo Boom Cinemático", "Bumbo Punch (pop)",
                                   "Bumbo 808 Longo")]
    + _kit_sounds("Bumbos", "Bumbo", 36, _ALL_KITS)
    + _kit_sounds("Bumbos", "Bumbo 2", 35, ("Acústico", "Power", "Standard", "808/909"))
    + [PadSound("Bumbo de Orquestra", "Bumbos", "sf2", 8, 116, 36, True),
       PadSound("Taiko", "Bumbos", "sf2", 0, 116, 40, True)]
    + [_synth("Caixas e palmas", n) for n in ("Caixa Grave Profunda", "Caixa Grave Larga (sala)",
                                              "Caixa Grave + Palmas", "Caixa Grave Worship",
                                              "Caixa Ampla (rimshot)",
                                              "Palmas Largas", "Palmas + Caixa Worship")]
    + _kit_sounds("Caixas e palmas", "Caixa", 38, _ALL_KITS + ("Vassourinha",))
    + _kit_sounds("Caixas e palmas", "Caixa 2", 40, ("Acústico", "Power", "Eletrônico", "808/909", "Vassourinha"))
    + _kit_sounds("Caixas e palmas", "Aro (rim)", 37, ("Acústico", "Standard", "808/909"))
    + _kit_sounds("Caixas e palmas", "Palmas", 39, ("Standard", "808/909", "Eletrônico", "Dance"))
    + [_synth("Chimbais e pratos", n) for n in ("Chimbal Fechado (synth)", "Chimbal Aberto (synth)")]
    + _kit_sounds("Chimbais e pratos", "Chimbal fechado", 42, ("Acústico", "Power", "Standard", "808/909", "Eletrônico", "Jazz"))
    + _kit_sounds("Chimbais e pratos", "Chimbal aberto", 46, ("Acústico", "Power", "Standard", "808/909", "Eletrônico", "Jazz"))
    + _kit_sounds("Chimbais e pratos", "Chimbal pedal", 44, ("Acústico", "Standard"))
    + _kit_sounds("Chimbais e pratos", "Prato de ataque", 49, ("Acústico", "Power", "Standard", "Orquestra"))
    + _kit_sounds("Chimbais e pratos", "Prato de ataque 2", 57, ("Acústico", "Standard"))
    + _kit_sounds("Chimbais e pratos", "Prato de condução", 51, ("Acústico", "Jazz", "Standard"))
    + _kit_sounds("Chimbais e pratos", "Cúpula do ride", 53, ("Acústico", "Jazz"))
    + _kit_sounds("Chimbais e pratos", "Splash", 55, ("Acústico",))
    + _kit_sounds("Chimbais e pratos", "China", 52, ("Acústico",))
    + [_synth("Toms e percussão", n) for n in ("Tom Cinemático", "Tom Grave Cinemático", "Shaker Suave")]
    + _kit_sounds("Toms e percussão", "Tom grave", 45, ("Acústico", "Power", "808/909"))
    + _kit_sounds("Toms e percussão", "Tom médio", 47, ("Acústico", "Power", "808/909"))
    + _kit_sounds("Toms e percussão", "Tom agudo", 50, ("Acústico", "Power", "808/909"))
    + _kit_sounds("Toms e percussão", "Surdo", 41, ("Acústico", "Power"))
    + _kit_sounds("Toms e percussão", "Pandeirola", 54, ("Standard",))
    + _kit_sounds("Toms e percussão", "Shaker", 70, ("Standard",))
    + _kit_sounds("Toms e percussão", "Cabasa", 69, ("Standard",))
    + _kit_sounds("Toms e percussão", "Cowbell", 56, ("Standard",))
    + _kit_sounds("Toms e percussão", "Triângulo", 81, ("Standard",))
    + [PadSound("Tímpano", "Toms e percussão", "sf2", 0, 47, 41, True)]
    + [_synth("Efeitos e cinemático", "Impacto (Boom + Prato)"),
       PadSound("Swell (prato reverso)", "Efeitos e cinemático", "sf2", 0, 119, 60, True),
       PadSound("Impacto Orquestral", "Efeitos e cinemático", "sf2", 0, 55, 60, True),
       PadSound("Sino de Igreja", "Efeitos e cinemático", "sf2", 8, 14, 60, True),
       PadSound("Sinos Tubulares", "Efeitos e cinemático", "sf2", 0, 14, 72, True)]
)
PAD_SOUND_BY_NAME = {s.name: s for s in PAD_SOUNDS}
PAD_CATEGORIES = list(dict.fromkeys(s.cat for s in PAD_SOUNDS))
PAD_PRESETS = {
    "Worship Moderno": ["Bumbo Sub Worship", "Caixa Grave Profunda", "Caixa Grave + Palmas",
                        "Chimbal fechado — Power", "Chimbal aberto — Power", "Prato de ataque — Acústico",
                        "Tom Cinemático", "Swell (prato reverso)"],
    "Worship Acústico": ["Bumbo — Acústico", "Caixa — Acústico", "Aro (rim) — Acústico", "Shaker Suave",
                         "Chimbal fechado — Acústico", "Chimbal aberto — Acústico",
                         "Prato de condução — Acústico", "Pandeirola — Standard"],
    "Worship Sala Grande": ["Bumbo Boom Cinemático", "Caixa Grave Larga (sala)", "Caixa Grave + Palmas",
                            "Chimbal fechado — Acústico", "Chimbal aberto — Acústico",
                            "Prato de ataque — Acústico", "Tom Grave Cinemático", "Swell (prato reverso)"],
    "Cinemático / Intro": ["Bumbo Boom Cinemático", "Tom Grave Cinemático", "Tom Cinemático", "Taiko",
                           "Impacto (Boom + Prato)", "Swell (prato reverso)", "Tímpano", "Sino de Igreja"],
    "Balada Pop": ["Bumbo Punch (pop)", "Caixa — Power", "Palmas — 808/909", "Chimbal fechado — Standard",
                   "Chimbal aberto — Standard", "Prato de ataque — Power", "Tom grave — Power",
                   "Shaker — Standard"],
    "Eletrônico Ambient": ["Bumbo 808 Longo", "Caixa — Eletrônico", "Palmas Largas", "Chimbal fechado — 808/909",
                           "Chimbal aberto — 808/909", "Prato de ataque — Standard", "Tom grave — 808/909",
                           "Swell (prato reverso)"],
    "Kit Rock": ["Bumbo — Power", "Caixa — Power", "Aro (rim) — Standard", "Palmas — Standard",
                 "Chimbal fechado — Power", "Chimbal aberto — Power", "Prato de ataque — Power",
                 "Tom grave — Power"],
}
DEFAULT_PAD_PRESET = "Worship Moderno"

# pad contínuo (banco B): tom de cada pad e timbre
KEY_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
PAD_B_CHOICES = KEY_NAMES + ("Parar",)
DEFAULT_PAD_KEYS = ["C", "D", "E", "F", "G", "A", "B", "Parar"]
CONT_PAD_SOUNDS = ("Pad Halo", "Pad Atmosfera", "Pad Quente", "Pad Vozes", "Pad Cristal", "Pad Órgão",
                   "Pad Vidro", "Coral", "Cordas Lentas", "Pad Orquestra")

# no pad contínuo o som precisa se sustentar: o "Crystal" do GM é um sino que morre em ~4 s e o
# "Bowed Glass" cai quase a zero depois do ataque. Aqui: (banco, programa, CC7, velocidade)
CONT_PAD_PROGRAMS = {"Pad Cristal": (0, 102, 100, 90),       # Echo Drops: brilhante e sustentado
                     "Pad Vidro": (0, 93, 127, 120)}         # Metal Pad, com o volume compensado

# pad contínuo que balança: (velocidade em Hz, quanto vai para cada lado no pan 0-63, vibrato CC1)
# "Pad Órgão": órgão tonewheel com um giro lento de um lado para o outro, como uma caixa Leslie
CONT_PAD_LFO = {"Pad Órgão": (0.45, 42, 24)}

PAD_COUNT = 8
KNOB_COUNT = 8
BUTTONS = ("PLAY", "STOP", "REC", "BT", "ARP", "SC/CH", "KNOB-B", "PAD-B")

KNOB_FUNCS = ("Nenhuma", "Volume teclas", "Volume camada 1", "Volume camada 2", "Volume camada 3",
              "Volume camada 4", "Volume bateria", "Volume pad contínuo",
              "Reverb", "Shimmer", "Reverb da bateria", "Chorus", "Rotação (intensidade)", "Drive",
              "Delay (mix)", "Tempo do delay", "Repetições do delay", "Brilho", "Release", "Ataque",
              "Sensibilidade ao toque", "BPM", "Master")
DEFAULT_KNOB_FUNCS = ["Volume teclas", "Volume camada 2", "Volume bateria", "Volume pad contínuo",
                      "Reverb", "Shimmer", "Brilho", "Master"]
BUTTON_FUNCS = ("Nenhuma", "Tap tempo (BPM)", "Timbre anterior", "Próximo timbre", "Preset de pads anterior",
                "Próximo preset de pads", "Liga/desliga camada 2", "Parar pad contínuo",
                "Banco de pads A/B (tela)", "Rotação lenta/rápida", "Rotação liga/desliga",
                "Delay liga/desliga", "Drive liga/desliga", "Sustain (segurar)", "Oitava −", "Oitava +",
                "Pânico (soltar notas)")
# o que a alavanca/faixa de pitch do controlador faz
PITCH_FUNCS = ("Pitch (tom)", "Rotação (velocidade)", "Delay (tempo)")
DEFAULT_FX = dict(drive_on=False, drive=30, rot_on=False, rot_fast=False, rot_mix=100, delay_on=False,
                  delay_ms=380, delay_div=0, delay_fb=30, delay_mix=25, delay_ping=True,
                  # velocidade da rotação: Hz de cada modo, ou voltas por tempo quando segue o BPM
                  rot_sync=False, rot_slow_hz=0.8, rot_fast_hz=6.8, rot_slow_mult=0.5, rot_fast_mult=4.0)
DELAY_DIVS = ("ms (livre)", "1/4", "1/8", "1/8 pontuada", "1/16", "1/8 tercina")
DEFAULT_BUTTON_FUNCS = ["Timbre anterior", "Próximo timbre", "Parar pad contínuo", "Tap tempo (BPM)",
                        "Preset de pads anterior", "Próximo preset de pads", "Liga/desliga camada 2",
                        "Banco de pads A/B (tela)"]

MAX_LAYERS = 4
CH_LAYERS = (0, 1, 2, 3)                    # um canal (e uma saída de áudio) por camada das teclas
CH_KEYS1, CH_KEYS2 = CH_LAYERS[0], CH_LAYERS[1]
# o FluidSynth tem 8 saídas (canal % 8): canais 8-11 cairiam nas saídas das camadas, então não são usados
CH_CPAD = (4, 12)                           # pad contínuo (dois canais para o crossfade entre tons)
PAD_CHANNELS = (5, 6, 7, 13, 14, 15)        # pads da bateria (o último também é o da prévia)
ROUTE_PAD, ROUTE_DRUMS = 4, 5
LAYER_ZONES = ("all", "left", "right")      # camadas 3 e 4: teclado todo / abaixo / a partir da divisão


def channel_routes():
    """Destino de cada saída (grupo) do FluidSynth no mixer (kernels.mix_soundfont)."""
    import numpy as np

    from .audio.soundfont import N_GROUPS

    r = np.full(N_GROUPS, -1, dtype=np.int64)
    dests = ([(ch, i) for i, ch in enumerate(CH_LAYERS)] + [(ch, ROUTE_PAD) for ch in CH_CPAD]
             + [(ch, ROUTE_DRUMS) for ch in PAD_CHANNELS])
    for ch, dest in dests:
        g = ch % N_GROUPS
        assert r[g] in (-1, dest), f"canal {ch} cai na saída de outro destino"
        r[g] = dest
    return r
MELODIC_HOLD = 4.0                          # s até o note-off de pads melódicos


def note_name(n):
    return KEY_NAMES[n % 12] + str(n // 12 - 1)


def clean_fx(d):
    """Efeitos de uma camada vindos de fora: só chaves conhecidas, com o tipo do padrão."""
    out = {}
    for k, v in d.items():
        ref = DEFAULT_FX.get(k)
        if ref is None:
            continue
        if isinstance(ref, bool):
            if isinstance(v, bool):
                out[k] = v
        elif isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) < 1e6:
            out[k] = v
    return out


def clean_layer(d):
    """Camada 3/4 vinda de fora (sessão, preset compartilhado) ou None."""
    if not isinstance(d, dict) or d.get("sound") not in SOUND_BY_NAME:
        return None
    vol, octv = d.get("vol", 90), d.get("oct", 0)
    return dict(sound=d["sound"],
                vol=int(max(0, min(127, vol))) if isinstance(vol, (int, float)) else 90,
                oct=int(max(-2, min(2, octv))) if isinstance(octv, (int, float)) else 0,
                on=d.get("on", True) if isinstance(d.get("on", True), bool) else True,
                zone=d.get("zone", "all") if d.get("zone", "all") in LAYER_ZONES else "all")


# Pads na tela: índices 0-3 = fileira de cima, 4-7 = de baixo. No SMK-25 (e na maioria dos
# controladores com 8 pads) a fileira de BAIXO manda as notas 36-39 e a de cima 40-43.
DEFAULT_PADS = [[9, n] for n in (40, 41, 42, 43, 36, 37, 38, 39)]
DEFAULT_PADS_B = [[9, n] for n in (48, 49, 50, 51, 44, 45, 46, 47)]
OLD_DEFAULT_PADS = [[9, n] for n in range(36, 44)]          # padrão antigo (fileiras trocadas)
# PSR-E473: knobs A e B do LIVE CONTROL (CC 74 e 71) nos knobs 1 e 2 da tela; ele não tem pads MIDI
PSR_KNOBS = [[0, 74], [0, 71]]
OLD_DEFAULT_PADS_B = [[9, n] for n in range(44, 52)]
LATCH_GAP = 1.5     # s: o "0" de um botão comum chega ao soltar; depois disso é um toque novo
# CCs de uso geral (modulação, volume, sustain, efeitos, banco, "all notes off"…): não são knobs
GENERAL_CCS = {0, 1, 2, 7, 10, 11, 32, 64, 65, 66, 67, 91, 93, 120, 121, 122, 123, 124, 125, 126, 127}


class Instruments:
    """Estado e roteamento. Os métodos de nota/MIDI podem ser chamados de qualquer thread."""

    def __init__(self, engine):
        self.engine = engine
        self.sf = None
        self.error = None
        self.keys = dict(sound1="Pad Halo", sound2="Pad Vozes", mode2="layer", split=48,
                         vol1=100, vol2=80, layer2_on=True, oct2=0)
        self.ready = "Pad Celestial (Shimmer)"
        self.pad_preset = DEFAULT_PAD_PRESET
        self.pad_sounds = list(PAD_PRESETS[DEFAULT_PAD_PRESET])
        self.pad_keys = list(DEFAULT_PAD_KEYS)
        self.cont_sound = "Pad Halo"
        self.levels = dict(keys=80, drums=85, pad=70, reverb=110, chorus=40, shimmer=65,
                           drumverb=35, bright=64, release=64, attack=0, touch=100)
        self.mapping = dict(pads=[list(p) for p in DEFAULT_PADS],
                            pads_b=[list(p) for p in DEFAULT_PADS_B],
                            knobs=[None] * KNOB_COUNT, buttons=[None] * len(BUTTONS))
        self.midi_device = ""                # entrada MIDI cujo mapeamento está em self.mapping
        self.device_maps = {}                # entrada MIDI -> {"mapping": ..., "free_map": ...}
        self.knob_funcs = list(DEFAULT_KNOB_FUNCS)
        self.button_funcs = list(DEFAULT_BUTTON_FUNCS)
        self.knob_values = [0] * KNOB_COUNT
        self.screen_bank = 0                 # banco mostrado na tela (0 = A, 1 = B)
        self.device = "Teclado simples"         # instrumento desenhado na tela
        self.bpm = 100
        self._taps = []
        # efeitos (drive, rotação, delay) de cada camada; fx_layer = camada que a tela e os
        # controles MIDI estão editando (self.fx aponta para ela)
        self.layer_fx = [dict(DEFAULT_FX) for _ in range(MAX_LAYERS)]
        self.fx_layer = 0
        self.extra_layers = []               # camadas 3 e 4: dict(sound, vol, oct, on, zone)
        self.pad_eq = dict(DEFAULT_PAD_EQ)   # EQ e ambiente do pad contínuo (banco B)
        self.transpose = 0
        self.sustain = False
        self.free_map = {}                   # função -> ["cc"|"note", canal, número] (atalhos rápidos)
        # mute de emergência (faders da aba Configurações): guarda o volume, só silencia; não é salvo
        self.mutes = set()                   # "Volume camada N", "Volume pad contínuo", "Volume bateria"
        self.pitch_func = PITCH_FUNCS[0]     # alavanca de pitch: tom, velocidade da rotação ou tempo do delay
        self.bend = 0.0                      # posição da alavanca (-1 a 1) quando não é tom
        self.capture = False                 # diálogo de mapeamento aberto: só monitora
        self.on_monitor = lambda kind, ch, num, val: None
        self.on_control = lambda func, val: None
        self.cont_key = None                 # tom do pad contínuo ativo
        self._cp = {}                        # canal -> [nível atual, alvo, notas]
        self._lfo_phase = 0.0                # balanço do pad contínuo (CONT_PAD_LFO)
        self._cp_next = 0
        self._pad_chan = [PAD_CHANNELS[0]] * PAD_COUNT
        self._melodic_off = []               # [(instante, canal, nota)]
        self.drum_events = deque()           # (tipo, velocidade) para a bateria sintetizada
        self._held = {}
        self._btn_on = {}                    # botão (índice) -> instante do último valor > 0
        self._last_cc = None                 # (canal, nº, valor, instante): filtra a cópia em outro canal
        self.learn_steps = []
        self._learned = set()
        # ganchos da interface (chamados de qualquer thread; a UI os liga a sinais Qt)
        self.on_pad = lambda i, vel: None    # i >= 8: banco B
        self.on_key = lambda note, on: None
        self.on_knob = lambda i, val: None
        self.on_change = lambda: None
        self.on_learn = lambda: None
        self.on_unmapped = lambda ch, cc: None   # knob/fader que ainda não está ligado a nada

    # ------------------------------------------------------------------ camadas
    @property
    def fx(self):
        return self.layer_fx[self.fx_layer]

    @fx.setter
    def fx(self, value):
        self.layer_fx[self.fx_layer] = value

    def layer_count(self):
        return 2 + len(self.extra_layers)

    def add_layer(self, sound="Cordas Lentas"):
        """Nova camada (3 ou 4) no teclado todo. Devolve o número dela, ou None se já tem 4."""
        if self.layer_count() >= MAX_LAYERS:
            return None
        self.extra_layers.append(dict(sound=sound, vol=90, oct=0, on=True, zone="all"))
        n = self.layer_count()
        self.layer_fx[n - 1] = dict(DEFAULT_FX)
        self.ready = ""
        self.apply_all()
        self.apply_fx()
        self.on_change()
        return n

    def remove_layer(self, n):
        """Remove a camada n (3 ou 4); os efeitos das seguintes andam junto."""
        i = n - 3
        if not 0 <= i < len(self.extra_layers):
            return
        self.all_off()
        del self.extra_layers[i]
        del self.layer_fx[n - 1]
        self.layer_fx.append(dict(DEFAULT_FX))
        self.fx_layer = min(self.fx_layer, self.layer_count() - 1)
        self.ready = ""
        self.apply_all()
        self.apply_fx()
        self.on_change()

    def set_extra_layer(self, n, **values):
        lay = self.extra_layers[n - 3]
        if "sound" in values and values["sound"] not in SOUND_BY_NAME:
            values.pop("sound")
        if values.get("zone", "all") not in LAYER_ZONES:
            values.pop("zone")
        self.all_off()
        lay.update(values)
        self.ready = ""
        self.apply_all()
        self.on_change()

    def layer_sounds(self):
        """[(número, timbre, ligada)] de todas as camadas existentes."""
        k = self.keys
        out = [(1, k["sound1"], True), (2, k["sound2"], bool(k["sound2"] and k["layer2_on"]))]
        for i, lay in enumerate(self.extra_layers):
            out.append((3 + i, lay["sound"], bool(lay["on"])))
        return out

    # ------------------------------------------------------------------ motor
    def start(self, fs, max_block):
        from .audio.soundfont import SoundFontEngine, available

        old, self.sf = self.sf, None
        if old is not None:
            old.close()
        self._cp.clear()
        self.cont_key = None
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

    @staticmethod
    def _gain(level):
        return (level / 100.0) ** 2 * 2.0

    def keys_gain(self):
        return self._gain(self.levels["keys"])

    def drums_gain(self):
        return 0.0 if "Volume bateria" in self.mutes else self._gain(self.levels["drums"])

    def pad_gain(self):
        return 0.0 if "Volume pad contínuo" in self.mutes else self._gain(self.levels["pad"])

    def layer_muted(self, n):
        return f"Volume camada {n}" in self.mutes

    def set_mute(self, func, on):
        """Mute de emergência de um fader (camada 1-4, pad contínuo ou pads), sem mexer no volume."""
        if on:
            self.mutes.add(func)
        else:
            self.mutes.discard(func)
        if func.startswith("Volume camada ") and self.sf:
            n = int(func[-1])
            vol = self.layer_volume(n)
            if vol is not None:
                self.sf.cc(CH_LAYERS[n - 1], 7, 0 if on else int(vol))

    def shimmer_amount(self):
        return self.levels["shimmer"] / 100.0

    def apply_all(self):
        self.all_off()
        sounds = [self.keys.get("sound1"), self.keys.get("sound2")] + [x["sound"] for x in self.extra_layers]
        vols = [self.keys["vol1"], self.keys["vol2"]] + [x["vol"] for x in self.extra_layers]
        for chan, name in zip(CH_LAYERS, sounds):
            s = SOUND_BY_NAME.get(name or "")
            if s is not None and s.src == "sf2" and self.sf:
                self.sf.program(chan, s.bank, s.prog)
            if s is not None and s.src == "synth":
                self.engine.synth.apply_preset(s.synth_preset)
        self._assign_pad_channels()
        if self.sf:
            for i, (ch, vol) in enumerate(zip(CH_LAYERS, vols)):
                self.sf.cc(ch, 7, 0 if self.layer_muted(i + 1) else int(vol))
            for ch in CH_LAYERS:
                self.sf.cc(ch, 91, self.levels["reverb"])
                self.sf.cc(ch, 93, self.levels["chorus"])
            for ch in CH_CPAD:
                self.sf.cc(ch, 91, int(self.pad_eq["reverb"]))
                self.sf.cc(ch, 93, int(self.pad_eq["chorus"]))
            for ch in PAD_CHANNELS:
                self.sf.cc(ch, 91, self.levels["drumverb"])
                self.sf.cc(ch, 93, 0)
            for ch in CH_LAYERS:
                self.sf.cc(ch, 74, self.levels["bright"])
                self.sf.cc(ch, 72, self.levels["release"])
                self.sf.cc(ch, 73, self.levels["attack"])

    def _assign_pad_channels(self):
        """Um canal MIDI por programa (kit/timbre) usado nos pads."""
        progs = {}
        for i, name in enumerate(self.pad_sounds):
            s = PAD_SOUND_BY_NAME.get(name)
            if s is None or s.kind != "sf2":
                continue
            key = (s.bank, s.prog)
            if key not in progs:
                progs[key] = PAD_CHANNELS[min(len(progs), len(PAD_CHANNELS) - 1)]
                if self.sf:
                    self.sf.program(progs[key], s.bank, s.prog)
            self._pad_chan[i] = progs[key]

    # ------------------------------------------------------------------ timbres
    def set_ready(self, name):
        cfg = dict(sound2="", mode2="layer", split=48, vol1=100, vol2=70, layer2_on=True, oct2=0)
        cfg.update({k: v for k, v in READY[name].items() if k not in ("fx", "fx2")})
        self.keys.update(cfg)
        self.extra_layers = []
        fx = READY[name].get("fx", {})
        self.levels.update(reverb=fx.get("reverb", 45), chorus=fx.get("chorus", 15),
                           shimmer=fx.get("shimmer", 0), attack=fx.get("attack", 0))
        self.layer_fx = [dict(DEFAULT_FX) for _ in range(MAX_LAYERS)]
        for i, d in enumerate((fx, READY[name].get("fx2", {}))):       # efeitos da camada 1 e 2
            self.layer_fx[i].update({k: v for k, v in d.items() if k in DEFAULT_FX})
        self.fx_layer = 0
        self.ready = name
        self.apply_all()
        self.apply_fx()
        self.on_change()

    def set_pad_eq(self, **values):
        """Muda EQ/ambiente do pad contínuo (dsp/padeq.py); voicing vale no próximo tom."""
        self.pad_eq.update(values)
        self.apply_pad_eq()
        if self.sf and ("reverb" in values or "chorus" in values):
            for ch in CH_CPAD:
                self.sf.cc(ch, 91, int(self.pad_eq["reverb"]))
                self.sf.cc(ch, 93, int(self.pad_eq["chorus"]))
        if "voicing" in values and self.cont_key:
            self.start_cont_pad(self.cont_key)
        self.on_change()

    def apply_pad_eq(self):
        eq = getattr(self.engine, "pad_eq", None)
        if eq is not None:
            eq.configure(self.pad_eq)

    def apply_fx(self):
        rot = 4.0 ** self.bend if self.pitch_func == PITCH_FUNCS[1] else 1.0
        dly = 2.0 ** self.bend if self.pitch_func == PITCH_FUNCS[2] else 1.0
        for kfx, fx in zip(getattr(self.engine, "keys_fx", ()), self.layer_fx):
            kfx.configure(fx, self.bpm, rot, dly)

    def handle_bend(self, val):
        """Alavanca de pitch (14 bits, centro 8192): tom, velocidade da rotação ou tempo do delay."""
        if self.pitch_func == PITCH_FUNCS[0]:
            self.engine.send_event(Ly.EV_BEND, val)
            if self.sf:
                for c in CH_LAYERS:
                    self.sf.pitch_bend(c, val)
            return
        self.bend = max(-1.0, min(1.0, (val - 8192) / 8191.0))
        self.apply_fx()

    def set_pitch_func(self, func):
        if func not in PITCH_FUNCS:
            return
        self.pitch_func = func
        self.bend = 0.0
        self.engine.send_event(Ly.EV_BEND, 8192)          # sem nota desafinada presa ao trocar
        if self.sf:
            for c in CH_LAYERS:
                self.sf.pitch_bend(c, 8192)
        self.apply_fx()
        self.on_change()

    def set_sound(self, slot, name):
        self.keys["sound1" if slot == 1 else "sound2"] = name
        if slot == 2:
            self.keys["oct2"] = 0             # timbre 2 escolhido à mão volta para a oitava normal
        self.ready = ""
        self.apply_all()
        self.on_change()

    def set_pad_sound(self, i, name):
        self.pad_sounds[i] = name
        self.pad_preset = ""
        self._assign_pad_channels()
        self.on_change()

    def set_pad_preset(self, name):
        self.pad_preset = name
        self.pad_sounds = list(PAD_PRESETS[name])
        self._assign_pad_channels()
        self.on_change()

    def set_pad_key(self, i, key):
        self.pad_keys[i] = key
        self.on_change()

    def set_cont_sound(self, name):
        self.cont_sound = name
        restart = self.cont_key
        self.stop_cont_pad(immediate=True)
        if restart:
            self.start_cont_pad(restart)
        self.on_change()

    def step_ready(self, delta):
        names = list(READY)
        i = names.index(self.ready) if self.ready in names else -1
        self.set_ready(names[(i + delta) % len(names)])

    def step_pad_preset(self, delta):
        names = list(PAD_PRESETS)
        i = names.index(self.pad_preset) if self.pad_preset in names else -1
        self.set_pad_preset(names[(i + delta) % len(names)])

    def display_text(self):
        k = self.keys
        if self.ready:
            return self.ready
        s2 = k["sound2"] if (k["sound2"] and k["layer2_on"]) else ""
        if not s2:
            return k["sound1"]
        return (s2 + " | " + k["sound1"]) if k["mode2"] == "split" else (k["sound1"] + " + " + s2)

    def display_line2(self):
        cp = f"Pad contínuo: {self.cont_key}" if self.cont_key else f"Pads: {self.pad_preset or 'personalizado'}"
        return cp

    # ------------------------------------------------------------------ notas
    def _targets(self, note):
        """[(timbre, canal, oitava)] das camadas que tocam esta nota."""
        k = self.keys
        s1 = SOUND_BY_NAME.get(k["sound1"])
        s2 = SOUND_BY_NAME.get(k["sound2"]) if (k["sound2"] and k["layer2_on"]) else None
        split = s2 is not None and k["mode2"] == "split"
        out = []
        if s1 is not None and (not split or note >= k["split"]):
            out.append((s1, CH_KEYS1, 0))
        if s2 is not None and (not split or note < k["split"]):
            out.append((s2, CH_KEYS2, k.get("oct2", 0)))
        for i, lay in enumerate(self.extra_layers):
            s = SOUND_BY_NAME.get(lay["sound"])
            zone = lay.get("zone", "all")
            if s is None or not lay.get("on", True):
                continue
            if zone == "all" or (zone == "left" and note < k["split"]) or (zone == "right" and note >= k["split"]):
                out.append((s, CH_LAYERS[2 + i], lay.get("oct", 0)))
        return out

    def _touch(self, vel):
        t = self.levels.get("touch", 100) / 100.0
        return max(1, min(127, round(127 * ((1.0 - t) * 0.82 + t * vel / 127.0))))

    def key_on(self, note, vel=100):
        if note in self._held:
            self.key_off(note)
        vel = self._touch(vel)
        played = note + self.transpose
        targets = [(s, ch, played + 12 * o) for s, ch, o in self._targets(played)]
        self._held[note] = targets
        synth_done = False
        for s, ch, n in targets:
            if s.src == "synth":
                if not synth_done:
                    self.engine.send_event(Ly.EV_NOTE_ON, n, vel)
                    synth_done = True
            elif self.sf:
                self.sf.noteon(ch, n, vel)
        self.on_key(note, True)

    def key_off(self, note):
        for s, ch, n in self._held.pop(note, []):
            if s.src == "synth":
                self.engine.send_event(Ly.EV_NOTE_OFF, n, 0)
            elif self.sf:
                self.sf.noteoff(ch, n)
        self.on_key(note, False)

    def pad_hit(self, i, vel=110):
        """i 0-7: banco A (bateria); 8-15: banco B (pad contínuo)."""
        if i >= PAD_COUNT:
            key = self.pad_keys[i - PAD_COUNT]
            if key == "Parar" or key == self.cont_key:
                self.stop_cont_pad()
            else:
                self.start_cont_pad(key)
            self.on_pad(i, vel)
            self.on_change()
            return
        name = self.pad_sounds[i]
        if name.startswith(REC_PREFIX):
            self.engine.sampler.trigger(name[len(REC_PREFIX):], vel)
        s = PAD_SOUND_BY_NAME.get(name)
        if s is not None:
            if s.kind == "synth":
                self.drum_events.append((s.synth, vel))
            elif self.sf:
                ch = self._pad_chan[i]
                self.sf.noteon(ch, s.note, vel)
                if s.melodic:
                    self._melodic_off.append((time.monotonic() + MELODIC_HOLD, ch, s.note))
        self.on_pad(i, vel)

    def preview_pad_sound(self, name, vel=110):
        """Toca um som de pad (usado no diálogo de escolha) sem alterar os pads."""
        if name.startswith(REC_PREFIX):
            self.engine.sampler.trigger(name[len(REC_PREFIX):], vel)
            return
        s = PAD_SOUND_BY_NAME.get(name)
        if s is None:
            return
        if s.kind == "synth":
            self.drum_events.append((s.synth, vel))
        elif self.sf:
            ch = PAD_CHANNELS[-1]
            self.sf.program(ch, s.bank, s.prog)
            self.sf.noteon(ch, s.note, vel)
            self._melodic_off.append((time.monotonic() + MELODIC_HOLD, ch, s.note))

    def end_preview(self):
        self._assign_pad_channels()          # o canal de prévia pode ser de um pad

    def all_off(self):
        for note in list(self._held):
            self.key_off(note)
        if self.sf:
            for ch in CH_LAYERS + PAD_CHANNELS:
                self.sf.all_off(ch)
        self.engine.send_event(Ly.EV_ALL_OFF)

    # ------------------------------------------------------------------ pad contínuo (banco B)
    def start_cont_pad(self, key):
        if not self.sf:
            return
        s = SOUND_BY_NAME.get(self.cont_sound)
        if s is None or s.src != "sf2":
            return
        root = 48 + KEY_NAMES.index(key)
        pe = self.pad_eq
        notes = [root + d for d in VOICINGS.get(pe["voicing"], VOICINGS["cheio"])]
        ch = CH_CPAD[self._cp_next % 2]
        self._cp_next += 1
        old = self._cp.get(ch)
        if old:                               # canal ainda soando: corta antes de reutilizar
            for n in old[2]:
                self.sf.noteoff(ch, n)
        for c, st in self._cp.items():        # o tom anterior sai em fade
            if c != ch:
                st[1] = 0.0
        bank, prog, vol, vel = CONT_PAD_PROGRAMS.get(self.cont_sound, (s.bank, s.prog, 100, 90))
        self.sf.program(ch, bank, prog)
        self.sf.cc(ch, 7, vol)
        lfo = CONT_PAD_LFO.get(self.cont_sound)
        self.sf.cc(ch, 10, 64)                # centro; o balanço (se houver) sai do tick
        self.sf.cc(ch, 1, lfo[2] if lfo else 0)
        self.sf.cc(ch, 11, 0)
        self.sf.cc(ch, 91, int(pe["reverb"]))
        self.sf.cc(ch, 93, int(pe["chorus"]))
        for n in notes:
            self.sf.noteon(ch, n, vel)
        self._cp[ch] = [0.0, 127.0, notes]
        self.cont_key = key

    def stop_cont_pad(self, immediate=False):
        for ch, st in list(self._cp.items()):
            st[1] = 0.0
            if immediate and self.sf:
                for n in st[2]:
                    self.sf.noteoff(ch, n)
                del self._cp[ch]
        self.cont_key = None

    def tick(self, dt):
        """Chamado pela interface ~30x/s: fades do pad contínuo e note-offs programados."""
        sf = self.sf
        if sf is None:
            return
        for ch, st in list(self._cp.items()):
            cur, target, notes = st
            if cur == target:
                continue
            rate = 127.0 * dt / (self.pad_eq["fade_in"] if target > cur else self.pad_eq["fade_out"])
            cur = min(target, cur + rate) if target > cur else max(target, cur - rate)
            st[0] = cur
            sf.cc(ch, 11, int(cur))
            if cur <= 0.0 and target <= 0.0:
                for n in notes:
                    sf.noteoff(ch, n)
                del self._cp[ch]
        lfo = CONT_PAD_LFO.get(self.cont_sound)
        if lfo and self._cp:
            rate, depth, _ = lfo
            if self.pitch_func == PITCH_FUNCS[1]:      # alavanca na rotação: acelera o balanço também
                rate *= 4.0 ** self.bend
            self._lfo_phase = (self._lfo_phase + rate * dt) % 1.0
            pan = int(64 + depth * math.sin(2 * math.pi * self._lfo_phase))
            for ch in self._cp:
                sf.cc(ch, 10, pan)
        if self._melodic_off:
            now = time.monotonic()
            due = [x for x in self._melodic_off if x[0] <= now]
            if due:
                self._melodic_off = [x for x in self._melodic_off if x[0] > now]
                for _, ch, note in due:
                    sf.noteoff(ch, note)

    # ------------------------------------------------------------------ knobs e botões
    def set_knob(self, i, value):
        """value 0..127 vindo do knob físico ou do knob desenhado na tela."""
        self.knob_values[i] = value
        self.apply_knob_func(self.knob_funcs[i], value)
        self.on_knob(i, value)

    def layer_volume(self, n):
        """Volume (0-127) da camada n (1-4); None se a camada não existe."""
        if n <= 2:
            return self.keys["vol1" if n == 1 else "vol2"]
        lay = self.extra_layers[n - 3] if n - 3 < len(self.extra_layers) else None
        return lay["vol"] if lay else None

    def set_layer_volume(self, n, value):
        """Volume da camada n (1-4), pelo painel ou por um knob; camada que não existe: nada."""
        value = int(max(0, min(127, value)))
        if n <= 2:
            self.keys["vol1" if n == 1 else "vol2"] = value
        elif n - 3 < len(self.extra_layers):
            self.extra_layers[n - 3]["vol"] = value
        else:
            return
        if self.sf:
            self.sf.cc(CH_LAYERS[n - 1], 7, 0 if self.layer_muted(n) else value)

    def synth_layer_gain(self):
        """Ganho do synth AmpSim: volume da camada ligada que usa um timbre "(AmpSim)", na mesma
        curva do CC7 do FluidSynth ((v/127)²). None = nenhuma camada usa o synth (fica o anterior)."""
        k = self.keys
        layers = [(k["sound1"], k["vol1"], True), (k["sound2"], k["vol2"], bool(k["sound2"] and k["layer2_on"]))]
        layers += [(x["sound"], x["vol"], x.get("on", True)) for x in self.extra_layers]
        for n, (name, vol, on) in enumerate(layers, start=1):
            s = SOUND_BY_NAME.get(name or "")
            if on and s is not None and s.src == "synth":
                return 0.0 if self.layer_muted(n) else (vol / 127.0) ** 2
        return None

    def apply_knob_func(self, func, value):
        lv = self.levels
        pct = round(value / 127 * 100)
        if func == "Volume teclas":
            lv["keys"] = pct
        elif func == "Volume bateria":
            lv["drums"] = pct
        elif func == "Volume pad contínuo":
            lv["pad"] = pct
        elif func == "Shimmer":
            lv["shimmer"] = pct
        elif func.startswith("Volume camada "):
            self.set_layer_volume(int(func[-1]), value)
        elif func == "Master":
            self.engine.master = (value / 127) ** 2 * 2.0
        elif func in ("Rotação (intensidade)", "Drive", "Delay (mix)", "Tempo do delay",
                      "Repetições do delay"):
            fx = self.fx
            if func == "Rotação (intensidade)":
                fx["rot_mix"] = pct
                fx["rot_on"] = pct > 0
            elif func == "Drive":
                fx["drive"] = pct
                fx["drive_on"] = pct > 0
            elif func == "Delay (mix)":
                fx["delay_mix"] = pct
                fx["delay_on"] = pct > 0
            elif func == "Tempo do delay":
                fx["delay_ms"] = round(80 + value / 127 * 1120)
                fx["delay_div"] = 0
            else:
                fx["delay_fb"] = pct
            self.apply_fx()
        elif func == "Sensibilidade ao toque":
            lv["touch"] = pct
        elif func == "BPM":
            self.set_bpm(60 + value / 127 * 120)
        elif func == "Reverb da bateria":
            lv["drumverb"] = value
            if self.sf:
                for ch in PAD_CHANNELS:
                    self.sf.cc(ch, 91, value)
        elif func in ("Reverb", "Chorus", "Brilho", "Release", "Ataque"):
            key, cc = {"Reverb": ("reverb", 91), "Chorus": ("chorus", 93), "Brilho": ("bright", 74),
                       "Release": ("release", 72), "Ataque": ("attack", 73)}[func]
            lv[key] = value
            if self.sf:                     # só as teclas: o pad contínuo tem reverb/chorus próprios
                for ch in CH_LAYERS:
                    self.sf.cc(ch, cc, value)

    # ------------------------------------------------------------------ andamento
    def set_bpm(self, bpm):
        self.bpm = int(max(40, min(220, round(bpm))))
        self.engine.synth.set_bpm(self.bpm)
        self.apply_fx()
        self.on_change()

    def tap_tempo(self):
        """Bata no ritmo: a média dos últimos toques define o BPM e o pulso recomeça no toque."""
        now = time.monotonic()
        if self._taps and now - self._taps[-1] > 2.0:
            self._taps = []
        self._taps = (self._taps + [now])[-5:]
        self.engine.synth.restart_pulse()
        if len(self._taps) >= 2:
            gaps = [b - a for a, b in zip(self._taps, self._taps[1:])]
            gaps.sort()
            self.set_bpm(60.0 / gaps[len(gaps) // 2])
        else:
            self.on_change()

    def button(self, i):
        self.do_button(self.button_funcs[i])

    def do_button(self, func):
        fx = self.fx
        if func == "Rotação lenta/rápida":
            fx["rot_on"] = True
            fx["rot_fast"] = not fx["rot_fast"]
            self.apply_fx()
            self.on_change()
        elif func == "Rotação liga/desliga":
            fx["rot_on"] = not fx["rot_on"]
            self.apply_fx()
            self.on_change()
        elif func == "Delay liga/desliga":
            fx["delay_on"] = not fx["delay_on"]
            self.apply_fx()
            self.on_change()
        elif func == "Drive liga/desliga":
            fx["drive_on"] = not fx["drive_on"]
            self.apply_fx()
            self.on_change()
        elif func == "Sustain (segurar)":
            self.sustain = not self.sustain
            val = 127 if self.sustain else 0
            self.engine.send_event(Ly.EV_SUSTAIN, val)
            if self.sf:
                for c in CH_LAYERS:
                    self.sf.cc(c, 64, val)
            self.on_change()
        elif func in ("Oitava −", "Oitava +"):
            self.transpose = max(-24, min(24, self.transpose + (12 if func.endswith("+") else -12)))
            self.on_change()
        elif func == "Tap tempo (BPM)":
            self.tap_tempo()
        elif func == "Timbre anterior":
            self.step_ready(-1)
        elif func == "Próximo timbre":
            self.step_ready(1)
        elif func == "Preset de pads anterior":
            self.step_pad_preset(-1)
        elif func == "Próximo preset de pads":
            self.step_pad_preset(1)
        elif func == "Liga/desliga camada 2":
            self.keys["layer2_on"] = not self.keys["layer2_on"]
            self.ready = ""
            self.all_off()
            self.on_change()
        elif func == "Parar pad contínuo":
            self.stop_cont_pad()
            self.on_change()
        elif func == "Banco de pads A/B (tela)":
            self.screen_bank = 1 - self.screen_bank
            self.on_change()
        elif func.startswith("Pânico"):
            self.all_off()
            self.stop_cont_pad(immediate=True)
            self.on_change()

    # ------------------------------------------------------------------ MIDI (thread do winmm)
    def handle_midi(self, status, d1, d2):
        kind, ch = status & 0xF0, status & 0x0F
        if kind == 0xB0:
            # o PSR manda cada knob/pedal nos canais das partes Main e Dual, juntos: a 2ª vez é cópia
            # (sem isso o assistente aprendia um knob físico como dois e o 2º ia para um slot escondido)
            now = time.monotonic()
            last = self._last_cc
            self._last_cc = (ch, d1, d2, now)
            if last is not None and last[0] != ch and last[1:3] == (d1, d2) and now - last[3] < 0.015:
                return
        if kind in (0x90, 0xB0) or (kind == 0x80):
            self.on_monitor("cc" if kind == 0xB0 else "note", ch, d1, d2 if kind != 0x80 else 0)
        elif kind in (0xC0, 0xE0):
            self.on_monitor("pc" if kind == 0xC0 else "bend", ch, d1, d2)
        if self.capture:
            return
        if kind == 0xC0 and not self.learn_steps:
            for i, b in enumerate(self.mapping["buttons"]):
                if b == ["pc", ch, d1]:
                    self.button(i)
                    return
        if kind in (0x90, 0xB0) and self.free_map:
            key = ["cc" if kind == 0xB0 else "note", ch, d1]
            for func, k in self.free_map.items():
                if k == key:
                    if func in KNOB_FUNCS and kind == 0xB0:
                        self.apply_knob_func(func, d2)
                        self.on_control(func, d2)
                    elif func in BUTTON_FUNCS and d2 > 0:
                        self.do_button(func)
                        self.on_control(func, 127)
                    return
        if self.learn_steps:
            self._learn(kind, ch, d1, d2)
            return
        m = self.mapping
        if kind in (0x80, 0x90):
            on = kind == 0x90 and d2 > 0
            # botão mapeado vem antes de tudo: um botão que manda nota (ex.: o PAD-B do M-VAVE)
            # nunca toca som de pad ou de tecla
            for i, b in enumerate(m["buttons"]):
                if b == ["note", ch, d1]:
                    if on:
                        self.button(i)
                    return
            # o banco da tela vem primeiro: se o controlador manda as mesmas notas nos dois bancos,
            # o PAD-B (mapeado como botão) troca o banco e os pads seguem a tela
            banks = ((0, "pads"), (1, "pads_b"))
            for bank, key in (banks if self.screen_bank == 0 else banks[::-1]):
                for i, pad in enumerate(m[key]):
                    if pad == [ch, d1]:
                        if on:
                            if self.screen_bank != bank:
                                self.screen_bank = bank
                                self.on_change()
                            self.pad_hit(i + bank * PAD_COUNT, d2)
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
            if d1 not in GENERAL_CCS and not any(b == ["cc", ch, d1] for b in m["buttons"]):
                self.on_unmapped(ch, d1)
            for i, b in enumerate(m["buttons"]):
                if b == ["cc", ch, d1]:
                    now = time.monotonic()
                    if d2 > 0:
                        self._btn_on[i] = now
                        self.button(i)
                    elif now - self._btn_on.get(i, 0.0) > LATCH_GAP:
                        self.button(i)              # botão que trava: 127 num toque, 0 no seguinte
                    return
            if d1 == 64:
                self.engine.send_event(Ly.EV_SUSTAIN, d2)
            elif d1 == 1:
                self.engine.send_event(Ly.EV_MOD, d2)
            elif d1 in (120, 123):
                self.all_off()
                return
            if self.sf:
                for c in CH_LAYERS:
                    self.sf.cc(c, d1, d2)
        elif kind == 0xE0:
            self.handle_bend(d1 | (d2 << 7))

    # ------------------------------------------------------------------ um mapeamento por controlador
    @staticmethod
    def default_mapping(name):
        """Mapeamento inicial de um controlador pelo nome da entrada MIDI."""
        from .audio.hotplug import instrument_of
        m = dict(pads=[list(p) for p in DEFAULT_PADS], pads_b=[list(p) for p in DEFAULT_PADS_B],
                 knobs=[None] * KNOB_COUNT, buttons=[None] * len(BUTTONS))
        if instrument_of(name or "") == "Yamaha PSR-E473":
            m["pads"] = [None] * PAD_COUNT          # as teclas do PSR não podem virar pads
            m["pads_b"] = [None] * PAD_COUNT
            m["knobs"][:len(PSR_KNOBS)] = [list(k) for k in PSR_KNOBS]
        return m

    def _device_maps_state(self):
        maps = {k: v for k, v in self.device_maps.items()}
        if self.midi_device:
            maps[self.midi_device] = self._map_snapshot()
        return maps

    def _map_snapshot(self):
        return {"mapping": {k: [list(x) if x else None for x in v] for k, v in self.mapping.items()},
                "free_map": dict(self.free_map)}

    def use_midi_device(self, name):
        """Abriu outra entrada MIDI: guarda o mapeamento da anterior e põe o desta (ou o padrão dela).
        Assim os pads do M-VAVE não viram teclas do PSR (e o contrário).
        Devolve "mesmo", "assumido" (1ª vez nesta versão), "restaurado" ou "novo" (nunca mapeado)."""
        if not name or name == self.midi_device:
            return "mesmo"
        from .audio.hotplug import instrument_of
        if self.midi_device:
            self.device_maps[self.midi_device] = self._map_snapshot()
            saved = self.device_maps.get(name)
        else:                                        # 1ª vez nesta versão: o mapeamento atual é dele
            saved = self.device_maps.get(name) or self._map_snapshot()
            if instrument_of(name) == "Yamaha PSR-E473":
                saved["mapping"]["pads"] = [None] * PAD_COUNT
                saved["mapping"]["pads_b"] = [None] * PAD_COUNT
        status = "assumido" if not self.midi_device else ("restaurado" if saved else "novo")
        self.midi_device = name
        if saved:
            m = saved.get("mapping", {})
            for k, n in (("pads", PAD_COUNT), ("pads_b", PAD_COUNT), ("knobs", KNOB_COUNT),
                         ("buttons", len(BUTTONS))):
                v = m.get(k)
                self.mapping[k] = [list(x) if x else None for x in v] if isinstance(v, list) and len(v) == n \
                    else self.default_mapping(name)[k]
            fm = saved.get("free_map", {})
            self.free_map = {f: v for f, v in fm.items() if (f in KNOB_FUNCS or f in BUTTON_FUNCS)
                             and isinstance(v, list) and len(v) == 3} if isinstance(fm, dict) else {}
        else:
            self.mapping = self.default_mapping(name)
            self.free_map = {}
        self.on_learn()
        return status

    def describe_midi(self, kind, ch, num, val):
        """Texto do monitor MIDI: o que o AmpSim faz com esta mensagem."""
        m = self.mapping
        if kind == "pc":
            for i, b in enumerate(m["buttons"]):
                if b == ["pc", ch, num]:
                    return f"Troca de programa {num} · canal {ch + 1} → botão {BUTTONS[i]}"
            return f"Troca de programa {num} · canal {ch + 1} → não usado"
        if kind == "bend":
            what = {PITCH_FUNCS[0]: "afinação das teclas", PITCH_FUNCS[1]: "velocidade da rotação",
                    PITCH_FUNCS[2]: "tempo do delay"}[self.pitch_func]
            return f"Pitch bend · canal {ch + 1} → {what}"
        key = [kind, ch, num]
        head = f"{'CC' if kind == 'cc' else 'Nota'} {num} · canal {ch + 1}" + (f" · valor {val}" if kind == "cc" else "")
        for func, k in self.free_map.items():
            if k == key:
                return f"{head} → {func}"
        if kind == "note":
            if val == 0:
                return f"{head} (soltou)"
            for bank, name in ((0, "pads"), (1, "pads_b")):
                for i, pad in enumerate(m[name]):
                    if pad == [ch, num]:
                        return f"{head} → pad {i + 1} do banco {'AB'[bank]}"
            for i, b in enumerate(m["buttons"]):
                if b == key:
                    return f"{head} → botão {BUTTONS[i]}"
            return f"{head} → tecla {note_name(num)}"
        for i, k in enumerate(m["knobs"]):
            if k == [ch, num]:
                return f"{head} → knob {i + 1} ({self.knob_funcs[i]})"
        for i, b in enumerate(m["buttons"]):
            if b == key:
                return f"{head} → botão {BUTTONS[i]}"
        general = {1: "modulação", 7: "volume", 10: "pan", 11: "expressão", 64: "sustain", 66: "sostenuto",
                   67: "pedal suave", 91: "reverb", 93: "chorus"}
        if num in general:
            return f"{head} → {general[num]}"
        return f"{head} → NÃO MAPEADO"

    # ------------------------------------------------------------------ assistente de mapeamento
    def start_learning(self, what=("pads", "pads_b", "knobs", "buttons")):
        steps = []
        for kind, count in (("pads", PAD_COUNT), ("pads_b", PAD_COUNT), ("knobs", KNOB_COUNT),
                            ("buttons", len(BUTTONS))):
            if kind in what:
                steps += [(kind, i) for i in range(count)]
        self._learned = set()
        self.learn_steps = steps
        self.on_learn()

    def skip_learning_step(self):
        if self.learn_steps:
            kind = self.learn_steps[0][0]
            self.learn_steps.pop(0)
            if kind == "pads_b" and self.learn_steps and self.learn_steps[0][0] != "pads_b":
                self.screen_bank = 0
            self.on_learn()

    def stop_learning(self):
        self.learn_steps = []
        self.screen_bank = 0
        self.on_learn()

    def learning_prompt(self):
        if not self.learn_steps:
            return ""
        kind, i = self.learn_steps[0]
        if kind == "pads":
            return f"Toque o PAD {i + 1} no controlador"
        if kind == "pads_b":
            pre = "Aperte PAD-B no controlador e " if i == 0 else ""
            return f"{pre}toque o PAD {i + 1} (banco B)"
        if kind == "knobs":
            return f"Gire o KNOB {i + 1} no controlador"
        return f"Aperte o botão {BUTTONS[i]} no controlador"

    def _learn(self, kind, ch, d1, d2):
        step, i = self.learn_steps[0]
        if kind == 0x90 and d2 > 0:
            key = ("note", ch, d1)
        elif kind == 0xB0:
            key = ("cc", ch, d1)
        elif kind == 0xC0 and step == "buttons":
            key = ("pc", ch, d1)
        else:
            return
        # CC já aprendido = resto do giro de um knob; nota já usada só vale de novo em outro banco
        seen = key if key[0] != "note" else (step, key)
        if seen in self._learned:
            return
        if step in ("pads", "pads_b") and key[0] == "note":
            self.mapping[step][i] = [ch, d1]
        elif step == "knobs" and key[0] == "cc":
            self.mapping["knobs"][i] = [ch, d1]
        elif step == "buttons" and (key[0] in ("note", "pc") or d2 > 0):
            self.mapping["buttons"][i] = list(key)
        elif step == "pads_b" and key[0] == "cc":
            return                        # o próprio botão PAD-B: ignora
        else:
            return
        self._learned.add(seen)
        self.learn_steps.pop(0)
        if step == "pads":
            self.pad_hit(i, d2)
        if self.learn_steps and self.learn_steps[0][0] == "pads_b":
            self.screen_bank = 1
        elif step == "pads_b":
            self.screen_bank = 0
        self.on_learn()

    # ------------------------------------------------------------------ persistência
    def get_state(self):
        return dict(keys=dict(self.keys), ready=self.ready, pad_preset=self.pad_preset,
                    pad_sounds=list(self.pad_sounds), pad_keys=list(self.pad_keys),
                    cont_sound=self.cont_sound, levels=dict(self.levels),
                    mapping={k: list(v) for k, v in self.mapping.items()},
                    knob_funcs=list(self.knob_funcs), button_funcs=list(self.button_funcs),
                    device=self.device, bpm=self.bpm, fx=dict(self.layer_fx[0]), free_map=dict(self.free_map),
                    layer_fx=[dict(f) for f in self.layer_fx], fx_layer=self.fx_layer,
                    extra_layers=[dict(x) for x in self.extra_layers],
                    pad_eq=dict(self.pad_eq), pitch_func=self.pitch_func,
                    midi_device=self.midi_device, device_maps=self._device_maps_state())

    def load_state(self, st):
        if not st:
            return
        self.keys.update({k: v for k, v in st.get("keys", {}).items() if k in self.keys})
        for k in ("sound1", "sound2"):
            if self.keys[k] and self.keys[k] not in SOUND_BY_NAME:
                self.keys[k] = "Piano de Cauda" if k == "sound1" else ""
        self.ready = st.get("ready", "") if st.get("ready", "") in READY else ""
        sounds = st.get("pad_sounds")
        if isinstance(sounds, list) and len(sounds) == PAD_COUNT:
            self.pad_sounds = [s if s in PAD_SOUND_BY_NAME else PAD_PRESETS[DEFAULT_PAD_PRESET][i]
                               for i, s in enumerate(sounds)]
            self.pad_preset = st.get("pad_preset", "") if st.get("pad_preset") in PAD_PRESETS else ""
        keys = st.get("pad_keys")
        if isinstance(keys, list) and len(keys) == PAD_COUNT and all(k in PAD_B_CHOICES for k in keys):
            self.pad_keys = list(keys)
        if isinstance(st.get("device"), str):
            self.device = st["device"]
        if isinstance(st.get("layer_fx"), list):
            self.layer_fx = [dict(DEFAULT_FX) for _ in range(MAX_LAYERS)]
            for i, d in enumerate(st["layer_fx"][:MAX_LAYERS]):
                if isinstance(d, dict):
                    self.layer_fx[i] = dict(DEFAULT_FX, **clean_fx(d))
        elif isinstance(st.get("fx"), dict):              # sessão antiga: um conjunto só
            self.layer_fx = [dict(DEFAULT_FX) for _ in range(MAX_LAYERS)]
            self.layer_fx[0] = dict(DEFAULT_FX, **clean_fx(st["fx"]))
        if isinstance(st.get("extra_layers"), list):
            self.extra_layers = [x for x in (clean_layer(d) for d in st["extra_layers"][:MAX_LAYERS - 2]) if x]
        if isinstance(st.get("fx_layer"), int):
            self.fx_layer = max(0, min(st["fx_layer"], self.layer_count() - 1))
        if isinstance(st.get("pad_eq"), dict):
            self.pad_eq.update(clean_pad_eq(st["pad_eq"]))
        if st.get("pitch_func") in PITCH_FUNCS:
            self.pitch_func = st["pitch_func"]
            self.bend = 0.0
        if isinstance(st.get("free_map"), dict):
            self.free_map = {k: v for k, v in st["free_map"].items()
                             if (k in KNOB_FUNCS or k in BUTTON_FUNCS) and isinstance(v, list) and len(v) == 3}
        if isinstance(st.get("bpm"), (int, float)):
            self.bpm = int(st["bpm"])
            self.engine.synth.set_bpm(self.bpm)
        if st.get("cont_sound") in CONT_PAD_SOUNDS:
            self.cont_sound = st["cont_sound"]
        self.levels.update({k: v for k, v in st.get("levels", {}).items() if k in self.levels})
        for k, n in (("pads", PAD_COUNT), ("pads_b", PAD_COUNT), ("knobs", KNOB_COUNT),
                     ("buttons", len(BUTTONS))):
            v = st.get("mapping", {}).get(k)
            if isinstance(v, list) and len(v) == n:
                self.mapping[k] = v
        # sessões com o padrão antigo dos pads (fileiras invertidas no SMK-25): corrige sozinho
        if self.mapping["pads"] == OLD_DEFAULT_PADS:
            self.mapping["pads"] = [list(p) for p in DEFAULT_PADS]
        if self.mapping["pads_b"] == OLD_DEFAULT_PADS_B:
            self.mapping["pads_b"] = [list(p) for p in DEFAULT_PADS_B]
        if isinstance(st.get("device_maps"), dict):
            self.device_maps = {name: m for name, m in st["device_maps"].items()
                                if isinstance(name, str) and isinstance(m, dict)}
        if isinstance(st.get("midi_device"), str):
            self.midi_device = st["midi_device"]
        for attr, valid, n in (("knob_funcs", KNOB_FUNCS, KNOB_COUNT),
                               ("button_funcs", BUTTON_FUNCS, len(BUTTONS))):
            v = st.get(attr)
            if isinstance(v, list) and len(v) == n and all(x in valid for x in v):
                setattr(self, attr, list(v))
        self.apply_all()
        self.apply_fx()
        self.apply_pad_eq()
