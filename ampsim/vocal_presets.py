"""Presets de fábrica da aba Vocal. Só é preciso listar o que difere do padrão (dsp/vocal.py).

Mesmo formato dos presets das outras trilhas (presets.py): {"values": {efeito: {param: valor, "on": True}}}.
Gate: limiares de -50 a -53 dB (RMS), para um chiado de microfone típico (-60 a -65 dBFS) fechar entre
as frases (o gate fecha 3 dB abaixo do limiar). Nenhum preset mexe no bloco "track" (liga/desliga, volume, ganho da entrada): trocar de preset no meio
do culto não pode abrir o microfone nem mudar o volume da voz.
"""


def _p(on, **values):
    """on = efeitos ligados; values = {efeito: {param: valor}}."""
    vals = {k: dict(v) for k, v in values.items()}
    for eff in on:
        vals.setdefault(eff, {})["on"] = True
    return {"values": vals}


_CLEAN = ("hpf", "gate", "comp", "eq", "deess")

VOCAL_FACTORY = {
    "Voz limpa (culto)": _p(_CLEAN + ("reverb",),
                            hpf=dict(freq=100, slope=1), gate=dict(threshold=-52, range=20, release=200),
                            comp=dict(amount=40, speed=1), eq=dict(body=-1, presence=2, air=1.5),
                            deess=dict(amount=40, freq=6500),
                            reverb=dict(type=0, size=35, predelay=15, mix=12)),
    "Voz com reverb (adoração)": _p(_CLEAN + ("reverb",),
                                    hpf=dict(freq=110, slope=1), gate=dict(threshold=-52, range=18, release=250),
                                    comp=dict(amount=50, speed=1), eq=dict(body=-1.5, presence=2.5, air=2.5),
                                    deess=dict(amount=50, freq=6500),
                                    reverb=dict(type=1, size=60, predelay=30, mix=24)),
    "Ministração (reverb longo)": _p(_CLEAN + ("delay", "reverb"),
                                     hpf=dict(freq=100, slope=1), gate=dict(threshold=-53, range=15, release=250),
                                     comp=dict(amount=45, speed=0), eq=dict(body=-1, presence=2, air=3),
                                     deess=dict(amount=50, freq=6800),
                                     delay=dict(sync=1, feedback=25, mix=10, ping=1),
                                     reverb=dict(type=1, size=90, predelay=40, mix=32)),
    "Voz falada (pregação)": _p(_CLEAN + ("reverb",),
                                hpf=dict(freq=140, slope=1), gate=dict(threshold=-50, range=25, release=150),
                                comp=dict(amount=65, speed=1), eq=dict(low=-2, body=1, presence=3, air=0),
                                deess=dict(amount=55, freq=6000),
                                reverb=dict(type=0, size=20, predelay=0, mix=5)),
    "Backing vocal (dobrado)": _p(_CLEAN + ("double", "reverb"),
                                  hpf=dict(freq=160, slope=1), gate=dict(threshold=-52, range=25, release=180),
                                  comp=dict(amount=55, speed=1), eq=dict(low=-3, body=-2, presence=1, air=2),
                                  deess=dict(amount=55, freq=6500), double=dict(mix=55, width=90),
                                  reverb=dict(type=1, size=55, predelay=25, mix=22)),
    "Voz seca (só limpeza)": _p(_CLEAN,
                                hpf=dict(freq=90, slope=1), gate=dict(threshold=-52, range=20, release=200),
                                comp=dict(amount=35, speed=1), deess=dict(amount=35, freq=6500)),
    "Rádio/telefone (efeito)": _p(("hpf", "gate", "comp", "eq"),
                                  hpf=dict(freq=200, slope=1), gate=dict(threshold=-50, range=30, release=150),
                                  comp=dict(amount=70, speed=2),
                                  eq=dict(low=-12, body=4, presence=6, air=-12, highcut=3500)),
}

DEFAULT_VOCAL_PRESET = "Voz limpa (culto)"
