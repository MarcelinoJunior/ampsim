"""Equalizador do pad contínuo (banco B): cortes de graves/agudos, três faixas e largura estéreo.

Os coeficientes são calculados na thread de UI (configure); o mix_soundfont só aplica os biquads.
"""
import numpy as np

from .filters import IDENTITY, biquad, db
from .params import Param

N_STAGES = 7                    # corte grave (2x, 24 dB/oit), graves, médios, agudos, corte agudo (2x)

PAD_EQ_PARAMS = (
    Param("lowcut", "Corte de graves", 20.0, 800.0, 20.0, "Hz", log=True),
    Param("low", "Graves", -15.0, 15.0, 0.0, "dB"),
    Param("mid_f", "Médios (freq.)", 150.0, 6000.0, 900.0, "Hz", log=True),
    Param("mid", "Médios", -15.0, 15.0, 0.0, "dB"),
    Param("mid_q", "Médios (largura)", 0.3, 4.0, 0.8, "Q", log=True),
    Param("high", "Agudos", -15.0, 15.0, 0.0, "dB"),
    Param("highcut", "Corte de agudos", 1000.0, 20000.0, 20000.0, "Hz", log=True),
    Param("width", "Largura estéreo", 0.0, 200.0, 100.0, "%"),
    Param("gain", "Volume do EQ", -12.0, 12.0, 0.0, "dB"),
)
# o resto do pad contínuo: ambiente e entrada/saída
PAD_AMB_PARAMS = (
    Param("reverb", "Reverb", 0.0, 127.0, 120.0, step=1.0),
    Param("chorus", "Chorus", 0.0, 127.0, 60.0, step=1.0),
    Param("shimmer", "Shimmer", 0.0, 100.0, 70.0, "%", step=1.0),
    Param("fade_in", "Entrada (fade-in)", 0.1, 10.0, 2.5, "s", log=True),
    Param("fade_out", "Saída (fade-out)", 0.1, 12.0, 3.5, "s", log=True),
)
DEFAULT_PAD_EQ = {p.key: p.default for p in PAD_EQ_PARAMS + PAD_AMB_PARAMS}
DEFAULT_PAD_EQ.update(on=True, voicing="cheio")

# tons do pad: notas somadas à tônica (o "cheio" é o som original do pad contínuo)
VOICINGS = {
    "cheio": (-12, 0, 7, 12, 19),
    "sem grave (oitava acima)": (0, 7, 12, 19),
    "só tônica e quinta": (0, 7),
    "grave profundo": (-24, -12, 0, 7, 12),
    "aberto (quintas e nonas)": (-12, 0, 7, 14, 19),
}

PAD_EQ_PRESETS = {
    "Original (sem EQ)": {},
    "Mais escuro (tira o brilho)": dict(high=-6.0, highcut=5500.0),
    "Sem embolar (tira graves)": dict(lowcut=180.0, low=-3.0),
    "Atrás da banda (só o meio)": dict(lowcut=250.0, highcut=6000.0, mid=2.0, mid_f=1200.0),
    "Aberto e largo": dict(high=3.0, width=160.0, lowcut=60.0),
    "Quente e próximo": dict(low=3.0, mid=-3.0, mid_f=2500.0, high=-3.0, width=80.0),
}


def clean_pad_eq(d):
    """Só as chaves conhecidas, com tipo e faixa válidos (arquivos de preset vêm de fora)."""
    out = {}
    for p in PAD_EQ_PARAMS + PAD_AMB_PARAMS:
        v = d.get(p.key)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v:
            out[p.key] = float(min(max(v, p.lo), p.hi))
    if isinstance(d.get("on"), bool):
        out["on"] = d["on"]
    if d.get("voicing") in VOICINGS:
        out["voicing"] = d["voicing"]
    return out


class PadEQ:
    def __init__(self, fs):
        self.fs = fs
        self.BQ = np.zeros((2 * N_STAGES, 5))       # coeficientes repetidos: linhas 0-6 L, 7-13 R
        self.Z = np.zeros((2 * N_STAGES, 2))
        self.P = np.zeros(3)                         # liga (0/1), largura, ganho linear
        self.configure(DEFAULT_PAD_EQ)

    def configure(self, v):
        fs = self.fs
        lc, hc = v["lowcut"], v["highcut"]
        stages = (
            biquad("hp", fs, lc, q=0.54) if lc > 21.0 else IDENTITY,
            biquad("hp", fs, lc, q=1.31) if lc > 21.0 else IDENTITY,
            biquad("ls", fs, 220.0, v["low"], q=0.7) if v["low"] else IDENTITY,
            biquad("peak", fs, v["mid_f"], v["mid"], q=v["mid_q"]) if v["mid"] else IDENTITY,
            biquad("hs", fs, 4500.0, v["high"], q=0.7) if v["high"] else IDENTITY,
            biquad("lp", fs, hc, q=0.54) if hc < 19500.0 else IDENTITY,
            biquad("lp", fs, hc, q=1.31) if hc < 19500.0 else IDENTITY,
        )
        for i, c in enumerate(stages):
            self.BQ[i] = c
            self.BQ[i + N_STAGES] = c
        self.P[0] = 1.0 if v.get("on", True) else 0.0
        self.P[1] = v["width"] / 100.0
        self.P[2] = db(v["gain"])

    def reset(self):
        self.Z[:] = 0.0

    def response(self, freqs):
        """Resposta em dB (canal esquerdo, sem largura) para desenhar a curva na tela."""
        z = np.exp(-2j * np.pi * np.asarray(freqs) / self.fs)
        h = np.ones_like(z)
        for b0, b1, b2, a1, a2 in self.BQ[:N_STAGES]:
            h *= (b0 + b1 * z + b2 * z * z) / (1.0 + a1 * z + a2 * z * z)
        return 20.0 * np.log10(np.maximum(np.abs(h), 1e-6)) + 20.0 * np.log10(self.P[2])
