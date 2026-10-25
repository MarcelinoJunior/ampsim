"""Definição dos parâmetros (faixas, padrões, rótulos) e dos modelos de amp/gabinete."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Param:
    key: str
    label: str
    lo: float = 0.0
    hi: float = 10.0
    default: float = 5.0
    unit: str = ""
    log: bool = False                 # mapeamento logarítmico no knob
    choices: tuple = ()               # se preenchido, é um seletor
    step: float = 0.0                 # 1.0 para inteiros

    @property
    def is_choice(self):
        return bool(self.choices)


@dataclass(frozen=True)
class EffectDef:
    key: str
    title: str
    params: tuple = field(default_factory=tuple)


# --------------------------------------------------------------------- amplificadores
# Modelos inspirados em amplificadores clássicos (nomes próprios, sem marcas). A ordem dos
# cinco primeiros é mantida para compatibilidade com sessões e presets já salvos.
AMP_MODELS = (
    dict(name="Blackface Twin", head=0.3, inspired="Fender Twin Reverb", skin="blackface", brand="Fender", model="Twin Reverb",
         stages=1, gain_db=(0, 28), bias=0.05, hpf=60, inter1=11000, inter2=9000, bass_f=100,
         mid_f=450, mid_q=0.6, mid_off=-4.0, treb_f=2600, pres_f=5000, depth=(90, 2.0), sag=0.35),
    dict(name="Brit Plexi", head=0.6, inspired="Marshall Super Lead 1959", skin="plexi", brand="Marshall", model="Super Lead 1959",
         stages=2, gain_db=(4, 40), bias=0.2, hpf=80, inter1=7500, inter2=6500, bass_f=120,
         mid_f=650, mid_q=0.7, mid_off=2.5, treb_f=2800, pres_f=3800, depth=(100, 2.0), sag=0.7),
    dict(name="Recto Modern", head=1.0, inspired="Mesa/Boogie Dual Rectifier", skin="recto", brand="Mesa/Boogie", model="Dual Rectifier",
         stages=3, gain_db=(16, 60), bias=0.3, hpf=160, inter1=5500, inter2=5000, bass_f=100,
         mid_f=700, mid_q=0.9, mid_off=-3.0, treb_f=3200, pres_f=4000, depth=(85, 4.0), sag=0.25),
    dict(name="SVT Classic", head=0.4, inspired="Ampeg SVT", skin="svt", brand="Ampeg", model="SVT Classic",
         stages=1, gain_db=(0, 26), bias=0.1, hpf=28, inter1=8000, inter2=8000, bass_f=60,
         mid_f=500, mid_q=0.7, mid_off=0.0, treb_f=2500, pres_f=5000, depth=(55, 2.5), sag=0.5),
    dict(name="Bass Drive", head=1.0, inspired="pré-amps de baixo modernos (B7K)", skin="bassdrive", brand="", model="Bass Drive",
         stages=2, gain_db=(6, 42), bias=0.2, hpf=35, inter1=5000, inter2=4500, bass_f=80,
         mid_f=1000, mid_q=0.8, mid_off=2.0, treb_f=2600, pres_f=4500, depth=(60, 2.5), sag=0.3),
    dict(name="Brit 800", head=0.8, inspired="Marshall JCM800 2203", skin="jcm800", brand="Marshall", model="JCM800 2203",
         stages=2, gain_db=(10, 48), bias=0.25, hpf=110, inter1=6500, inter2=6000, bass_f=120,
         mid_f=750, mid_q=0.8, mid_off=3.0, treb_f=3200, pres_f=3600, depth=(100, 2.5), sag=0.5),
    dict(name="AC Top Boost", head=0.5, inspired="Vox AC30 Top Boost", skin="ac", brand="Vox", model="AC30 Top Boost",
         stages=2, gain_db=(0, 34), bias=0.12, hpf=90, inter1=9000, inter2=8000, bass_f=140,
         mid_f=900, mid_q=0.6, mid_off=-2.0, treb_f=3000, pres_f=2500, depth=(110, 1.0), sag=0.6),
)

# --------------------------------------------------------------------- gabinetes
# (tipo, freq, ganho dB, Q)
CAB_MODELS = (
    ("4x12 Fechado", [("hp", 75, 0, 0.8), ("peak", 110, 4, 1.4), ("peak", 400, -3, 1.0),
                      ("peak", 2400, 4, 1.3), ("lp", 5200, 0, 0.75), ("lp", 6500, 0, 0.6)]),
    ("2x12 Aberto", [("hp", 65, 0, 0.7), ("peak", 130, 2.5, 1.2), ("peak", 600, -2, 1.0),
                     ("peak", 2000, 3.5, 1.2), ("lp", 5800, 0, 0.75), ("lp", 7500, 0, 0.6)]),
    ("1x12 Combo", [("hp", 90, 0, 0.7), ("peak", 160, 2, 1.3), ("peak", 1800, 3, 1.0),
                    ("peak", 3500, -2, 2.0), ("lp", 4800, 0, 0.8), ("lp", 6000, 0, 0.6)]),
    ("Baixo 8x10", [("hp", 38, 0, 0.8), ("peak", 80, 3, 1.2), ("peak", 800, -3, 0.9),
                    ("peak", 2500, 2, 1.2), ("lp", 4500, 0, 0.75), ("lp", 6000, 0, 0.6)]),
    ("Baixo 4x10", [("hp", 45, 0, 0.8), ("peak", 100, 2.5, 1.2), ("peak", 600, -2, 1.0),
                    ("peak", 3000, 3, 1.4), ("lp", 5500, 0, 0.75), ("lp", 7000, 0, 0.6)]),
    ("Baixo 1x15", [("hp", 32, 0, 0.8), ("peak", 70, 4, 1.0), ("peak", 500, -2, 1.0),
                    ("lp", 2600, 0, 0.75), ("lp", 3600, 0, 0.6)]),
)
CAB_IR_INDEX = len(CAB_MODELS)          # última opção = IR carregada de arquivo
CAB_CHOICES = tuple(n for n, _ in CAB_MODELS) + ("IR (arquivo .wav)",)

EQ_FREQS = (100, 400, 1000, 2500, 6000)

ONOFF = ("Não", "Sim")

# --------------------------------------------------------------------- cadeia de efeitos
HUM_CHOICES = ("Desligado", "50 Hz", "60 Hz")
HUM_FREQS = (0, 50, 60)

EFFECTS = (
    EffectDef("denoise", "Redutor de Ruído", (
        Param("hum", "Anti-hum (rede)", 0, 2, 2, choices=HUM_CHOICES),
        Param("hiss", "Anti-chiado", 0, 100, 50, "%"),
        Param("sens", "Limiar", -80, -20, -50, "dB"),
        Param("lowcut", "Corte grave", 20, 250, 30, "Hz", log=True),
        Param("highcut", "Corte agudo", 2000, 20000, 9000, "Hz", log=True),
    )),
    EffectDef("gate", "Noise Gate", (
        Param("threshold", "Limiar", -90, -20, -60, "dB"),
        Param("release", "Release", 5, 500, 60, "ms", log=True),
    )),
    EffectDef("comp", "Compressor", (
        Param("threshold", "Limiar", -50, 0, -20, "dB"),
        Param("ratio", "Razão", 1, 20, 4, ":1", log=True),
        Param("attack", "Ataque", 0.1, 100, 5, "ms", log=True),
        Param("release", "Release", 10, 1000, 120, "ms", log=True),
        Param("makeup", "Ganho", 0, 24, 4, "dB"),
    )),
    EffectDef("overdrive", "Overdrive", (
        Param("drive", "Drive", 0, 10, 5),
        Param("tone", "Tom", 0, 10, 5),
        Param("level", "Nível", 0, 10, 5),
    )),
    EffectDef("amp", "Amplificador", (
        Param("model", "Modelo", 0, len(AMP_MODELS) - 1, 0,
              choices=tuple(f'{m["name"]}  (estilo {m["inspired"]})' for m in AMP_MODELS)),
        Param("gain", "Gain", 0, 10, 4),
        Param("bass", "Graves", 0, 10, 5),
        Param("mid", "Médios", 0, 10, 5),
        Param("treble", "Agudos", 0, 10, 5),
        Param("presence", "Presença", 0, 10, 5),
        Param("master", "Master", 0, 10, 5),
        Param("blend", "Blend DI", 0, 100, 0, "%"),
    )),
    EffectDef("nam", "Captura NAM (amp real)", (
        Param("input", "Entrada", -24, 24, 0, "dB"),
        Param("output", "Saída", -24, 24, 0, "dB"),
    )),
    EffectDef("vst", "Plugin VST3", (
        Param("mix", "Mix", 0, 100, 100, "%"),
    )),
    EffectDef("cab", "Gabinete", (
        Param("model", "Gabinete", 0, len(CAB_CHOICES) - 1, 0, choices=CAB_CHOICES),
        Param("level", "Nível", -12, 12, 0, "dB"),
    )),
    EffectDef("eq", "Equalizador", tuple(
        Param(f"b{i}", (f"{f // 1000}k" if f >= 1000 and f % 1000 == 0 else
                        f"{f / 1000:g}k" if f >= 1000 else str(f)), -12, 12, 0, "dB")
        for i, f in enumerate(EQ_FREQS)
    ) + (Param("level", "Nível", -12, 12, 0, "dB"),)),
    EffectDef("chorus", "Chorus", (
        Param("rate", "Veloc.", 0.05, 5, 0.8, "Hz", log=True),
        Param("depth", "Profund.", 0, 100, 50, "%"),
        Param("mix", "Mix", 0, 100, 50, "%"),
    )),
    EffectDef("delay", "Delay", (
        Param("time", "Tempo", 20, 2000, 380, "ms", log=True),
        Param("feedback", "Feedback", 0, 95, 35, "%"),
        Param("mix", "Mix", 0, 100, 25, "%"),
        Param("tone", "Tom", 0, 10, 6),
        Param("ping", "Ping-pong", 0, 1, 0, choices=ONOFF),
    )),
    EffectDef("reverb", "Reverb", (
        Param("size", "Tamanho", 0, 100, 55, "%"),
        Param("damping", "Abafar", 0, 100, 45, "%"),
        Param("mix", "Mix", 0, 100, 22, "%"),
        Param("width", "Largura", 0, 100, 100, "%"),
    )),
)

TRACK_PARAMS = (
    Param("input_gain", "Entrada", -24, 24, 0, "dB"),
    Param("volume", "Volume", -60, 12, 0, "dB"),
    Param("pan", "Pan", -100, 100, 0, ""),
)

EFFECT_BY_KEY = {e.key: e for e in EFFECTS}

WAVES = ("Seno", "Triângulo", "Serra", "Quadrada")

SYNTH_GROUPS = (
    ("Osciladores", (
        Param("wave1", "Onda 1", 0, 3, 2, choices=WAVES),
        Param("wave2", "Onda 2", 0, 3, 2, choices=WAVES),
        Param("mix2", "Mix Osc 2", 0, 100, 50, "%"),
        Param("semi2", "Semitom 2", -24, 24, 0, "st", step=1.0),
        Param("detune", "Detune", 0, 50, 9, "ct"),
        Param("sub", "Sub", 0, 100, 0, "%"),
    )),
    ("Filtro", (
        Param("cutoff", "Corte", 30, 18000, 1800, "Hz", log=True),
        Param("reso", "Resson.", 0, 95, 15, "%"),
        Param("fenv", "Env→Filtro", 0, 6, 1.5, "oct"),
        Param("keytrk", "Key track", 0, 100, 50, "%"),
        Param("f_attack", "Ataque", 1, 8000, 900, "ms", log=True),
        Param("f_decay", "Decay", 10, 8000, 1500, "ms", log=True),
        Param("f_sustain", "Sustain", 0, 100, 40, "%"),
        Param("f_release", "Release", 10, 10000, 1500, "ms", log=True),
    )),
    ("Amplitude", (
        Param("a_attack", "Ataque", 1, 8000, 600, "ms", log=True),
        Param("a_decay", "Decay", 10, 8000, 1000, "ms", log=True),
        Param("a_sustain", "Sustain", 0, 100, 85, "%"),
        Param("a_release", "Release", 10, 10000, 1800, "ms", log=True),
    )),
    ("Pulso no tempo (BPM)", (
        Param("pulse_depth", "Pulso", 0, 100, 0, "%"),
        Param("pulse_filt", "Pulso→Filtro", 0, 4, 0, "oct"),
        Param("pulse_div", "Divisão", 0, 4, 1, choices=("1/4", "1/8", "1/8 pontuada", "1/16", "1/2")),
        Param("pulse_shape", "Forma", 0, 2, 0, choices=("Pulso (sidechain)", "Ondas (vai e volta)", "Gate (picado)")),
        Param("pulse_retrig", "Começa na nota", 0, 1, 1, choices=("Não", "Sim")),
    )),
    ("Modulação / Saída", (
        Param("lfo_rate", "LFO veloc.", 0.05, 10, 0.3, "Hz", log=True),
        Param("lfo_depth", "LFO→Filtro", 0, 2, 0.25, "oct"),
        Param("velsens", "Veloc. sens.", 0, 100, 50, "%"),
        Param("bend_range", "Pitch bend", 0, 12, 2, "st", step=1.0),
        Param("volume", "Volume", -40, 12, 0, "dB"),
    )),
)
SYNTH_PARAMS = tuple(p for _, ps in SYNTH_GROUPS for p in ps)
