"""Presets de fábrica. Só é preciso listar o que difere do padrão."""


def _p(on, **values):
    """on = efeitos ligados; values = {efeito: {param: valor}}."""
    vals = {k: dict(v) for k, v in values.items()}
    for eff in on:
        vals.setdefault(eff, {})["on"] = True
    return {"values": vals}


def _nam(capture, cab, extra=(), treble_cut=False, eq=None, **values):
    """Timbre com captura NAM no lugar do amplificador interno (as capturas são só o amp,
    sem falante, então o gabinete do AmpSim fica ligado)."""
    on = ("nam", "cab") + tuple(extra)
    values.setdefault("cab", {})["model"] = cab
    values["nam"] = dict(file=capture)
    if treble_cut:      # captura muito brilhante: segura os agudos no EQ
        values["eq"] = dict(b3=-2, b4=-5)
        on += ("eq",)
    return _p(on, **values)


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
                             amp=dict(model=5, gain=7, bass=5, mid=7, treble=5.5, presence=6, master=6),
                             cab=dict(model=0), delay=dict(time=420, feedback=35, mix=25, tone=5),
                             reverb=dict(mix=18)),
        "Hi-Gain Rítmico": _p(("gate", "overdrive", "amp", "cab", "eq"),
                              gate=dict(threshold=-55, release=40),
                              overdrive=dict(drive=0.5, tone=6, level=7),
                              amp=dict(model=2, gain=7.5, bass=6, mid=4, treble=6.5, presence=6.5, master=6),
                              cab=dict(model=0), eq=dict(b0=-2, b1=-2, b4=1)),
        "Brit 800 Rock": _p(("gate", "amp", "cab", "reverb"),
                            amp=dict(model=5, gain=6, bass=5.5, mid=6.5, treble=6, presence=6, master=6),
                            cab=dict(model=0), reverb=dict(mix=12)),
        "AC Top Boost Jangle": _p(("comp", "amp", "cab", "delay", "reverb"),
                                  comp=dict(threshold=-26, ratio=3, makeup=5),
                                  amp=dict(model=6, gain=4.5, bass=4.5, mid=5, treble=6.5, presence=5,
                                           master=6),
                                  cab=dict(model=1), delay=dict(time=360, feedback=25, mix=18),
                                  reverb=dict(size=55, mix=22)),
        "NAM · Fender Twin Limpo": _nam("Fender Twin Reverb (limpo)", cab=1, extra=("chorus", "reverb"),
                                        eq=None, reverb=dict(size=60, mix=25),
                                        chorus=dict(rate=0.6, depth=40, mix=35), treble_cut=True),
        "NAM · Vox AC15 Top Boost": _nam("Vox AC15 Top Boost", cab=1, extra=("reverb",),
                                         reverb=dict(size=50, mix=20)),
        "NAM · JCM2000 Crunch": _nam("Marshall JCM2000 Crunch", cab=0, extra=("reverb",),
                                     reverb=dict(mix=12)),
        "NAM · JCM900 Lead": _nam("Marshall JCM900 Lead", cab=0, extra=("delay", "reverb"),
                                  delay=dict(time=420, feedback=30, mix=22, tone=5),
                                  reverb=dict(mix=15)),
        "NAM · Mesa Mark IV": _nam("Mesa Boogie Mark IV", cab=0, extra=("reverb",), reverb=dict(mix=12)),
        "NAM · 5150 Metal": _nam("EVH 5150 Block Letter (boost)", cab=0, extra=()),
        "NAM · Soldano Crunch": _nam("Soldano SLO pedal (crunch)", cab=0, extra=("reverb",),
                                     reverb=dict(mix=12)),
        "NAM · Orange Rockerverb": _nam("Orange Rockerverb", cab=0, extra=("reverb",),
                                        reverb=dict(mix=15)),
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
        "NAM · dUg DP3X Drive": _nam("Baixo - Tech21 dUg DP3X (drive)", cab=4, extra=("comp",),
                                     comp=dict(threshold=-20, ratio=4, makeup=4)),
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

# Redutor de ruído ligado em todos os presets de guitarra e baixo (menos o DI puro), e gate
# mais alto nos timbres com distorção, onde o chiado da entrada é amplificado.
_DENOISE = {
    "guitar": dict(on=True, hum=2, hiss=50, sens=-45, lowcut=40, highcut=9000),
    "bass": dict(on=True, hum=2, hiss=40, sens=-45, lowcut=25, highcut=7000),
}
_GATE = {"Crunch Clássico": -50, "Solo com Delay": -50, "Hi-Gain Rítmico": -48, "Baixo Fuzz": -50,
         "Brit 800 Rock": -50, "NAM · JCM2000 Crunch": -50, "NAM · JCM900 Lead": -48,
         "NAM · Mesa Mark IV": -48, "NAM · 5150 Metal": -46, "NAM · Soldano Crunch": -50,
         "NAM · Orange Rockerverb": -48, "NAM · dUg DP3X Drive": -50}
for _kind, _cfg in _DENOISE.items():
    for _name, _preset in FACTORY[_kind].items():
        if _name.startswith("DI"):
            continue
        _preset["values"]["denoise"] = dict(_cfg)
        if _name in _GATE:
            _g = _preset["values"].setdefault("gate", {})
            _g.update(on=True, threshold=_GATE[_name])
