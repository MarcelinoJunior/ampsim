"""Presets de fábrica. Só é preciso listar o que difere do padrão."""


def _p(on, **values):
    """on = efeitos ligados; values = {efeito: {param: valor}}."""
    vals = {k: dict(v) for k, v in values.items()}
    for eff in on:
        vals.setdefault(eff, {})["on"] = True
    return {"values": vals}


FACTORY = {
    "guitar": {
        "Crunch Clássico": _p(("gate", "amp", "cab", "reverb"),
                              amp=dict(model=1, gain=5.5, bass=5, mid=6, treble=6, presence=5, master=6),
                              cab=dict(model=0), reverb=dict(mix=15)),
        "Limpo com Chorus": _p(("comp", "amp", "cab", "chorus", "reverb"),
                               comp=dict(threshold=-24, ratio=3, makeup=5),
                               amp=dict(model=0, gain=3, bass=5, mid=4, treble=6.5, presence=6),
                               cab=dict(model=2), chorus=dict(rate=0.7, depth=55, mix=45),
                               reverb=dict(size=60, mix=25)),
        "Solo com Delay": _p(("gate", "overdrive", "amp", "cab", "delay", "reverb"),
                             overdrive=dict(drive=3, tone=6, level=7),
                             amp=dict(model=2, gain=6, bass=5, mid=7, treble=5.5, presence=6, master=6),
                             cab=dict(model=0), delay=dict(time=420, feedback=35, mix=25, tone=5),
                             reverb=dict(mix=18)),
        "Hi-Gain Rítmico": _p(("gate", "overdrive", "amp", "cab", "eq"),
                              gate=dict(threshold=-55, release=40),
                              overdrive=dict(drive=0.5, tone=6, level=7),
                              amp=dict(model=2, gain=7.5, bass=6, mid=4, treble=6.5, presence=6.5, master=6),
                              cab=dict(model=0), eq=dict(b0=-2, b1=-2, b4=1)),
        "DI (sem efeitos)": _p(()),
    },
    "bass": {
        "Baixo Limpo": _p(("comp", "amp", "cab"),
                          comp=dict(threshold=-22, ratio=4, attack=10, release=150, makeup=5),
                          amp=dict(model=3, gain=3.5, bass=6, mid=5, treble=5, presence=4, blend=30),
                          cab=dict(model=3)),
        "Baixo Rock": _p(("comp", "amp", "cab", "eq"),
                         comp=dict(threshold=-20, ratio=5, makeup=5),
                         amp=dict(model=4, gain=4.5, bass=6, mid=6.5, treble=5.5, blend=45),
                         cab=dict(model=4), eq=dict(b1=-2, b3=2)),
        "Baixo Fuzz": _p(("overdrive", "amp", "cab"),
                         overdrive=dict(drive=8, tone=4, level=6),
                         amp=dict(model=4, gain=6, bass=6, mid=6, blend=50), cab=dict(model=3)),
        "Baixo Dub": _p(("comp", "amp", "cab"),
                        comp=dict(threshold=-25, ratio=6, makeup=6),
                        amp=dict(model=3, gain=2.5, bass=8, mid=4, treble=2.5, presence=2, blend=20),
                        cab=dict(model=5)),
        "DI (sem efeitos)": _p(()),
    },
    "pads": {
        "Pad Ambiente": _p(("chorus", "delay", "reverb"),
                           chorus=dict(rate=0.35, depth=60, mix=50),
                           delay=dict(time=480, feedback=40, mix=20, tone=4, ping=1),
                           reverb=dict(size=85, damping=40, mix=40)),
        "Pad Seco": _p(("chorus",), chorus=dict(rate=0.5, depth=40, mix=35)),
        "Pad no Amp": _p(("amp", "cab", "reverb"),
                         amp=dict(model=0, gain=2, bass=5, mid=5, treble=5),
                         cab=dict(model=1), reverb=dict(mix=30)),
    },
}

DEFAULT_PRESET = {"guitar": "Crunch Clássico", "bass": "Baixo Limpo", "pads": "Pad Ambiente"}
